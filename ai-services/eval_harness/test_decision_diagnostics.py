import json
from types import SimpleNamespace
from uuid import UUID
import pytest


def api():
    from app.mcp_servers.mcp_shared import decision_diagnostics as d
    return d


def test_capture_allowlist_aliases_limits_and_unknowns():
    d = api()
    source = '3e089123-4567-4567-8123-123456789012'
    state = {'customer_id': '0912345678', 'request': SimpleNamespace(
        session_id=UUID(source), client_msg_id=UUID(source)),
        'history': [{'source_turn_id': source, 'customer': 'PRIVATE'}]}
    with d.capture_decisions(max_events=2) as capture:
        d.emit('context_loaded', state=state, snapshot={
            'schema_version': 2, 'selected_sku': 'SKU-TEST', 'accepted_offer': None,
            'presented_offer': {'sku': 'SKU-TEST', 'price_vnd': 900000,
                                'coverage': 'partial', 'evidence_quote': 'PRIVATE'},
            'source_refs': {'selected_sku': {'customer_id': '0912345678',
                'session_id': source, 'source_turn_id': source, 'source_kind': 'customer',
                'evidence_quote': 'PRIVATE'}}}, raw_prompt='PRIVATE', phone='0912345678')
        d.emit('gate_result', state=state, reason='PRIVATE', status='blocked')
        d.emit('gate_result', state=state, reason='identity_required', status='blocked')
    raw = json.dumps(capture.events)
    assert 'PRIVATE' not in raw and '0912345678' not in raw
    first = capture.events[0]
    assert first['snapshot']['accepted_offer'] is None
    assert first['snapshot']['presented_offer']['price_vnd'] == 900000
    assert first['snapshot']['source_refs']['selected_sku']['source_turn_id'] == source
    assert first['snapshot']['source_refs']['selected_sku']['owner_matches'] is True
    assert first['snapshot']['source_refs']['selected_sku']['source_in_history'] is True
    assert capture.events[1]['reason'] == 'unknown_reason'
    assert capture.truncated is True
    assert 'selected_sku' not in d.safe_snapshot({})
    assert d.safe_snapshot({'selected_sku': None})['selected_sku'] is None


def test_capture_is_opt_in_and_does_not_raise_on_bad_payload():
    d = api()
    assert not d.active()
    d.emit('gate_result', snapshot=object())
    with d.capture_decisions() as capture:
        d.emit('gate_result', snapshot=object())
        d.emit('gate_result', reason='identity_required', status='blocked')
    assert capture.errors > 0
    assert capture.events[-1]['reason'] == 'identity_required'


def test_loaded_fingerprint_uses_function_code_not_disk(tmp_path):
    d = api()
    import importlib.util
    path = tmp_path / 'loaded.py'
    path.write_text('def f(): return 1\n')
    spec = importlib.util.spec_from_file_location('loaded_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = d.loaded_fingerprint([module])
    path.write_text('def f(): return 2\n')
    assert d.loaded_fingerprint([module]) == original
    exec('def f(): return 3', module.__dict__)
    assert d.loaded_fingerprint([module]) != original


def test_memory_service_envelope_is_opt_in_and_store_strips_transport(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from app.agent.memory.store import MCPMemoryStore
    from app.mcp_servers.mcp_memory.services import memory
    d = api()
    class Repo:
        @asynccontextmanager
        async def transaction(self): yield self
        async def owner(self, conn, sid): return None
        async def turns(self, conn, sid): return []
    class Gateway:
        async def invoke(self, name, args):
            return await memory.read(Repo(), None, args['session_id'])
    async def run():
        with d.capture_decisions() as capture:
            result = await MCPMemoryStore(Gateway()).read_context('session', None)
        return result, capture
    plain, disabled = asyncio.run(run())
    assert '_decision_diagnostics' not in plain
    monkeypatch.setenv('EVAL_DECISION_DIAGNOSTICS', '1')
    observed, capture = asyncio.run(run())
    assert observed == plain
    assert any(e['event'] == 'memory_read' and e['component'] == 'memory' for e in capture.events)
    assert not disabled.events




def test_tool_attempt_blocked_before_mcp_is_visible():
    import asyncio
    from datetime import datetime, timezone
    from app.agent.implementations.business_agent import BusinessTools
    d = api()
    class Gateway:
        async def invoke(self, *args): raise AssertionError('must not reach MCP')
    state = {'identity_status': 'unknown', 'tool_calls': []}
    with d.capture_decisions() as capture:
        result = asyncio.run(BusinessTools(Gateway(), state, 5,
            lambda: datetime.now(timezone.utc)).invoke('order.create', {'sku': 'SKU-TEST'}))
    assert result == {'error': 'identity_required'} and state['tool_calls'] == []
    attempt = next(e for e in capture.events if e['event'] == 'tool_attempt')
    outcome = next(e for e in capture.events if e['event'] == 'tool_result')
    assert attempt['origin'] == 'model'
    assert outcome['attempt_id'] == attempt['attempt_id']
    assert outcome['status'] == 'blocked' and outcome['reason'] == 'identity_required'


@pytest.mark.parametrize('retrieval,status,count', [
    ('ok', 'success', 2), ('no_evidence', 'success', 0),
    ('unavailable', 'failed', 0), ('timeout', 'failed', 0), ('overloaded', 'failed', 0),
])
def test_policy_result_reports_retrieval_instead_of_transaction_receipt(retrieval, status, count):
    import asyncio
    d = api()
    result = {'retrieval_status': retrieval, 'evidence': [{'content': 'PRIVATE'}] * count}

    class Tools:
        def __init__(self): self.state = {'tool_calls': []}
        @d.tool_boundary
        async def invoke(self, name, args):
            self.state['tool_calls'].append({'name': name, 'args': args, 'result': result})
            return result

    with d.capture_decisions() as capture:
        actual = asyncio.run(Tools().invoke('policy.search', {'query': 'PRIVATE'}))
    assert actual == result
    attempt = next(e for e in capture.events if e['event'] == 'tool_attempt')
    outcome = next(e for e in capture.events if e['event'] == 'tool_result')
    assert attempt['query_present'] is True and attempt['args'] == {}
    assert outcome['retrieval_status'] == retrieval and outcome['evidence_count'] == count
    assert outcome['status'] == status
    assert 'receipt_present' not in outcome
    assert 'PRIVATE' not in json.dumps(capture.events)
    assert all(d.valid_event(e) for e in capture.events)
    with d.capture_decisions() as received:
        d.ingest({'events': capture.events})
    assert received.events == capture.events


@pytest.mark.parametrize('tool,key', [('order.create', 'order_id'), ('handoff.transfer', 'ticket_id')])
def test_transaction_receipt_remains_available(tool, key):
    import asyncio
    d = api()
    class Tools:
        def __init__(self): self.state = {'tool_calls': []}
        @d.tool_boundary
        async def invoke(self, name, args):
            result = {key: 'RECEIPT'}
            self.state['tool_calls'].append({'name': name, 'args': args, 'result': result})
            return result
    with d.capture_decisions() as capture:
        asyncio.run(Tools().invoke(tool, {}))
    outcome = next(e for e in capture.events if e['event'] == 'tool_result')
    assert outcome['receipt_present'] is True


def test_decision_file_binds_trace_and_reports_missing_components(tmp_path):
    from eval_harness.turn_diagnostics import TurnDiagnostics, verify_decisions
    d = api()
    row = dict(run_id='r', config='full', scenario_id='generic', call='call_1', turn=1,
               agent_text='Chào anh', tool_calls=[], memory_writes=[])
    trace = tmp_path / 'trace.jsonl'
    trace.write_text(json.dumps(row) + '\n')
    collector = TurnDiagnostics()
    with d.capture_decisions() as capture:
        d.emit('gate_result', status='blocked', reason='identity_required')
    collector.observe_decisions(row, capture)
    ref = collector.write_decisions(trace)
    records = [json.loads(v) for v in (tmp_path / ref['path']).read_text().splitlines()]
    assert records[0]['kind'] == 'metadata'
    assert records[-1]['kind'] == 'summary'
    assert records[-1]['turns'][0]['missing_components'] == ['memory', 'worker']
    assert verify_decisions(trace, ref) == ref
    with pytest.raises(ValueError): collector.write_decisions(trace)
    trace.write_text(trace.read_text() + '\n')
    with pytest.raises(ValueError): verify_decisions(trace, ref)


def test_safe_offer_preserves_promised_terms_and_component_sources():
    d = api()
    source = '3e089123-4567-4567-8123-123456789012'
    offer = {'sku': 'SKU-TEST', 'promo_terms': [
        {'type': 'gift', 'gift_sku': 'SKU-GIFT', 'qty': 1},
        {'type': 'delivery', 'freeship': True}, {'type': 'freecod'}],
        'sources': {'term:0': {'agent': {'session_id': source, 'source_turn_id': source,
            'source_kind': 'agent'}, 'observation': {'session_id': source,
                'source_turn_id': source, 'tool_name': 'pricing.get_quote', 'observation_index': 0}}}}
    safe = d.safe_snapshot({'presented_offer': offer})['presented_offer']
    assert safe['promo_terms'] == offer['promo_terms']
    assert safe['sources']['term:0']['agent']['source_turn_id'] == source


def test_bad_remote_envelope_cannot_break_business_capture():
    d = api()
    with d.capture_decisions() as capture:
        d.ingest({'events': 'PRIVATE'})
        d.ingest({'events': [{'event': 'memory_read', 'raw_prompt': 'PRIVATE'}]})
        d.emit('gate_result', status='blocked', reason='identity_required')
    assert capture.errors >= 2
    assert 'PRIVATE' not in json.dumps(capture.events)


def test_coordinator_merges_configs_without_overwriting(tmp_path):
    from eval_harness.turn_diagnostics import TurnDiagnostics, merge_decisions, _verify_decision_file
    d = api()
    traces = {}
    for config in ('full', 'baseline_no_memory'):
        row = dict(run_id='r', config=config, scenario_id='generic', call='call_1', turn=1,
                   agent_text='Chào anh')
        trace = tmp_path / (config + '.jsonl')
        trace.write_text(json.dumps(row) + '\n')
        collector = TurnDiagnostics()
        with d.capture_decisions() as capture:
            d.emit('gate_result', status='blocked', reason='identity_required')
        collector.observe_decisions(row, capture)
        collector.write_decisions(trace)
        traces[config] = trace
    out = tmp_path / 'decision_diagnostics.jsonl'
    ref = merge_decisions(traces, out)
    assert set(ref['traces']) == set(traces) and ref['complete'] is False
    assert _verify_decision_file(out, traces, ref) == ref
    with pytest.raises(ValueError): merge_decisions(traces, out)
    data = out.read_text().replace('identity_required', 'PRIVATE')
    out.write_text(data)
    with pytest.raises(ValueError): _verify_decision_file(out, traces)


def test_run_configuration_exports_readback_without_altering_official_rows(monkeypatch, tmp_path):
    import asyncio
    from unittest.mock import AsyncMock
    from langchain_core.messages import AIMessage
    from eval_harness.test_evidence_continuation_end_to_end import production_case, scripted_tool
    from eval_harness.benchmark_runner import run_configuration, DistillationWrites
    from eval_harness.turn_diagnostics import verify_decisions
    monkeypatch.setenv('EVAL_DECISION_DIAGNOSTICS', '1')
    runtime, gateway, model = production_case()
    model.replies.extend([scripted_tool('catalog.search', {'query': 'Willow Classic'}),
                          scripted_tool('pricing.get_quote', {'sku': 'SKU-WILLOW'}),
                          AIMessage(content='Willow Classic giá 730.000đ.')])
    async def wait(*args): await gateway.project()
    async def capture(ids):
        jobs = {j['source_turn_id']: {'revision': j['job_id'], 'status': j['status'],
            'envelope': j['accepted_proposals'].get('_decision_diagnostics')} for j in gateway.repo.jobs
            if j['source_turn_id'] in ids}
        return DistillationWrites({}, jobs)
    scenarios = {'CAPTURE': {'calls': {'call_1': {'call_date': '2026-11-05',
        'customer_turns': ['Cho tôi xem giá Willow Classic.']}}}}
    out = tmp_path / 'runner.jsonl'
    result = asyncio.run(run_configuration(scenarios=scenarios, config='full', runtime=runtime,
        run_id='offline', out=out, wait_for_jobs=wait, capture_writes=capture))
    ref = result['decision_diagnostics']
    verify_decisions(out, ref)
    assert 'decision_diagnostics' not in out.read_text()
    records = [json.loads(line) for line in (tmp_path / ref['path']).read_text().splitlines()]
    assert records[-1]['turns'][0]['missing_components'] == []
    assert any(e.get('event') == 'job_readback' and e['status'] == 'success' for e in records)
    assert not records[-1]['turns'][0]['errors']


def test_diagnostics_production_flag_is_ignored(monkeypatch):
    from unittest.mock import patch
    d = api()
    monkeypatch.setenv('EVAL_DECISION_DIAGNOSTICS', '1')
    with patch('app.configs.get_settings', return_value=SimpleNamespace(app_env='production')):
        assert d.enabled() is False


def test_logging_errors_cannot_abort_worker_transaction():
    import asyncio
    from contextlib import asynccontextmanager
    d = api()
    order = []
    class Conn:
        @asynccontextmanager
        async def transaction(self):
            order.append('savepoint')
            try: yield
            except RuntimeError:
                order.append('rollback_savepoint')
                raise
    class Repo:
        async def save_distillation_proposals(self, *args): raise RuntimeError('PRIVATE')
    with d.capture_decisions() as capture:
        asyncio.run(d.save_worker_envelope(Repo(), Conn(), 1, {}))
    assert order == ['savepoint', 'rollback_savepoint']
    assert capture.errors == 1


def test_aliases_are_consistent_across_turns_and_remove_transport_session_ids():
    d = api()
    from eval_harness.turn_diagnostics import TurnDiagnostics
    collector = TurnDiagnostics()
    source = '3e089123-4567-4567-8123-123456789012'
    other = '3e089123-4567-4567-8123-123456789013'
    for index, session in enumerate((source, other, source), 1):
        with d.capture_decisions(aliases=collector.decision_aliases) as capture:
            d.emit('context_loaded', state={'customer_id': 'PRIVATE',
                'request': SimpleNamespace(session_id=UUID(session))})
        collector.observe_decisions(dict(run_id='r', config='full', scenario_id='test',
            call='call_1', turn=index, agent_text='hello'), capture)
    events = collector.decisions
    assert events[0]['session_alias'] == events[2]['session_alias'] != events[1]['session_alias']
    assert len({e['customer_alias'] for e in events}) == 1
    assert all('session_ref' not in e for e in events)


def test_verifier_rejects_private_or_fabricated_summary(tmp_path):
    from eval_harness.turn_diagnostics import TurnDiagnostics, _verify_decision_file
    d = api()
    row = dict(run_id='r', config='full', scenario_id='generic', call='call_1', turn=1,
               agent_text='hello')
    trace = tmp_path / 'trace.jsonl'; trace.write_text(json.dumps(row) + '\n')
    collector = TurnDiagnostics()
    with d.capture_decisions() as capture:
        d.emit('gate_result', status='blocked', reason='identity_required')
    collector.observe_decisions(row, capture)
    ref = collector.write_decisions(trace)
    path = tmp_path / ref['path']
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[-1]['turns'][0]['raw_prompt'] = 'PRIVATE'
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    with pytest.raises(ValueError): _verify_decision_file(path, {'full': trace})


def test_constraints_keep_typed_gate_inputs_without_delivery_text():
    d = api()
    safe = d.safe_snapshot({'delegation': {'status': 'active', 'constraints': {
        'limit_vnd': 900000, 'child_lock_required': True, 'room_area_m2': 23.5,
        'delivery_condition': 'Giao tới PRIVATE 0912345678 trước thứ sáu',
        'required_promo_code': 'RUN10'}}})
    constraints = safe['delegation']['constraints']
    assert constraints['child_lock_required'] is True
    assert constraints['room_area_m2'] == 23.5
    assert constraints['delivery_condition_present'] is True
    assert constraints['required_promo_code'] == 'RUN10'
    assert 'PRIVATE' not in json.dumps(safe)
