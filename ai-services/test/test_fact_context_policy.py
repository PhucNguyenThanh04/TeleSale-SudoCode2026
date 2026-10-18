"""Clause context must not turn a question or a negated choice into a customer fact."""

import unittest

from app.agent.guardrails.checks import FactRejectReason, fact_evidence
from app.constants import Slot


class FactContextPolicyTests(unittest.TestCase):
    def test_questions_and_hypotheticals(self):
        rejected = (
            (Slot.PAYMENT, "momo", "thanh toan momo duoc khong", FactRejectReason.QUESTION_CONTEXT),
            (Slot.PAYMENT, "momo", "thanh toán momo được không?", FactRejectReason.QUESTION_CONTEXT),
            (Slot.HAS_CHILDREN, True, "nếu tôi có con nhỏ thì sao?", FactRejectReason.HYPOTHETICAL_CONTEXT),
            (Slot.HAS_CHILDREN, True, "giả sử tôi có con nhỏ thì sao?", FactRejectReason.HYPOTHETICAL_CONTEXT),
            (Slot.BLOCKER, "2 cái", "giả sử tôi mua 2 cái", FactRejectReason.HYPOTHETICAL_CONTEXT),
        )
        for key, value, text, reason in rejected:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(key, value, "set", text, []).reason, reason)

    def test_assertions_and_clause_scope(self):
        accepted = (
            (Slot.PAYMENT, "momo", "tôi thanh toán momo nhé"),
            (Slot.HAS_CHILDREN, True, "nhà có con nhỏ, hỏi giúp"),
            (Slot.BUDGET_VND, 5_000_000, "ngân sách 5 triệu, được không?"),
            (Slot.BUDGET_VND, 4_000_000, "Phòng 30 m² và tôi muốn chi không quá 4 triệu."),
            (Slot.HAS_CHILDREN, False, "nhà tôi không có con nhỏ"),
            (Slot.HAS_CHILDREN, False, "chưa có con nhỏ"),
        )
        for key, value, text in accepted:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(key, value, "set", text, []).source, "customer")

    def test_slot_specific_negation(self):
        self.assertEqual(fact_evidence(Slot.PAYMENT, "momo", "set", "tôi không thanh toán momo", []).reason,
                         FactRejectReason.NEGATED_CONTEXT)
        self.assertEqual(fact_evidence(Slot.BLOCKER, "giao gấp", "set", "không cần giao gấp", []).reason,
                         FactRejectReason.NEGATED_CONTEXT)
        self.assertEqual(fact_evidence(Slot.BUDGET_VND, 4_000_000, "set", "tôi muốn chi không quá 4 triệu", []).source,
                         "customer")
        # The existing budget parser does not represent a floor or recognize these short forms.
        for text in ("không hơn 4 triệu", "không dưới 4 triệu"):
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.BUDGET_VND, 4_000_000, "set", text, []).reason,
                                 FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW)


if __name__ == "__main__":
    unittest.main()
