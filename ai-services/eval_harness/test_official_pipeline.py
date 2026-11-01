"""Contract tests for publication through the unchanged BTC scorer."""

import json
from pathlib import Path

import pytest

from eval_harness.official_pipeline import publish_pair


ROOT = Path(__file__).resolve().parents[2]
BTC = ROOT.parent / "BTC-Data-Vong1-TEAMS"


def _case(tmp_path):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "case.json").write_text(json.dumps({
        "scenario_id": "LOCAL-01", "calls": {"call_1": {
            "customer_turns": ["Xin chào"]}}}), encoding="utf-8")
    identity = {"database": "telesale", "host": "localhost", "port": 5432}
    paths = {}
    for config in ("full", "baseline_no_memory"):
        path = tmp_path / f"{config}.jsonl"
        row = {"run_id": f"run-{config}", "config": config,
               "scenario_id": "LOCAL-01", "call": "call_1", "turn": 1,
               "customer_text": "Xin chào", "agent_text": "Dạ chào anh/chị",
               "questions": [], "claims": [], "tool_calls": [],
               "latency": {"ttft_ms": 4, "total_ms": 4}}
        path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        path.with_suffix(".report.json").write_text(json.dumps({
            "run_id": row["run_id"], "config": config,
            "database_identity": identity}), encoding="utf-8")
        paths[config] = path
    metadata = dict(source_digest="source", seed_id="seed-7", seed_digest="seed-hash",
                    model_id="model-A", model_params={"temperature": 0},
                    tool_mode="mcp", guardrails={"enabled": True},
                    database_identity=identity, hardware={"cpu": "test"},
                    started_at_utc="2026-11-01T00:00:00Z",
                    expected_database="telesale", app_env="test")
    return scenarios, paths, metadata


def test_publish_pair_matches_btc_and_writes_manifests(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    result = publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                          tmp_path / "score.json", metadata, btc_root=BTC)
    assert result["score"]["n_scenarios"] == 1
    assert result["manifests"]["full"]["trace_rows"] == 1
    assert (tmp_path / "full.manifest.json").is_file()
    assert (tmp_path / "baseline_no_memory.manifest.json").is_file()


def test_invalid_trace_never_publishes_score(tmp_path):
    scenarios, paths, metadata = _case(tmp_path)
    paths["full"].write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Trace audit failed"):
        publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                     tmp_path / "score.json", metadata, btc_root=BTC)
    assert not (tmp_path / "score.json").exists()


@pytest.mark.parametrize("field", [
    {"memory_error": "job_failed"}, {"agent_text": "[ERROR: RuntimeError]"}])
def test_operational_failure_never_publishes_score(tmp_path, field):
    scenarios, paths, metadata = _case(tmp_path)
    row = json.loads(paths["full"].read_text())
    paths["full"].write_text(json.dumps({**row, **field}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Trace audit failed"):
        publish_pair(scenarios, paths["full"], paths["baseline_no_memory"],
                     tmp_path / "score.json", metadata, btc_root=BTC)
    assert not (tmp_path / "score.json").exists()
