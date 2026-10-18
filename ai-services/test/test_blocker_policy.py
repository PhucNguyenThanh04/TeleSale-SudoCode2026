"""Only an actual obstacle to a purchase decision belongs in blocker."""

import unittest

from langchain_core.messages import AIMessage

from app.agent.guardrails.checks import FactRejectReason, fact_evidence
from app.agent.memory.fact_candidates import accepted_candidates, model_candidates
from app.constants import Slot


class BlockerPolicyTests(unittest.TestCase):
    def test_preferences_and_delivery_constraints_are_rejected(self):
        examples = (
            ("lắp ráp phức tạp", "Tôi không thích phải lắp ráp phức tạp.",
             FactRejectReason.PREFERENCE_NOT_BLOCKER),
            ("giày có dây", "Tôi đi size 38 và không thích giày có dây.",
             FactRejectReason.PREFERENCE_NOT_BLOCKER),
            ("màu đỏ", "Tôi không thích màu đỏ.", FactRejectReason.PREFERENCE_NOT_BLOCKER),
            ("hỏi mẹ", "Tôi không muốn hỏi mẹ.", FactRejectReason.PREFERENCE_NOT_BLOCKER),
            ("chỉ nhận hàng sau 18 giờ", "Tôi thích màu xanh, nhưng chỉ nhận hàng sau 18 giờ.",
             FactRejectReason.DELIVERY_CONSTRAINT_NOT_BLOCKER),
            ("giao buổi sáng", "Tôi không thích giao buổi sáng.",
             FactRejectReason.DELIVERY_CONSTRAINT_NOT_BLOCKER),
        )
        for value, text, reason in examples:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.BLOCKER, value, "set", text, []).reason, reason)
                self.assertEqual(accepted_candidates(text, [], [{"key": Slot.BLOCKER, "value": value}]), [])

    def test_actual_decision_obstacles_are_accepted(self):
        examples = (
            ("hỏi chồng", "Để tôi hỏi chồng rồi quyết định."),
            ("hỏi vợ", "Tôi phải hỏi vợ đã rồi mới mua được."),
            ("hỏi mẹ", "Tôi phải hỏi mẹ đã."),
            ("hỏi thêm người nhà", "Tôi cần hỏi thêm người nhà rồi quyết định."),
            ("đợi lương", "Đợi lương về rồi mua."),
            ("chờ bên kia báo giá", "Chờ bên kia báo giá."),
        )
        for value, text in examples:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.BLOCKER, value, "set", text, []).source,
                                 "customer")

    def test_extractor_keeps_short_blocker_and_redacted_quote(self):
        candidates = model_candidates([AIMessage(content='{"fact_candidates": [{'
            '"key": "blocker", "value": "hỏi mẹ", "source": "customer", '
            '"evidence_quote": "phải hỏi mẹ đã"}]}')])
        self.assertEqual(candidates[0]["value"], "hỏi mẹ")
        self.assertEqual(candidates[0]["evidence_quote"], "phải hỏi mẹ đã")
        unsafe = model_candidates([AIMessage(content='{"fact_candidates": [{'
            '"key": "blocker", "value": "hỏi mẹ", "source": "customer", '
            '"evidence_quote": "gọi 0901234567"}]}')])
        self.assertNotIn("evidence_quote", unsafe[0])


if __name__ == "__main__":
    unittest.main()
