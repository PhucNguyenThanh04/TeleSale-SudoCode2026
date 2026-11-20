
import json

from eval_harness.preflight import inspect_eval_inputs


def test_preflight_reports_generic_scenario_and_trace_contract_issues(tmp_path):
    btc = tmp_path / "btc"
    schemas = btc / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "scenario_format.md").write_text(
        "| `expected_outcome` | chot_don / chuyen_may | outcome |\n",
        encoding="utf-8")
    (schemas / "tools.schema.json").write_text(json.dumps({"tools": [
        {"name": "order.create"}, {"name": "order.update"}]}), encoding="utf-8")
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "case.json").write_text(json.dumps({
        "scenario_id": "CASE-A", "calls": {
            "call_1": {"expected_outcome": "chot_don",
                       "facts_established": {"order_id": "OD123"}},
            "call_2": {"expected_outcome": "local_handoff",
                       "success_if": {"tool_called": "order.update",
                                      "args_match": {"order_id": "OD123",
                                                     "customer_phone": "0900000000"}}}}}),
        encoding="utf-8")
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"scenario_id": "CASE-A", "call": "call_2",
        "turn": 1, "tool_calls": [{"name": "[TÊN ĐÃ ẨN]",
                                    "args": {"order_id": "OD123"}}]}) + "\n",
        encoding="utf-8")

    report = inspect_eval_inputs(scenarios, btc, trace)

    assert report["scenario_count"] == 1
    assert {(issue["code"], issue["scenario_id"]) for issue in report["issues"]} == {
        ("unsupported_outcome", "CASE-A"),
        ("generated_order_id_exact_match", "CASE-A"),
        ("pii_args_match", "CASE-A"),
        ("redacted_tool_name", "CASE-A"),
    }
    assert report["trace_recoverable"] is False

    scorer_dir = btc / "eval"
    scorer_dir.mkdir()
    (scorer_dir / "reference_eval.py").write_text(
        "def args_match(expected, actual, order_aliases=()):\n    pass\n", encoding="utf-8")
    trace.write_text(json.dumps({"scenario_id": "CASE-A", "call": "call_1",
        "tool_calls": [{"name": "order.create", "result": {"status": "created"}},
                       {"name": "order.create", "result": {"order_id": "[SỐ ĐÃ ẨN]"}}]}) + "\n",
        encoding="utf-8")
    modern = inspect_eval_inputs(scenarios, btc, trace)
    codes = {issue["code"] for issue in modern["issues"]}
    assert "generated_order_id_exact_match" not in codes
    assert {"missing_created_order_id", "redacted_created_order_id"} <= codes
