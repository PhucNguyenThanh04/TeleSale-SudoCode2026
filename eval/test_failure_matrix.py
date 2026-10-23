import json
import tempfile
import unittest
from pathlib import Path

from eval.failure_matrix import build_failure_matrix


class FailureMatrixTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenarios = self.root / "scenarios"
        self.scenarios.mkdir()
        self.trace = self.root / "trace.jsonl"
        self.stages = self.root / "trace.stages.json"
        self.report = self.root / "score.json"

    def run_case(self, tool, tool_calls, *, stage=None, failed=False):
        (self.scenarios / "case.json").write_text(json.dumps({
            "scenario_id": "CASE-X", "calls": {"call_2": {
                "customer_turns": ["Xin chào"],
                "must_carry_over": ["product_advised"],
                "success_if": {"tool_called": tool,
                               "args_match": {"sku": "SKU-OTHER"} if tool == "order.create" else {}}}}}),
            encoding="utf-8")
        row = {"run_id": "run-1", "config": "full", "scenario_id": "CASE-X",
               "call": "call_2", "turn": 1, "agent_text": "Em xử lý ạ",
               "facts_used": [], "tool_calls": tool_calls}
        self.trace.write_text(json.dumps(row) + "\n", encoding="utf-8")
        evidence = {"scenario_id": "CASE-X", "call": "call_2", "turn": 1,
                    "run_id": "run-1", "config": "full",
                    "identity_status": "known", "memory_read_status": "ok",
                    "prior_episode_count": 1, "call_brief_present": True,
                    "business_tools": [{"name": c["name"], "status": "failed" if
                                       c.get("result", {}).get("error") else "success"}
                                      for c in tool_calls]}
        if stage:
            evidence.update(stage)
        self.stages.write_text(json.dumps([evidence]), encoding="utf-8")
        self.report.write_text(json.dumps({"system": {"task_success_rate": {
            "failures": ([{"scenario": "CASE-X", "call": "call_2",
                          "reasons": ["task failed"]}] if failed else [])}}}),
            encoding="utf-8")
        return build_failure_matrix(self.scenarios, self.trace, self.stages, self.report)[0]

    def test_successful_order_has_no_observed_failure(self):
        item = self.run_case("order.create", [{"name": "order.create",
            "args": {"sku": "SKU-OTHER"}, "result": {"order_id": "OD1", "status": "created"}}])
        self.assertIsNone(item["first_observed_failure"])

    def test_brief_present_without_order_exposes_action_gap(self):
        item = self.run_case("order.create", [], failed=True)
        self.assertEqual(item["first_observed_failure"]["stage"], "business_tool_call")
        self.assertEqual(item["first_observed_failure"]["turn"], 1)
        self.assertIn("agent_use", item["uncertain_stages"])

    def test_memory_failure_precedes_missing_order(self):
        item = self.run_case("order.create", [], stage={
            "memory_read_status": "failed", "call_brief_present": False}, failed=True)
        self.assertEqual(item["first_observed_failure"]["stage"], "memory_read")

    def test_failed_business_tool_result_is_observed(self):
        item = self.run_case("order.create", [{"name": "order.create",
            "args": {"sku": "SKU-OTHER"}, "result": {"error": "out_of_stock"}}], failed=True)
        self.assertEqual(item["first_observed_failure"]["stage"], "business_tool_result")

    def test_handoff_control_is_not_classified_as_missing_order(self):
        item = self.run_case("handoff.transfer", [{"name": "handoff.transfer",
            "args": {"brief": {"escalation_reason": "khac"}},
            "result": {"ticket_id": "HT1", "status": "queued"}}])
        self.assertIsNone(item["first_observed_failure"])

    def test_missing_stage_evidence_rejects_incomplete_diagnosis(self):
        self.run_case("order.create", [], failed=True)
        self.stages.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stage coverage"):
            build_failure_matrix(self.scenarios, self.trace, self.stages, self.report)

    def test_baseline_uses_baseline_verdict(self):
        self.run_case("order.create", [{"name": "order.create",
            "args": {"sku": "SKU-OTHER"}, "result": {"status": "created", "order_id": "OD1"}}])
        row = json.loads(self.trace.read_text())
        row["config"] = "baseline_no_memory"
        self.trace.write_text(json.dumps(row) + "\n", encoding="utf-8")
        stage = json.loads(self.stages.read_text())
        stage[0]["config"] = "baseline_no_memory"
        self.stages.write_text(json.dumps(stage), encoding="utf-8")
        self.report.write_text(json.dumps({
            "system": {"task_success_rate": {"failures": []}},
            "baseline": {"task_success_rate": {"failures": [{
                "scenario": "CASE-X", "call": "call_2", "reasons": ["baseline failed"]}]}}}),
            encoding="utf-8")
        item = build_failure_matrix(self.scenarios, self.trace, self.stages, self.report)[0]
        self.assertFalse(item["btc_passed"])
        self.assertEqual(item["btc_reasons"], ["baseline failed"])

    def test_prior_memory_write_failure_is_first_observed_stage(self):
        self.run_case("order.create", [], failed=True)
        scenario = json.loads((self.scenarios / "case.json").read_text())
        scenario["calls"] = {"call_1": {"customer_turns": ["Tôi chọn sản phẩm"]},
                             **scenario["calls"]}
        (self.scenarios / "case.json").write_text(json.dumps(scenario))
        stage = json.loads(self.stages.read_text())
        stage.insert(0, {"run_id": "run-1", "config": "full",
                         "scenario_id": "CASE-X", "call": "call_1", "turn": 1,
                         "memory_write_status": "failed"})
        self.stages.write_text(json.dumps(stage))
        self.trace.write_text(json.dumps({"run_id": "run-1", "config": "full",
            "scenario_id": "CASE-X", "call": "call_1", "turn": 1,
            "agent_text": "Đã ghi nhận", "tool_calls": []}) + "\n" +
            self.trace.read_text(), encoding="utf-8")
        item = build_failure_matrix(self.scenarios, self.trace, self.stages, self.report)[0]
        self.assertEqual(item["first_observed_failure"]["stage"], "memory_write")
        self.assertEqual(item["first_observed_failure"]["call"], "call_1")

    def test_sidecar_from_other_run_is_rejected(self):
        self.run_case("order.create", [], failed=True)
        stage = json.loads(self.stages.read_text())
        stage[0]["run_id"] = "different-run"
        self.stages.write_text(json.dumps(stage))
        with self.assertRaisesRegex(ValueError, "stage.*run"):
            build_failure_matrix(self.scenarios, self.trace, self.stages, self.report)


if __name__ == "__main__":
    unittest.main()
