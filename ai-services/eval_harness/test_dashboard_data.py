import hashlib
import json

import pytest

from eval_harness.dashboard_data import load_run, metric_rows, scenario_outcomes


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_dashboard_loads_only_validated_run_and_marks_missing_denominator(tmp_path):
    run = tmp_path / "run-1"
    run.mkdir()
    score = {"n_scenarios": 2, "system": {
        "task_success_rate": {"value": 50.0, "passed": 1, "total": 2,
                              "hard_cases": {"value": None, "total": 0},
                              "failures": []},
        "repeat_question_rate": {"value": None, "redundant": 0, "total_questions": 0},
        "context_carryover_rate": {"value": None, "used": 0, "required": 0},
        "hallucination_rate": {"value": None, "wrong": 0, "total_claims": 0,
                               "price_promo_only": {"value": None, "wrong": 0, "total": 0}},
        "guardrail_violations": {"total": 0, "by_type": {}, "examples": []},
        "latency": {"n_turns": 1, "total": {"n": 1, "p50_ms": 10, "p95_ms": 10},
                    "ttft": {"n": 1, "p50_ms": 10, "p95_ms": 10},
                    "call_brief": {"n": 0, "p50_ms": None, "p95_ms": None}}},
             "baseline": {}, "comparison": {"rqr_relative_reduction_pct": None}}
    score_path = run / "btc_score.json"
    _write(score_path, score)
    digest = hashlib.sha256(score_path.read_bytes()).hexdigest()
    traces = {}
    for config in ("full", "baseline_no_memory"):
        trace = run / f"{config}.jsonl"
        trace.write_text('{"safe": true}\n', encoding="utf-8")
        traces[config] = trace.name
        _write(run / f"{config}.manifest.json", {
            "config": config, "run_id": "run-1", "expected_rows": 1,
            "trace_rows": 1, "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
            "scorer_report_sha256": digest})
    _write(run / "run.json", {"run_id": "run-1", "status": "validated",
                              "score": "btc_score.json", "traces": traces})
    data = load_run(run)
    rows = metric_rows(data["score"])
    assert data["scenarios"] == 2 and data["turns"] == 1
    assert next(row for row in rows if row["key"] == "rqr")["status"] == "not_measured"
    assert next(row for row in rows if row["key"] == "tsr")["value"] == 50.0
    (run / "full.jsonl").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="trace"):
        load_run(run)
    (run / "full.jsonl").write_text('{"safe": true}\n', encoding="utf-8")
    _write(run / "full.manifest.json", {"config": "full", "run_id": "run-1",
                                              "expected_rows": 99, "trace_rows": 1,
                                              "scorer_report_sha256": digest})
    with pytest.raises(ValueError, match="manifest"):
        load_run(run)


def test_scenario_outcomes_include_passes_and_filter_group():
    score = {"system": {"task_success_rate": {"failures": [
        {"scenario": "SC02", "call": "call_2", "reasons": ["missing tool"]}]}}}
    groups = {"SC01": "M1", "SC02": "M2", "SC03": "M1"}
    assert scenario_outcomes(score, groups) == [
        {"scenario": "SC01", "group": "M1", "status": "pass"},
        {"scenario": "SC02", "group": "M2", "status": "fail"},
        {"scenario": "SC03", "group": "M1", "status": "pass"}]
    assert [x["scenario"] for x in scenario_outcomes(score, groups, "M1")] == ["SC01", "SC03"]
