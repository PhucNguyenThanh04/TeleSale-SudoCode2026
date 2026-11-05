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


def test_conversation_run_does_not_execute_retired_rag(tmp_path):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "case.json").write_text(json.dumps({
        "scenario_id": "CASE-A", "calls": {"call_1": {"customer_turns": ["Xin chào"]}}}), encoding="utf-8")
    identity = {"database": "telesale_eval_test"}

    def fake_run(config, scenarios, agent, seed, run_id, out, **kwargs):
        trace = out / f"{config}.jsonl"
        trace.write_text("", encoding="utf-8")
        trace.with_suffix(".report.json").write_text(json.dumps({
            "database_identity": identity}), encoding="utf-8")
        return trace

    settings = SimpleNamespace(app_env="test", llm_model="fake", ollama_base_url="https://offline.invalid",
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
         patch("eval_harness.run_official.publish_pair", return_value={
             "manifests": {"full": {}, "baseline_no_memory": {}}}), \
         patch("asyncpg.connect", side_effect=AssertionError("Retired RAG must not query source DB")):
        out = asyncio.run(run_pair(scenarios=scenarios, btc_root=__import__("pathlib").Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS",
                                   agent="deep", seed=7, out_root=tmp_path / "results", expected_database="telesale_eval_test"))

    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "validated"
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
