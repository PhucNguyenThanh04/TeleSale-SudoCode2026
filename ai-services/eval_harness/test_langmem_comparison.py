"""Release gate uses BTC denominators and identical run metadata."""

import unittest

from eval_harness.compare_langmem import compare


def report(*, ccr=60, tsr=70, hard=50, rqr=20, hr=0,
           price_claims=3, brief=3000, guard=0, seed=7):
    return {"meta": {"model": "gemma4:31b", "temperature": 0.2,
                      "max_tokens": 256, "seed": seed,
                      "reference_date": "2026-10-15", "dataset_hash": "same"},
            "system": {"repeat_question_rate": {"value": rqr, "total_questions": 10},
                       "context_carryover_rate": {"value": ccr, "required": 10},
                       "task_success_rate": {"value": tsr, "total": 10,
                           "hard_cases": {"value": hard, "total": 4}, "failures": []},
                       "hallucination_rate": {"price_promo_only": {
                           "value": hr, "total": price_claims}},
                       "guardrail_violations": {"total": guard,
                           "by_type": {"pii_in_memory_or_text": 0}},
                       "latency": {"call_brief": {"n": 5, "p95_ms": brief},
                           "total": {"n": 10, "p95_ms": 7000},
                           "ttft": {"n": 10, "p95_ms": 7000}}}}


class CompareTests(unittest.TestCase):
    def test_improvement_without_regression_passes(self):
        current = report()
        shadow = report()
        enabled = report(ccr=80, tsr=70, rqr=10)
        result = compare({"current": current, "shadow": shadow, "enabled": enabled})
        self.assertTrue(result["adoption_gate"]["pass"])
        self.assertEqual(result["variants"]["enabled"]["rqr_relative_reduction_pct"], 50)

    def test_missing_price_claims_and_brief_are_inconclusive(self):
        enabled = report(ccr=80, price_claims=0)
        enabled["system"]["latency"]["call_brief"] = None
        result = compare({"current": report(), "shadow": report(), "enabled": enabled})
        self.assertIsNone(result["variants"]["enabled"]["price_promo_hr_pct"])
        self.assertFalse(result["adoption_gate"]["pass"])

    def test_mismatched_seed_and_regression_fail(self):
        result = compare({"current": report(), "shadow": report(seed=8),
                          "enabled": report(ccr=80, tsr=60, guard=1)})
        self.assertFalse(result["adoption_gate"]["pass"])
        self.assertIn("run_metadata_mismatch", result["adoption_gate"]["reasons"])
        self.assertIn("task_success_regression", result["adoption_gate"]["reasons"])

    def test_scenario_ids_must_match_reference_set(self):
        current, shadow, enabled = report(), report(), report(ccr=80)
        for item in (current, shadow, enabled):
            item["meta"]["scenario_ids"] = ["SC01"]
            item["reference_scenario_ids"] = ["SAMPLE-01"]
        result = compare({"current": current, "shadow": shadow, "enabled": enabled})
        self.assertIn("scenario_coverage_mismatch", result["adoption_gate"]["reasons"])
