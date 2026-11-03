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
        "scenario_id": "CASE-A", "calls": {}}), encoding="utf-8")
    identity = {"database": "telesale_eval_test"}

    def fake_run(config, scenarios, agent, seed, run_id, out):
        trace = out / f"{config}.jsonl"
        trace.write_text("", encoding="utf-8")
        trace.with_suffix(".report.json").write_text(json.dumps({
            "database_identity": identity}), encoding="utf-8")
        return trace

    settings = SimpleNamespace(app_env="test", llm_model="fake",
                               llm_temperature=0, llm_max_tokens=1,
                               agent_prompt_history_turns=1,
                               agent_guardrails_enabled=True)
    with patch("eval_harness.run_official.Settings", return_value=settings), \
         patch("eval_harness.run_official.database_url", return_value="dsn"), \
         patch("eval_harness.run_official.fingerprint_btc_source",
               new_callable=AsyncMock, return_value="seed"), \
         patch("eval_harness.run_official.source_snapshot_digest", return_value="source"), \
         patch("eval_harness.run_official._run_one", side_effect=fake_run), \
         patch("eval_harness.run_official.publish_pair", return_value={
             "manifests": {"full": {}, "baseline_no_memory": {}}}), \
         patch("asyncpg.connect", side_effect=AssertionError("Retired RAG must not query source DB")):
        out = asyncio.run(run_pair(scenarios=scenarios, btc_root=tmp_path,
                                   agent="deep", seed=7, out_root=tmp_path / "results"))

    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "validated"
    assert "rag_summary" not in run
    assert not (out / "rag_retrieval.json").exists()
