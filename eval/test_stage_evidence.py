import json
import unittest
from types import SimpleNamespace

from eval.stage_evidence import stage_evidence


class StageEvidenceTest(unittest.TestCase):
    def test_known_customer_records_stage_keys_without_values_or_pii(self):
        state = {
            "identity_status": "known", "customer_name": "Lan",
            "customer_phone": "0912345678", "profile": {
                "budget_vnd": {"value": 5000000, "source": "old-session:1"}},
            "scoped_facts": {"product": {
                "SKU-TEST": {"price_quoted_vnd": {"value": 4900000}},
                "0912345678": {"preferred_color": {"value": "đỏ"}}}},
            "episodes": [{"summary": "Gọi 0912345678"}],
            "call_brief": {"customer_phone": "0912345678",
                           "must_not_ask": ["budget_vnd"],
                           "open_blockers": ["Cần hỏi vợ"]},
            "tool_calls": [{"name": "order.create", "args": {"phone": "0912345678"},
                            "result": {"ok": True, "order_id": "OD-123"}}],
            "memory_writes": [{"key": "budget_vnd", "value": 5000000}],
        }
        item = stage_evidence(state, SimpleNamespace(call_brief=state["call_brief"]),
                              scenario_id="CASE-X", call="call_2", turn=1,
                              run_id="run-1", config="full")
        self.assertEqual(item["memory_read_status"], "ok")
        self.assertEqual(item["prior_fact_keys"], ["budget_vnd"])
        self.assertEqual(item["scoped_fact_keys"]["product"]["SKU-TEST"],
                         ["price_quoted_vnd"])
        self.assertEqual(item["business_tools"], [{"name": "order.create",
                                                   "status": "success"}])
        self.assertEqual(item["memory_write_count"], 1)
        raw = json.dumps(item, ensure_ascii=False)
        for sensitive in ("0912345678", "Lan", "5000000", "4900000", "OD-123",
                          "Cần hỏi vợ"):
            self.assertNotIn(sensitive, raw)

    def test_failure_is_not_reported_as_empty_success(self):
        state = {"identity_status": "ambiguous", "profile": {},
                 "memory_failure": "memory.read", "tool_calls": [],
                 "memory_writes": []}
        item = stage_evidence(state, SimpleNamespace(call_brief=None),
                              scenario_id="CASE-X", call="call_1", turn=1,
                              run_id="run-1", config="full")
        self.assertEqual(item["identity_status"], "ambiguous")
        self.assertEqual(item["memory_read_status"], "failed")
        self.assertFalse(item["call_brief_present"])

    def test_failed_business_write_is_visible_without_result_body(self):
        item = stage_evidence({"identity_status": "unknown", "profile": {},
            "tool_calls": [{"name": "order.create", "result": {"error": "bad phone 0912345678"}}]},
            SimpleNamespace(call_brief=None), scenario_id="CASE-X", call="call_1", turn=1,
            run_id="run-1", config="full")
        self.assertEqual(item["business_tools"], [{"name": "order.create",
                                                   "status": "failed"}])
        self.assertEqual(item["memory_read_status"], "unknown")
        self.assertNotIn("0912345678", json.dumps(item))

    def test_btc_order_result_with_created_status_counts_as_success(self):
        item = stage_evidence({"identity_status": "known", "profile": {},
            "tool_calls": [{"name": "order.create", "result": {
                "order_id": "OD-123", "status": "created", "total_vnd": 4900000}}]},
            SimpleNamespace(call_brief=None), scenario_id="CASE-X", call="call_2", turn=2,
            run_id="run-1", config="full")
        self.assertEqual(item["business_tools"], [{"name": "order.create",
                                                   "status": "success"}])

    def test_btc_action_receipts_count_as_success(self):
        for name, result in (
            ("order.update", {"order_id": "OD1", "status": "pickup_scheduled"}),
            ("schedule.callback", {"callback_id": "CB1", "callback_at": "2026-10-22T10:00"}),
            ("handoff.transfer", {"ticket_id": "HT1", "status": "queued"}),
        ):
            with self.subTest(name=name):
                item = stage_evidence({"identity_status": "known", "profile": {},
                    "tool_calls": [{"name": name, "result": result}]},
                    SimpleNamespace(call_brief=None), scenario_id="CASE-X", call="call_2", turn=2,
                    run_id="run-1", config="full")
                self.assertEqual(item["business_tools"], [{"name": name,
                                                           "status": "success"}])


if __name__ == "__main__":
    unittest.main()
