import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx2 as httpx
import openai
import pytest
from app.agent.harness.observability import capture_diagnostic_events


def test_schema_failure_retains_safe_code_through_turn_diagnostics():
    from pydantic import BaseModel, ValidationError
    from app.agent.harness.execution_diagnostics import safe_execution_error
    from app.agent.harness.observability import safe_diagnostic_event
    from eval_harness.turn_diagnostics import _classify
    class Args(BaseModel):
        qty: int
    try:
        Args(qty='private-0912345678')
    except ValidationError as exc:
        event = safe_diagnostic_event('execution', 'phase_result',
            safe_execution_error(exc, phase='model_invocation', invocation='initial'))
    assert event['error_type'] == 'ValidationError'
    assert event['error_code'] == 'schema_validation_failed'
    summary = _classify([event], [])
    assert summary['model']['error_code'] == 'schema_validation_failed'
    assert '0912345678' not in json.dumps([event, summary])


def test_local_tool_failure_code_is_not_lost_in_normalization():
    from app.infarstructure.local_llm import LocalToolOutputError
    from app.agent.harness.execution_diagnostics import safe_execution_error
    error = LocalToolOutputError('local_tool_output_invalid', 'private-0912345678')
    result = safe_execution_error(error, phase='model_invocation')
    assert result['error_type'] == 'LocalToolOutputError'
    assert result['error_code'] == 'local_tool_output_invalid'
    assert '0912345678' not in json.dumps(result)


@pytest.mark.parametrize('kind', ['parser', 'context'])
def test_parser_and_context_errors_keep_safe_codes_through_summary(kind):
    from langchain_core.exceptions import OutputParserException
    from app.agent.harness.execution_diagnostics import safe_execution_error
    from app.agent.harness.observability import safe_diagnostic_event
    from eval_harness.turn_diagnostics import _classify
    error = (OutputParserException('private-0912345678') if kind == 'parser' else
             openai.BadRequestError('private-0912345678', response=httpx.Response(400,
                 request=httpx.Request('POST', 'https://offline.invalid')), body={
                     'error': {'code': 'context_length_exceeded', 'message': 'private-0912345678'}}))
    event = safe_diagnostic_event('execution', 'phase_result',
        safe_execution_error(error, phase='model_invocation', invocation='initial'))
    summary = _classify([event], [])
    assert summary['model']['error_code'] == (
        'output_parse_failed' if kind == 'parser' else 'context_length_exceeded')
    assert '0912345678' not in json.dumps([event, summary])


def test_safe_api_error_preserves_contract_without_body():
    from app.agent.harness.execution_diagnostics import safe_execution_error
    error = openai.BadRequestError('secret 0912345678', response=httpx.Response(400,
        request=httpx.Request('POST', 'https://offline.invalid')), body={
            'code': 'invalid_value', 'param': 'tools[0].function.name', 'message': 'secret'})
    result = safe_execution_error(error, phase='model_invocation', invocation='initial')
    assert result['error_type'] == 'BadRequestError' and result['http_status'] == 400
    assert result['error_param'] == 'tools[0].function.name'
    assert 'secret' not in json.dumps(result) and '0912345678' not in json.dumps(result)
    error.body = {'code': 'secret', 'param': 'customer_phone=0912345678'}
    result = safe_execution_error(error, phase='model_invocation')
    assert result['error_code'] == result['error_param'] == 'unknown'


@pytest.mark.parametrize('failure', ['model', 'postprocess'])
def test_real_node_distinguishes_model_and_postprocess(failure):
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.harness.execution_diagnostics import execution_health
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={'messages': []}))
    if failure == 'model':
        agent.ainvoke.side_effect = TimeoutError('private')
    else:
        agent.ainvoke.return_value = None  # post-invoke result.get fails
    node = AgentNodes(None, None, None, 3, 3)
    with patch('app.agent.harness.agent_nodes.build_agent', return_value=agent), \
         patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'), \
         patch('app.agent.harness.agent_nodes.prompt_context', return_value={}), \
         patch('app.agent.harness.agent_nodes.prompt_messages', return_value=[]):
        with capture_diagnostic_events() as events:
            from datetime import date
            asyncio.run(node.run_agent({'safe_text': 'xin chào', 'tool_calls': [],
                'request': SimpleNamespace(on=date(2026, 10, 15))}))
    failed = [e for e in events if e.get('status') == 'failed']
    assert failed[0]['phase'] == ('model_invocation' if failure == 'model' else 'postprocess')
    assert execution_health([{'runtime_events': events}]) == 'degraded'
    assert 'private' not in json.dumps(events)


def test_health_missing_evidence_is_unknown():
    from app.agent.harness.execution_diagnostics import execution_health
    assert execution_health([{'runtime_events': []}]) == 'unknown'
    assert execution_health([{'runtime_events': [{'event': 'model_failed'}]}]) == 'degraded'


@pytest.mark.parametrize('kind,status', [
    ('AuthenticationError',401),('PermissionDeniedError',403),('NotFoundError',404),
    ('RateLimitError',429),('InternalServerError',500)])
def test_sdk_failure_types_remain_distinct(kind, status):
    from app.agent.harness.execution_diagnostics import safe_execution_error
    error = getattr(openai,kind)('private', response=httpx.Response(status,
        request=httpx.Request('POST','https://offline.invalid')), body=None)
    detail = safe_execution_error(error, phase='model_invocation')
    assert detail['error_type'] == kind and detail['http_status'] == status


def test_unknown_error_and_untrusted_field_types_are_safe():
    from app.agent.harness.execution_diagnostics import safe_execution_error, normalize_execution_event
    error = type('PrivateName0912345678',(Exception,),{})('secret')
    detail = safe_execution_error(error, phase='postprocess')
    assert detail['error_type'] == 'unknown_error'
    assert 'Private' not in json.dumps(detail)
    assert normalize_execution_event({'phase':[], 'status':{}, 'invocation':[]})['status']=='unknown'


def test_memory_failure_cannot_be_classified_as_healthy_direct_route():
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.harness.execution_diagnostics import execution_health
    with capture_diagnostic_events() as events:
        asyncio.run(AgentNodes(None,None,None,3,3).run_agent({'safe_text':'chào','tool_failed':True}))
    assert execution_health([{'runtime_events':events}]) == 'degraded'
