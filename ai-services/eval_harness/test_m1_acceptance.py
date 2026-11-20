from copy import deepcopy
from eval_harness.test_support import LEGACY_TEXT_MEASUREMENT
import json
from pathlib import Path

import pytest

from eval_harness.test_official_pipeline import _case, BTC
from eval_harness.official_pipeline import publish_pair


def saved_pair(tmp_path, measurement=None, unequal_nonstreaming_times=False, warmup=None):
    scenarios, traces, metadata = _case(tmp_path)
    if warmup is not None:
        metadata['model_params']['warmup_turns'] = warmup
        for path in traces.values():
            report_path = path.with_suffix('.report.json')
            report = json.loads(report_path.read_text())
            report['warmup_turns'] = warmup
            report_path.write_text(json.dumps(report))
    if measurement is not None:
        metadata['model_params']['conversation_measurement'] = measurement
        for path in traces.values():
            row = json.loads(path.read_text())
            row['latency']['ttft_is_proxy'] = measurement['ttft_is_proxy']
            if unequal_nonstreaming_times:
                row['latency']['ttft_ms'] = row['latency']['total_ms'] - 1
            path.write_text(json.dumps(row) + '\n')
    case_path = scenarios / 'case.json'
    case = json.loads(case_path.read_text())
    case['calls']['call_1']['success_if'] = {'must_say_any': ['Dạ']}
    case_path.write_text(json.dumps(case))
    result = publish_pair(scenarios, traces['full'], traces['baseline_no_memory'],
                          tmp_path / 'btc_score.json', metadata, btc_root=BTC)
    run = {'run_id': 'offline-fixture', 'status': result['status'], 'score': 'btc_score.json',
        'subset': False,
        'execution_health': 'healthy', 'extraction_status': 'complete',
        'conversation_measurement': measurement or {'delivery_mode': 'text', 'ttft_is_proxy': True},
        'traces': {key: path.name for key, path in traces.items()},
        'manifests': {key: key + '.manifest.json' for key in traces}}
    (tmp_path / 'run.json').write_text(json.dumps(run))
    return run


def checks(report):
    return {item['name']: item for item in report['checks']}


@pytest.mark.parametrize('warmup,expected', [(None, 'missing'), (0, 'fail'),
                                            (2, 'fail'), (3, 'pass')])
def test_latency_requires_three_warmup_turns_in_bound_evidence(tmp_path, warmup, expected):
    from eval_harness.m1_acceptance import inspect_run
    saved_pair(tmp_path, warmup=warmup)
    assert checks(inspect_run(tmp_path, btc_root=BTC))['latency_warmup']['status'] == expected


def test_small_pair_cannot_pass_m1_despite_validated_status(tmp_path):
    from eval_harness.m1_acceptance import inspect_run
    saved_pair(tmp_path)
    report = inspect_run(tmp_path, btc_root=BTC)
    assert report['conversation_accepted'] is False
    gates = checks(report)
    assert gates['artifact_integrity']['status'] == 'pass'
    assert gates['multi_session_coverage']['status'] == 'fail'
    assert gates['latency_sample_size']['status'] == 'fail'
    assert gates['ttft_measured']['status'] == 'missing'
    assert gates['extraction_review']['status'] == 'missing'


def test_smoke_subset_cannot_be_presented_as_complete_dataset_run(tmp_path):
    from eval_harness.m1_acceptance import inspect_run
    run = saved_pair(tmp_path)
    run['subset'] = True
    (tmp_path / 'run.json').write_text(json.dumps(run))
    report = inspect_run(tmp_path, btc_root=BTC)
    assert checks(report)['complete_dataset_run']['status'] == 'fail'


@pytest.mark.parametrize('name', ['btc_score.json', 'full.jsonl', 'full.manifest.json',
                                 'full.report.json', 'scenarios/case.json'])
def test_tampered_evidence_is_rejected_without_rescoring(tmp_path, name):
    from eval_harness.m1_acceptance import inspect_run
    saved_pair(tmp_path)
    path = tmp_path / name
    if name.endswith('manifest.json'):
        value = json.loads(path.read_text())
        value['model_id'] = 'different'
        path.write_text(json.dumps(value))
    else:
        path.write_text(path.read_text() + '\n')
    report = inspect_run(tmp_path, btc_root=BTC)
    assert report['conversation_accepted'] is False
    assert checks(report)['artifact_integrity']['status'] == 'fail'


def test_acceptance_is_read_only_and_does_not_echo_private_artifact_errors(tmp_path):
    from eval_harness.m1_acceptance import inspect_run
    (tmp_path / 'run.json').write_text('private 0901234567 invalid json')
    before = (tmp_path / 'run.json').read_bytes()
    report = inspect_run(tmp_path, btc_root=BTC)
    assert '0901234567' not in json.dumps(report)
    assert (tmp_path / 'run.json').read_bytes() == before
    assert report['conversation_accepted'] is False


def test_dataset_handoff_counts_actual_calls_not_index_claims(tmp_path):
    from eval_harness.m1_acceptance import inspect_dataset
    scenarios, _, _ = _case(tmp_path)
    report = inspect_dataset(scenarios, btc_root=BTC)
    assert report['coverage']['multi_session_scenarios'] == 0
    assert report['coverage']['scenarios'] == 1
    assert report['dataset_ready'] is False


def test_one_labelled_scenario_does_not_hide_other_missing_memory_expectations(tmp_path):
    from eval_harness.m1_acceptance import inspect_dataset
    scenarios, _, _ = _case(tmp_path)
    first = {'scenario_id': 'FIRST', 'calls': {
        'call_1': {'customer_turns': ['Phòng 25m2.']},
        'call_2': {'customer_turns': ['Chào'], 'must_carry_over': ['room_area_m2'],
                   'must_not_ask': ['room_area_m2'], 'success_if': {'must_say_any': ['Dạ']}}}}
    second = json.loads(json.dumps(first))
    second['scenario_id'] = 'SECOND'
    second['calls']['call_2'].pop('must_carry_over')
    (scenarios / 'case.json').write_text(json.dumps(first))
    (scenarios / 'second.json').write_text(json.dumps(second))
    report = inspect_dataset(scenarios, btc_root=BTC)
    assert checks(report)['memory_labels_available']['status'] == 'fail'


def test_text_mode_and_guardrail_metadata_cannot_be_assumed(tmp_path):
    from eval_harness.m1_acceptance import inspect_run
    run = saved_pair(tmp_path)
    run.pop('conversation_measurement')
    (tmp_path / 'run.json').write_text(json.dumps(run))
    report = inspect_run(tmp_path, btc_root=BTC)
    assert checks(report)['m1_text_lifecycle']['status'] == 'missing'


@pytest.mark.parametrize('unequal', [False, True])
def test_nonstreaming_measurement_uses_btc_rule_7_and_requires_equal_times(tmp_path, unequal):
    from eval_harness.m1_acceptance import inspect_run
    saved_pair(tmp_path, deepcopy(LEGACY_TEXT_MEASUREMENT), unequal_nonstreaming_times=unequal)
    report = inspect_run(tmp_path, btc_root=BTC)
    gates = checks(report)
    assert gates['m1_text_lifecycle']['status'] == 'pass'
    assert gates['ttft_measured']['status'] == ('missing' if unequal else 'pass')
    assert report['conversation_accepted'] is False
