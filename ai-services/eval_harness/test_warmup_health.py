import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.agent.harness.observability import log_event
from eval_harness.benchmark_runner import warm_up_configuration
from eval_harness.test_support import VoiceLifecycleStub


@pytest.mark.parametrize('mode', ['failed', 'repair_failed', 'missing', 'healthy'])
def test_warmup_checks_evidence_not_response_text(mode):
    async def run(request):
        if mode != 'missing':
            log_event({}, 'execution', 'phase_result', phase='model_invocation', invocation='initial',
                status='failed' if mode == 'failed' else 'succeeded', error_type='BadRequestError')
            log_event({}, 'execution', 'phase_result', phase='postprocess', status='succeeded')
        if mode == 'repair_failed':
            log_event({}, 'execution', 'phase_result', phase='model_invocation', invocation='repair',
                      status='failed', error_type='BadRequestError')
        return SimpleNamespace(agent_text='Dạ, hiện em chưa kiểm tra được thông tin này.', call_brief=None)
    runtime = VoiceLifecycleStub()
    runtime.run = AsyncMock(side_effect=run)
    if mode == 'healthy':
        assert asyncio.run(warm_up_configuration(runtime))['turns'] == 3
    else:
        with pytest.raises(RuntimeError) as raised:
            asyncio.run(warm_up_configuration(runtime))
        assert raised.value.error_code == 'warmup_execution_unhealthy'
        assert runtime.run.await_count == 1
        if mode in {'failed', 'repair_failed'}:
            assert raised.value.execution_error['error_type'] == 'BadRequestError'
            assert raised.value.execution_error['invocation'] == ('repair' if mode == 'repair_failed' else 'initial')


def test_warmup_failure_stops_before_reset_and_scored_turns(tmp_path):
    import json
    from unittest.mock import patch
    from app.configs import Settings
    from eval_harness.benchmark_runner import execute_configuration
    settings = Settings(_env_file=None,llm_api_key='offline-key',llm_model='offline-model')
    runtime = VoiceLifecycleStub()
    runtime.memory = SimpleNamespace(include_prior=True)
    runtime.tools = object()
    runtime.run = AsyncMock(return_value=SimpleNamespace(agent_text='Dạ, em nghe ạ.', call_brief=None))
    with patch('eval_harness.benchmark_runner.preflight_runtime', new_callable=AsyncMock), \
         patch('eval_harness.benchmark_runner.build_runtime', return_value=runtime), \
         patch('eval_harness.benchmark_runner.prepare_runtime_for_eval', new_callable=AsyncMock) as reset, \
         patch('eval_harness.benchmark_runner.run_configuration', new_callable=AsyncMock) as scored:
        with pytest.raises(RuntimeError):
            asyncio.run(execute_configuration(settings=settings, scenarios={},config='full',run_id='offline',
                out=tmp_path/'trace.jsonl',btc_root=tmp_path,expected_database='telesale',
                release={'release_id':'btc-only'},runtime=runtime))
    reset.assert_not_called()
    scored.assert_not_called()
    report=json.loads((tmp_path/'trace.report.json').read_text())
    assert report['status']=='failed' and report['phase']=='warmup'
    assert report['execution_error']['status']=='unknown'
    assert not (tmp_path/'btc_score.json').exists()


def test_unexpected_success_exit_writes_a_failed_configuration_report(tmp_path, monkeypatch):
    import json
    from app.configs import Settings
    from eval_harness import benchmark_runner as runner

    runtime = SimpleNamespace(memory=SimpleNamespace(), tools=object())
    monkeypatch.setattr(runner, 'preflight_runtime', AsyncMock())
    monkeypatch.setattr(runner, 'build_runtime', lambda *args, **kwargs: runtime)
    monkeypatch.setattr(runner, 'warm_up_configuration', AsyncMock(side_effect=SystemExit(0)))
    with pytest.raises(RuntimeError, match='configuration_failed'):
        asyncio.run(runner.execute_configuration(
            settings=Settings(_env_file=None, llm_api_key='offline', llm_model='offline'),
            scenarios={}, config='full', run_id='offline', out=tmp_path/'trace.jsonl',
            btc_root=tmp_path, expected_database='offline', release={'release_id': 'k0'},
            runtime=runtime))
    report = json.loads((tmp_path/'trace.report.json').read_text())
    assert report['status'] == 'failed'
    assert report['phase'] == 'warmup'
    assert report['error_code'] == 'unexpected_process_exit'


def test_warmup_preserves_verifier_rejections_and_redacted_drafts():
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.harness.execution_diagnostics import safe_failure_details
    from app.agent.memory.store import MCPMemoryStore
    from eval_harness.benchmark_runner import WarmupGateway
    from test_deep_memory import FakeToolModel

    async def run():
        inner = SimpleNamespace(invoke=AsyncMock(side_effect=AssertionError('external tool called')))
        gateway = WarmupGateway(inner)
        draft = 'Mọi đơn hàng đều được miễn phí vận chuyển.'
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content=draft)] * 2),
            gateway, MCPMemoryStore(gateway))
        try:
            with pytest.raises(RuntimeError) as failure:
                await warm_up_configuration(runtime, turns=1)
            detail = safe_failure_details(failure.value)
            assert detail['verification_rejections'] == ['promotion_quote_missing'] * 2
            assert [item['agent_draft'] for item in detail['verification_diagnostics']] == [draft] * 2
            assert 'execution_error' not in detail
            assert not inner.invoke.called
        finally:
            await runtime.close()

    asyncio.run(run())
