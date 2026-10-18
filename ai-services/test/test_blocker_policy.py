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

    def test_decision_maker_and_specific_delay_variants(self):
        accepted = (
            ("để tôi bàn với chồng", "bàn với chồng"),
            ("chồng tôi chưa đồng ý", "chồng tôi chưa đồng ý"),
            ("phải xin ý kiến bố mẹ", "xin ý kiến bố mẹ"),
            ("chờ anh ấy về", "chờ anh ấy về"),
            ("hỏi ý kiến vợ đã", "hỏi ý kiến vợ"),
            ("chưa quyết được", "chưa quyết được"),
            ("để tôi xem lại rồi báo", "xem lại rồi báo"),
            ("Tôi cần trao đổi với mẹ trước khi đặt", "trao đổi với mẹ"),
        )
        for text, value in accepted:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.BLOCKER, value, "set", text, []).source,
                                 "customer")
        rejected = (
            ("để suy nghĩ thêm", "suy nghĩ thêm", FactRejectReason.PATTERN_NOT_MATCHED),
            ("chồng tôi thích màu đen", "chồng tôi thích màu đen",
             FactRejectReason.PREFERENCE_NOT_BLOCKER),
            ("tôi không thích hỏi nhiều", "không thích hỏi nhiều",
             FactRejectReason.PREFERENCE_NOT_BLOCKER),
        )
        for text, value, reason in rejected:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.BLOCKER, value, "set", text, []).reason,
                                 reason)

    def test_completed_actions_and_delivery_updates_are_not_new_blockers(self):
        rejected = (
            ("chờ giao hàng mấy ngày vậy?", "chờ giao hàng", FactRejectReason.QUESTION_CONTEXT),
            ("tôi chờ hàng ba ngày rồi chưa thấy", "chờ hàng ba ngày",
             FactRejectReason.DELIVERY_STATUS_NOT_BLOCKER),
            ("xem lại giỏ hàng giúp tôi", "xem lại giỏ hàng",
             FactRejectReason.PATTERN_NOT_MATCHED),
            ("chồng tôi đồng ý rồi", "chồng tôi đồng ý rồi",
             FactRejectReason.RESOLVED_BLOCKER),
            ("tôi đã bàn với chồng rồi", "bàn với chồng",
             FactRejectReason.PAST_CONSULTATION_NOT_BLOCKER),
            ("tôi hỏi thêm về bảo hành", "hỏi thêm về bảo hành",
             FactRejectReason.PATTERN_NOT_MATCHED),
            ("vợ tôi đã đồng ý", "vợ tôi đã đồng ý",
             FactRejectReason.RESOLVED_BLOCKER),
            ("tôi đã hỏi mẹ xong", "hỏi mẹ",
             FactRejectReason.PAST_CONSULTATION_NOT_BLOCKER),
        )
        for text, value, reason in rejected:
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.BLOCKER, value, "set", text, []).reason,
                                 reason)
                self.assertEqual(accepted_candidates(text, [], [
                    {"key": Slot.BLOCKER, "value": value}]), [])
        self.assertEqual(fact_evidence(Slot.BLOCKER, "bàn với chồng", "set",
                                       "tôi sẽ bàn với chồng rồi quyết định", []).source,
                         "customer")


if __name__ == "__main__":
    unittest.main()
