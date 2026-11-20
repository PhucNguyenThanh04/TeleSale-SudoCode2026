import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from eval_harness.benchmark_runner import run_scenario_call, conversation_measurement
from eval_harness.test_entrypoint_parity import Runtime


@pytest.mark.parametrize('config', ['full', 'baseline_no_memory'])
def test_stream_ttft_is_first_delta_and_total_includes_terminal_persistence(monkeypatch, config):
    clock = [0.0]
    class StreamRuntime(Runtime):
        async def stream(self, request):
            identity = {'client_msg_id': str(request.client_msg_id), 'session_id': str(request.session_id)}
            clock[0] += .05
            yield {'event': 'delta', **identity, 'seq': 1, 'text': 'Giá '}
            clock[0] += .07
            yield {'event': 'delta', **identity, 'seq': 2, 'text': '50.000đ.'}
            clock[0] += .02
            yield {'event': 'done', **identity, 'agent_text': 'Giá 50.000đ.',
                   'memory_update': {'turn_saved': True, 'status': 'pending'}}
    monkeypatch.setattr('eval_harness.benchmark_runner.time.perf_counter', lambda: clock[0])
    rows = asyncio.run(run_scenario_call(runtime=StreamRuntime(), scenario_id='X', call_name='call_1',
        call_spec={'customer_turns': ['Giá bao nhiêu?']}, base_date=date(2026, 11, 17),
        customer_phone='0900000000', config=config, delivery_mode='text'))
    latency = rows[0]['latency']
    assert latency['ttft_ms'] == 50 and latency['total_ms'] == 140
    assert latency['ttft_is_proxy'] is False and latency['answer_delta_count'] == 2
    assert latency['stream_completed'] is True


@pytest.mark.parametrize('fault', ['missing_done', 'no_delta', 'identity', 'changed_answer', 'error'])
def test_broken_stream_never_becomes_a_fabricated_ttft(fault):
    class Broken(Runtime):
        async def stream(self, request):
            identity = {'client_msg_id': str(request.client_msg_id), 'session_id': str(request.session_id)}
            if fault != 'no_delta':
                yield {'event': 'delta', **identity, 'seq': 1, 'text': 'Xin tư vấn.'}
            if fault == 'missing_done': return
            if fault == 'identity': identity['session_id'] = 'wrong'
            yield {'event': 'error' if fault == 'error' else 'done', **identity,
                   'agent_text': 'wrong' if fault == 'changed_answer' else 'Xin tư vấn.'}
    with pytest.raises(RuntimeError):
        asyncio.run(run_scenario_call(runtime=Broken(), scenario_id='X', call_name='call_1',
            call_spec={'customer_turns': ['Xin tư vấn']}, base_date=date(2026, 11, 17),
            customer_phone='0900000000', delivery_mode='text'))


def test_text_measurement_always_uses_guarded_streaming():
    value = conversation_measurement('text')
    assert value['ttft_basis'] == 'streaming_guarded_answer_delta'
    assert value['ttft_is_proxy'] is False


def test_paired_cli_defaults_to_streaming_without_mode_selectors(tmp_path, monkeypatch):
    from eval_harness.run_official import main
    (tmp_path/'run.json').write_text(json.dumps({'status': 'failed'}))
    monkeypatch.setattr('sys.argv', ['run_official', '--btc-root', str(tmp_path)])
    with patch('eval_harness.run_official.run_pair', new_callable=AsyncMock, return_value=tmp_path) as pair:
        with pytest.raises(SystemExit): main()
    assert pair.await_count == 1
    assert not {'streaming', 'delivery_mode', 'agent'} & pair.call_args.kwargs.keys()


@pytest.mark.parametrize('evidence', ['valid', 'no_count', 'unfinished', 'proxy', 'report_mismatch', 'time_reversed'])
def test_acceptance_requires_bound_stream_evidence_not_just_a_smaller_number(tmp_path, evidence):
    from eval_harness.test_official_pipeline import _case, BTC
    from eval_harness.official_pipeline import publish_pair
    from eval_harness.m1_acceptance import inspect_run
    scenarios, traces, metadata = _case(tmp_path)
    measurement = conversation_measurement('text')
    metadata['model_params'].update(streaming=True, conversation_measurement=measurement)
    for path in traces.values():
        row = json.loads(path.read_text())
        total = row['latency']['total_ms']
        row['latency'].update(ttft_ms=total-1, ttft_is_proxy=False, streaming=True,
                              answer_delta_count=1, stream_completed=True)
        if evidence == 'no_count': row['latency'].pop('answer_delta_count')
        if evidence == 'unfinished': row['latency']['stream_completed'] = False
        if evidence == 'proxy': row['latency']['ttft_is_proxy'] = True
        if evidence == 'time_reversed': row['latency']['ttft_ms'] = total+1
        path.write_text(json.dumps(row)+'\n')
        report_path = path.with_suffix('.report.json')
        report = json.loads(report_path.read_text())
        report['streaming'] = evidence != 'report_mismatch'
        report_path.write_text(json.dumps(report))
    result = publish_pair(scenarios, traces['full'], traces['baseline_no_memory'],
                          tmp_path/'btc_score.json', metadata, btc_root=BTC)
    (tmp_path/'run.json').write_text(json.dumps({'status':result['status'], 'score':'btc_score.json',
        'conversation_measurement':measurement, 'subset':False,
        'manifests':{key:key+'.manifest.json' for key in traces},
        'traces':{key:path.name for key,path in traces.items()}}))
    report = inspect_run(tmp_path, btc_root=BTC)
    gates = {c['name']:c for c in report['checks']}
    assert gates['artifact_integrity']['status'] == 'pass'
    assert gates['ttft_measured']['status'] == ('pass' if evidence == 'valid' else 'missing')
