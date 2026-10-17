"""Rejected drafts remain inspectable in eval state without raw contact data."""

import asyncio
import json
import unittest

from app.agent.guardrails.checks import FALLBACK
from app.agent.guardrails.diagnostics import rejected_draft
from app.agent.harness.agent_nodes import AgentNodes


class VerifierDiagnosticsTest(unittest.TestCase):
    def test_blocked_price_records_redacted_draft_claim_span_and_sources(self):
        node = AgentNodes.__new__(AgentNodes)
        node.guardrails_enabled = True
        state = {
            "agent_draft": "Chị Hoa, gọi 0912345678. Giá máy 4.890.000đ ạ.",
            "customer_name": "Hoa",
            "safe_text": "Máy này giá bao nhiêu?",
            "profile": {"budget_vnd": {"value": 5_000_000, "source_kind": "customer"}},
            "tool_calls": [],
        }
        result = asyncio.run(node.verify_agent(state))
        self.assertEqual(result["agent_text"], FALLBACK)
        event = result["verifier_events"][0]
        self.assertEqual(event["reason"], "price_without_quote")
        self.assertEqual(event["claim_type"], "price")
        self.assertEqual(event["claims"][0]["value"], 4_890_000)
        start, end = event["claims"][0]["span"]
        self.assertEqual(event["agent_draft"][start:end], "4.890.000đ")
        self.assertEqual(event["source_evidence"]["memory"]["amounts_vnd"],
                         [5_000_000])
        self.assertFalse(event["source_evidence"]["quote"]["available"])
        serialized = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("0912345678", serialized)
        self.assertNotIn("Hoa", serialized)

    def test_policy_amount_is_attributed_without_copying_policy_body(self):
        state = {"agent_draft": "COD áp dụng cho đơn dưới 10 triệu ạ.",
                 "safe_text": "Shop có COD không?",
                 "tool_calls": [{"name": "policy.search", "result": {"chunks": [
                     {"chunk_id": "VC-03", "body": "COD cho đơn dưới 10 triệu."}]}}]}
        event = rejected_draft(state, "price_without_quote")
        self.assertEqual(event["claims"][0]["value"], 10_000_000)
        self.assertEqual(event["claims"][0]["matched_sources"], ["policy.search"])
        self.assertEqual(event["source_evidence"]["policy.search"]["chunk_ids"],
                         ["VC-03"])
        self.assertNotIn("body", event["source_evidence"]["policy.search"])

    def test_spec_event_keeps_explicit_false_from_catalog(self):
        state = {"agent_draft": "Mẫu này có khóa trẻ em.",
                 "safe_text": "Máy có khóa trẻ em không?",
                 "tool_calls": [{"name": "catalog.search", "result": {"items": [
                     {"sku": "SKU-EXAMPLE", "attributes": {"child_safe_lock": False}}]}}]}
        event = rejected_draft(state, "unsupported_product_spec")
        self.assertEqual(event["claim_type"], "spec")
        self.assertEqual(event["source_evidence"]["catalog.search"]["items"][0]
                         ["features"]["child_safe_lock"], "không có")


if __name__ == "__main__":
    unittest.main()
