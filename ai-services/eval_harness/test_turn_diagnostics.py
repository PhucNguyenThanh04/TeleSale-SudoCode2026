"""Safe observed fallback evidence, independent from speech/score heuristics."""
import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.agent.harness.observability import log_event, capture_diagnostic_events
from eval_harness.turn_diagnostics import TurnDiagnostics, verify_turn_diagnostics


def trace_row():
    return dict(run_id='r',config='full',scenario_id='generic',call='call_1',turn=1,
                agent_text='Dạ chào anh',questions=[],claims=[],tool_calls=[],memory_writes=[])


def test_capture_is_context_local_even_with_logging_disabled():
    async def task(code):
        with capture_diagnostic_events() as events:
            log_event({},'run_agent','model_failed',error_type=code)
            await asyncio.sleep(0)
            return events
    async def both(): return await asyncio.gather(task('TimeoutError'),task('ValueError'))
    with patch('app.agent.harness.observability.logger.isEnabledFor',return_value=False):
        first,second=asyncio.run(both())
    assert first == [{'step':'run_agent','event':'model_failed','error_type':'TimeoutError'}]
    assert second[0]['error_type']=='ValueError'
    log_event({},'run_agent','model_failed',error_type='RuntimeError')
    assert len(first)==1


def test_collector_keeps_codes_not_draft_or_result_values(tmp_path):
    row=trace_row()
    state={'request':SimpleNamespace(session_id='now'),'identity_status':'known',
           'agent_draft':'Private name 0912345678',
           'verifier_events':[{'reason':'price_without_quote','agent_draft':'Private name',
               'claims':[{'value':9876543}], 'source_evidence':{'phone':'0912345678'}}],
           'tool_calls':[{'name':'policy.search','result':{'retrieval_status':'timeout','error':'private secret'}}]}
    with capture_diagnostic_events() as events:
        log_event(state,'run_agent','model_failed',error_type='Private_0912345678')
        log_event(state,'verify','grounding_checked',accepted=False,reason='private secret')
        log_event(state,'verify','recovery_exhausted')
    collector=TurnDiagnostics()
    collector.observe(SimpleNamespace(session_id='now'),SimpleNamespace(call_brief=None),state,row,events)
    trace=tmp_path/'trace.jsonl';trace.write_text(json.dumps(row)+'\n')
    refs=collector.write(trace)
    assert verify_turn_diagnostics(trace,refs)==refs
    data=json.loads(trace.with_suffix('.events.json').read_text())[0]
    assert data['model']['error_type']=='other_error'
    assert data['grounding']['reason']=='unknown_reason'
    assert data['recovery']['status']=='failed'
    assert data['tool_failures'][0]['retrieval_status']=='timeout'
    raw=trace.with_suffix('.events.json').read_text()+trace.with_suffix('.stages.json').read_text()
    for secret in ('Private','0912345678','9876543','private secret','agent_draft','source_evidence'):
        assert secret not in raw


def test_no_events_is_unknown_even_for_fallback_message(tmp_path):
    from app.agent.guardrails.checks import FALLBACK
    row=trace_row();row['agent_text']=FALLBACK
    collector=TurnDiagnostics()
    collector.observe(SimpleNamespace(session_id='now'),None,{},row,[])
    trace=tmp_path/'trace.jsonl';trace.write_text(json.dumps(row)+'\n')
    collector.write(trace)
    event=json.loads(trace.with_suffix('.events.json').read_text())[0]
    assert event['fallback_observed'] is True
    assert event['model']['status']==event['grounding']['status']==event['recovery']['status']=='unknown'


@pytest.mark.parametrize('damage',['missing','duplicate','hash','identity','unknown_key'])
def test_diagnostic_integrity_rejects_damage(tmp_path,damage):
    row=trace_row();trace=tmp_path/'trace.jsonl';trace.write_text(json.dumps(row)+'\n')
    c=TurnDiagnostics();c.observe(SimpleNamespace(session_id='now'),None,{},row,[])
    refs=c.write(trace)
    path=trace.with_suffix('.events.json');events=json.loads(path.read_text())
    if damage=='missing': path.unlink()
    else:
        if damage=='duplicate': events*=2
        if damage=='hash': events[0]['agent_text_sha256']='wrong'
        if damage=='identity': events[0]['turn']=2
        if damage=='unknown_key': events[0]['agent_draft']='secret'
        path.write_text(json.dumps(events))
    with pytest.raises(ValueError): verify_turn_diagnostics(trace,refs)


def test_verifier_recovery_observations_do_not_change_result():
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.guardrails.checks import FALLBACK
    nodes=AgentNodes(None,None,None,3,3)
    state={'safe_text':'chào','agent_draft':'Giá 70.000đ.','tool_calls':[]}
    plain=asyncio.run(nodes.verify_agent(state.copy()))
    with capture_diagnostic_events() as events:
        observed=asyncio.run(nodes.verify_agent(state.copy()))
    assert observed==plain
    assert any(e['event']=='recovery_exhausted' for e in events)
    assert observed['agent_text']==FALLBACK


def test_actual_model_exception_is_observed_without_exception_message():
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.guardrails.checks import FALLBACK
    from unittest.mock import AsyncMock
    agent=SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError('private 0912345678')))
    node=AgentNodes(None,None,None,3,3)
    with patch('app.agent.harness.agent_nodes.build_agent',return_value=agent), \
         patch('app.agent.harness.agent_nodes.text_prompt',return_value='offline'), \
         patch('app.agent.harness.agent_nodes.prompt_context',return_value={}), \
         patch('app.agent.harness.agent_nodes.prompt_messages',return_value=[]):
        with capture_diagnostic_events() as events:
            result=asyncio.run(node.run_agent({'safe_text':'xin chào','tool_calls':[]}))
    assert result['agent_draft']==FALLBACK
    assert {'step':'run_agent','event':'model_failed','error_type':'TimeoutError'} in events
    assert any(e.get('phase') == 'model_invocation' and e.get('error_type') == 'TimeoutError' for e in events)
    assert 'private' not in json.dumps(events)


def test_successful_and_rejected_recoveries_have_explicit_outcomes():
    from app.agent.harness.agent_nodes import AgentNodes
    from unittest.mock import Mock
    state={'safe_text':'chào','agent_draft':'Giá 70.000đ.','tool_calls':[]}
    for reply,expected in [('Dạ chào anh','recovery_succeeded'),('Giá 90.000đ.','recovery_rejected')]:
        with patch('app.agent.harness.agent_nodes.safe_transaction_reply',Mock(return_value=reply)):
            with capture_diagnostic_events() as events:
                asyncio.run(AgentNodes(None,None,None,3,3).verify_agent(state.copy()))
        assert any(e['event']==expected for e in events)


def test_untrusted_event_metadata_is_dropped_without_crashing_turn():
    with patch('app.agent.harness.observability.logger.isEnabledFor',return_value=False):
        with capture_diagnostic_events() as events:
            log_event({},'verify','grounding_checked',accepted=False,reason={'private':'0912345678'})
    assert events[0]['reason']=='unknown_reason'


def test_stage_nested_payload_is_rejected_even_without_expected_hash(tmp_path):
    row=trace_row();trace=tmp_path/'trace.jsonl';trace.write_text(json.dumps(row)+'\n')
    c=TurnDiagnostics();c.observe(SimpleNamespace(session_id='now'),None,{},row,[]);c.write(trace)
    path=trace.with_suffix('.stages.json');data=json.loads(path.read_text())
    data[0]['business_tools']=[{'name':'order.create','status':'failed','result':{'private':'0912345678'}}]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): verify_turn_diagnostics(trace)
