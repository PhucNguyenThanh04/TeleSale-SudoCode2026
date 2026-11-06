import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.agent.harness.observability import log_event
from eval_harness.benchmark_runner import warm_up_configuration


@pytest.mark.parametrize('mode', ['failed', 'missing', 'healthy'])
def test_warmup_checks_evidence_not_response_text(mode):
    async def run(request):
        if mode != 'missing':
            log_event({}, 'execution', 'phase_result', phase='model_invocation', invocation='initial',
                status='failed' if mode == 'failed' else 'succeeded', error_type='BadRequestError')
            log_event({}, 'execution', 'phase_result', phase='postprocess', status='succeeded')
        return SimpleNamespace(agent_text='Dạ, hiện em chưa kiểm tra được thông tin này.')
    runtime = SimpleNamespace(run=AsyncMock(side_effect=run))
    if mode == 'healthy':
        assert asyncio.run(warm_up_configuration(runtime))['turns'] == 3
    else:
        with pytest.raises(RuntimeError) as raised:
            asyncio.run(warm_up_configuration(runtime))
        assert raised.value.error_code == 'warmup_execution_unhealthy'
        assert runtime.run.await_count == 1
        if mode == 'failed':
            assert raised.value.execution_error['error_type'] == 'BadRequestError'


def test_warmup_failure_stops_before_reset_and_scored_turns(tmp_path):
    import json
    from unittest.mock import patch
    from app.configs import Settings
    from eval_harness.benchmark_runner import execute_configuration
    settings = Settings(_env_file=None,llm_api_key='offline-key',llm_model='offline-model')
    runtime = SimpleNamespace(memory=SimpleNamespace(include_prior=True), tools=object(), run=AsyncMock())
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
