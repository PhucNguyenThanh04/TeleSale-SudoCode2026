"""The run coordinator cannot publish mismatched source snapshots."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from eval_harness.run_official import require_same_seed, run_pair


def test_seed_fingerprint_must_match_across_configurations():
    assert require_same_seed("digest-a", "digest-a") == "digest-a"
    with pytest.raises(ValueError, match="btc_source"):
        require_same_seed("digest-a", "digest-b")


@pytest.mark.parametrize('failure', [None, 'publish', 'missing', 'tampered', 'turn_missing', 'turn_tampered'])
def test_conversation_run_does_not_execute_retired_rag(tmp_path, failure):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "case.json").write_text(json.dumps({
        "scenario_id": "CASE-A", "calls": {"call_1": {"customer_turns": ["Xin chào"]}}}), encoding="utf-8")
    identity = {"database": "telesale_eval_test"}

    def fake_run(config, scenarios, agent, seed, run_id, out, **kwargs):
        assert (kwargs['btc_root'] / 'btc_release.json').is_file()
        assert 'pricing.quote_order' in (kwargs['btc_root'] / 'schemas/tools.schema.json').read_text()
        trace = out / f"{config}.jsonl"
        from eval_harness.extractor import extract_detailed
        from eval_harness.extraction_report import write_extraction_sidecar
        row = dict(run_id=run_id, config='full' if config == 'full' else 'baseline_no_memory', scenario_id='CASE-A', call='call_1', turn=1,
                   agent_text='Dạ chào anh', tool_calls=[], questions=[], claims=[])
        trace.write_text(json.dumps(row) + '\n')
        write_extraction_sidecar(trace, out/('full.extraction.jsonl' if config == 'full' else 'baseline.extraction.jsonl'))
        from eval_harness.turn_diagnostics import TurnDiagnostics
        collector=TurnDiagnostics()
        collector.observe(SimpleNamespace(session_id='now'),None,{},row,[])
        refs=collector.write(trace)
        trace.with_suffix(".report.json").write_text(json.dumps({
            "database_identity": identity, "turn_diagnostics":refs}), encoding="utf-8")
        return trace

    def fake_publish(scenarios, full, baseline, score, metadata, **kwargs):
        from eval_harness.extraction_report import summarize_extraction, sha256
        measurement = metadata['model_params']['conversation_measurement']
        assert measurement['delivery_mode'] == 'voice'
        assert measurement['ttft_is_proxy'] is True
        if failure == 'publish':
            raise OSError('synthetic publication failure')
        result = {'status': 'validated', 'manifests': {'full': {}, 'baseline_no_memory': {}}}
        if failure == 'missing':
            return result
        report = summarize_extraction({'full': full, 'baseline_no_memory': baseline}, kwargs['extraction_sidecars'], {})
        path = score.parent/'extraction_report.json'
        path.write_text(json.dumps(report))
        result.update(extraction_status=report['extraction_status'],
                      extraction_report={'path': path.name, 'sha256': sha256(path)})
        if failure != 'turn_missing':
            result['turn_diagnostics']={config:json.loads(path.with_suffix('.report.json').read_text())['turn_diagnostics']
                for config,path in {'full':full,'baseline_no_memory':baseline}.items()}
        if failure == 'turn_tampered':
            full.with_suffix('.events.json').write_text('[]')
        if failure == 'tampered':
            kwargs['extraction_sidecars']['full'].write_text('')
        return result

    settings = SimpleNamespace(app_env="test", llm_model="fake", llm_base_url="https://offline.invalid",
                               llm_temperature=0, llm_max_tokens=1,
                               agent_prompt_history_turns=1,
                               agent_guardrails_enabled=True)
    with patch("eval_harness.run_official.Settings", return_value=settings), \
         patch("eval_harness.run_official.database_url", return_value="dsn"), \
         patch("eval_harness.run_official.capture_release", new_callable=AsyncMock, return_value={"release_id": "btc-only", "manifest_hash": "btc-only"}), \
         patch("eval_harness.run_official.fingerprint_btc_source",
               new_callable=AsyncMock, return_value="seed"), \
         patch("eval_harness.run_official.source_snapshot_digest", return_value="source"), \
         patch("eval_harness.run_official._run_one", side_effect=fake_run), \
         patch("eval_harness.run_official.publish_pair", side_effect=fake_publish), \
         patch("asyncpg.connect", side_effect=AssertionError("Retired RAG must not query source DB")):
        out = asyncio.run(run_pair(scenarios=scenarios, btc_root=__import__("pathlib").Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS",
                                   agent="deep", seed=7, out_root=tmp_path / "results", expected_database="telesale_eval_test"))

    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == ("failed" if failure else "validated")
    assert run['conversation_measurement']['response_scope'] == 'transcript_to_complete_reply'
    assert "rag_summary" not in run
    assert not (out / "rag_retrieval.json").exists()


def test_preflight_failure_persists_failed_status_without_model(tmp_path):
    with patch('eval_harness.run_official._run_one') as model:
        out=asyncio.run(run_pair(scenarios=tmp_path/'missing',btc_root=tmp_path,
            agent='deep',seed=7,out_root=tmp_path/'results',expected_database='telesale'))
    assert not model.called
    assert json.loads((out/'run.json').read_text())['status']=='failed'
    assert not (out/'btc_score.json').exists()


def test_child_preflight_diagnostic_survives_coordinator_boundary(tmp_path):
    from eval_harness.run_official import _run_one
    report=tmp_path/'full.diagnostics_full.report.json'
    report.write_text(json.dumps({'status':'failed','error_type':'PreflightError',
        'phase':'preflight','error_code':'mcp_database_identity_unavailable','service':'knowledge'}))
    with patch('eval_harness.run_official.subprocess.run',return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(RuntimeError) as caught:
            _run_one('full',tmp_path,'deep',7,'r',tmp_path,btc_root=tmp_path,
                expected_database='telesale',release={'release_id':'r','manifest_hash':'h'})
    assert caught.value.error_code=='mcp_database_identity_unavailable'
    assert caught.value.phase=='preflight'
    assert caught.value.service=='knowledge'


def test_child_progress_is_inherited_unbuffered_but_stderr_stays_private(tmp_path,capsys):
    from eval_harness.run_official import _run_one
    import subprocess
    trace=tmp_path/'full.diagnostics_full.jsonl'
    trace.write_text('')
    trace.with_suffix('.report.json').write_text(json.dumps({'status':'completed'}))
    with patch('eval_harness.run_official.subprocess.run',return_value=SimpleNamespace(returncode=0)) as child:
        _run_one('full',tmp_path,'deep',7,'r',tmp_path,btc_root=tmp_path,
            expected_database='telesale',release={'release_id':'r','manifest_hash':'h'})
    args=child.call_args
    assert '-u' in args.args[0]
    assert not args.kwargs.get('capture_output',False)
    assert args.kwargs.get('stdout') is None
    assert args.kwargs['stderr']==subprocess.PIPE
    assert '[eval] full: starting' in capsys.readouterr().out


def test_child_execution_error_survives_without_raw_stderr(tmp_path):
    from eval_harness.run_official import _run_one
    report = tmp_path/'full.diagnostics_full.report.json'
    report.write_text(json.dumps({'status':'failed', 'phase':'warmup',
        'error_code':'warmup_execution_unhealthy', 'execution_error': {
            'phase':'model_invocation', 'status':'failed', 'error_type':'BadRequestError',
            'http_status':400, 'error_code':'invalid_value', 'error_param':'tools[0].function.name',
            'message':'private-secret'}}))
    with patch('eval_harness.run_official.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='private-secret')):
        with pytest.raises(RuntimeError) as caught:
            _run_one('full',tmp_path,'deep',7,'r',tmp_path,btc_root=tmp_path,
                     expected_database='telesale',release={'release_id':'r','manifest_hash':'h'})
    assert caught.value.execution_error['error_type'] == 'BadRequestError'
    assert 'private-secret' not in json.dumps(caught.value.__dict__)


def test_full_failure_never_starts_baseline_or_publishes(tmp_path):
    scenarios=tmp_path/'scenarios'
    scenarios.mkdir()
    (scenarios/'case.json').write_text(json.dumps({'scenario_id':'X','calls':{'call_1':{'customer_turns':['Chào']}}}))
    with patch('eval_harness.run_official.Settings',return_value=SimpleNamespace(app_env='test')), \
         patch('eval_harness.run_official.database_url',return_value='offline'), \
         patch('eval_harness.run_official.capture_release',new_callable=AsyncMock,return_value={'release_id':'btc-only'}), \
         patch('eval_harness.run_official.fingerprint_btc_source',new_callable=AsyncMock,return_value='seed'), \
         patch('eval_harness.run_official._run_one',side_effect=RuntimeError('warmup failed')) as child, \
         patch('eval_harness.run_official.publish_pair') as publish:
        from pathlib import Path
        btc=Path(__file__).resolve().parents[3]/'BTC-Data-Vong1-TEAMS'
        out=asyncio.run(run_pair(scenarios=scenarios,btc_root=btc,agent='deep',seed=7,
                                out_root=tmp_path/'runs',expected_database='telesale'))
    assert child.call_count==1 and child.call_args.args[0]=='full'
    publish.assert_not_called()
    assert json.loads((out/'run.json').read_text())['status']=='failed'


@pytest.mark.parametrize('payload', ['[]', 'null', '"private-secret"', '{broken'])
def test_malformed_child_report_keeps_safe_runner_failure(tmp_path, payload):
    from eval_harness.run_official import _run_one
    (tmp_path/'full.diagnostics_full.report.json').write_text(payload)
    with patch('eval_harness.run_official.subprocess.run',return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(RuntimeError) as caught:
            _run_one('full',tmp_path,'deep',7,'r',tmp_path,btc_root=tmp_path,
                     expected_database='telesale',release={'release_id':'r','manifest_hash':'h'})
    assert caught.value.error_code == 'configuration_execution_failed'
    assert 'private-secret' not in str(caught.value.__dict__)
