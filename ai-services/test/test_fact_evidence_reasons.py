"""Fact diagnostics classify rejections without changing admission."""

import unittest

from app.agent.guardrails.checks import FactEvidence, FactRejectReason, fact_evidence
from app.constants import Slot


class FactEvidenceReasonTests(unittest.TestCase):
    def test_rejections_have_exactly_one_closed_reason(self):
        examples = (
            ("unknown", "x", "x", FactRejectReason.UNKNOWN_KEY),
            (Slot.BUDGET_VND, None, "Ngân sách 2 triệu", FactRejectReason.TYPE_INVALID),
            (Slot.BLOCKER, "", "Tôi hỏi vợ", FactRejectReason.EMPTY_VALUE),
            (Slot.BLOCKER, "0901234567", "Gọi 0901234567", FactRejectReason.PII_VALUE),
            (Slot.PAYMENT, "cash", "Tôi trả tiền mặt nhé.",
             FactRejectReason.VALUE_OUT_OF_DOMAIN),
            (Slot.HAS_CHILDREN, "true", "Tôi có con nhỏ", FactRejectReason.TYPE_INVALID),
            (Slot.ROOM_AREA_M2, 0, "Phòng rộng 0 m²", FactRejectReason.VALUE_OUT_OF_DOMAIN),
            (Slot.PROMO_EXPIRY, "2026-02-30", "", FactRejectReason.VALUE_OUT_OF_DOMAIN),
            (Slot.HAS_CHILDREN, False, "Nếu tôi có con nhỏ thì sao?",
             FactRejectReason.HYPOTHETICAL_CONTEXT),
            (Slot.PAYMENT, "MoMo", "Thanh toán bằng MoMo được không?",
             FactRejectReason.QUESTION_CONTEXT),
            (Slot.HAS_CHILDREN, True, "Bạn tôi có con nhỏ.",
             FactRejectReason.THIRD_PARTY_CONTEXT),
            (Slot.BLOCKER, "hỏi chồng", "Tôi còn phải hỏi vợ.",
             FactRejectReason.QUOTE_NOT_FOUND),
            (Slot.PRODUCT_ADVISED, "SKU-AP-X", "Tôi thích SKU-AP-X.",
             FactRejectReason.TOOL_EVIDENCE_MISSING),
        )
        for key, value, customer_text, expected in examples:
            with self.subTest(key=key, expected=expected):
                result = fact_evidence(key, value, "set", customer_text, [])
                self.assertIsNone(result.source)
                self.assertEqual(result.reason, expected)
                self.assertIn(result.reason, FactRejectReason)

    def test_result_invariant_and_existing_acceptance(self):
        with self.assertRaises(ValueError):
            FactEvidence(None, None)
        with self.assertRaises(ValueError):
            FactEvidence("customer", FactRejectReason.PATTERN_NOT_MATCHED)
        result = fact_evidence(Slot.PAYMENT, "COD", "set", "Tôi thanh toán COD.", [])
        self.assertEqual(result.source, "customer")
        self.assertIsNone(result.reason)


if __name__ == "__main__":
    unittest.main()
