"""Unit tests for Eval Harness Scorer and Extractor."""

import unittest
from eval_harness.extractor import extract_questions, extract_claims, build_trace_row
from eval_harness.scorer import (
    pct,
    p95,
    args_match,
    evaluate_task_success,
    evaluate_memory_metrics,
    evaluate_hallucination,
    evaluate_guardrails,
    evaluate_diagnostics_and_latency,
)


class TestEvalHarness(unittest.TestCase):
    def test_math_helpers(self):
        self.assertEqual(pct(5, 10), 50.0)
        self.assertIsNone(pct(5, 0))
        self.assertEqual(p95([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]), 100)
        self.assertTrue(args_match({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(args_match({"a": 1}, {"a": 2}))

    def test_extractor_questions(self):
        text = "Chào chị, phòng nhà mình rộng bao nhiêu mét vuông ạ? Chị lấy size 40 đúng không ạ?"
        qs = extract_questions(text)
        self.assertTrue(len(qs) >= 2)
        types = {q["slot"]: q["type"] for q in qs}
        self.assertEqual(types.get("room_area_m2"), "open")
        self.assertEqual(types.get("size"), "confirm")

    def test_extractor_claims(self):
        text = "Dạ máy này còn hàng và giao trong vòng 2 ngày nhé anh."
        tool_calls = [{"name": "order.create", "args": {"sku": "SKU-AP-X", "price_vnd": 4200000}}]
        claims = extract_claims(text, tool_calls)
        fields = {c["field"]: c["value"] for c in claims}
        self.assertEqual(fields.get("in_stock"), True)
        self.assertEqual(fields.get("delivery_days"), 2)
        self.assertEqual(fields.get("sku"), "SKU-AP-X")
        self.assertEqual(fields.get("price_vnd"), 4200000)

    def test_scorer_task_success(self):
        scenarios = {
            "SC01": {
                "scenario_id": "SC01",
                "calls": {
                    "call_2": {
                        "success_if": {
                            "tool_called": "order.create",
                            "args_match": {"sku": "SKU-AP-Y", "price_vnd": 5200000},
                        }
                    }
                },
            }
        }
        trace_pass = {
            ("SC01", "call_2"): [
                {"tool_calls": [{"name": "order.create", "args": {"sku": "SKU-AP-Y", "price_vnd": 5200000}}]}
            ]
        }
        res = evaluate_task_success(scenarios, trace_pass)
        self.assertEqual(res["tsr_overall_pct"], 100.0)
        self.assertEqual(res["passed"], 1)

    def test_scorer_guardrails(self):
        scenarios = {"SC01": {"calls": {"call_1": {}}}}
        # Fake PII leak
        trace_leak = {("SC01", "call_1"): [{"agent_text": "Số CCCD của anh là 012345678901 đúng không?"}]}
        res = evaluate_guardrails(scenarios, trace_leak)
        self.assertEqual(res["total_violations"], 1)
        self.assertFalse(res["is_safe"])


if __name__ == "__main__":
    unittest.main()
