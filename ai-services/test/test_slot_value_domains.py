"""Slot domains and customer quote validation for memory candidates."""

import unittest

from app.agent.guardrails.checks import FactRejectReason, fact_evidence
from app.agent.memory.fact_candidates import accepted_candidates
from app.constants import SLOT_SPEC_BY_KEY, Slot


class SlotValueDomainTests(unittest.TestCase):
    def test_expensive_objections_map_to_observed_value(self):
        for text, proposal in (
            ("Mắc quá", "mắc quá"),
            ("Giá hơi cao", "giá hơi cao"),
            ("Đắt thế", "đắt thế"),
            ("Hơi chát", "hơi chát"),
            ("Mẫu này đắt quá; tôi muốn loại bền", "đắt quá"),
        ):
            with self.subTest(text=text):
                evidence = fact_evidence(Slot.OBJECTION, proposal, "set", text, [])
                self.assertEqual(evidence.source, "customer")
                self.assertEqual(evidence.normalized_value, "dat_qua")
                self.assertTrue(evidence.evidence_quote)
                accepted = accepted_candidates(text, [], [{"key": Slot.OBJECTION,
                                                            "value": proposal}])
                self.assertEqual(accepted[0]["value"], "dat_qua")
                self.assertIn("evidence_quote", accepted[0])

    def test_other_objection_keeps_literal_quote(self):
        text = "Máy này chạy ồn quá"
        accepted = accepted_candidates(text, [], [{"key": Slot.OBJECTION,
            "value": "ồn quá", "evidence_quote": "chạy ồn quá"}])
        self.assertEqual(accepted[0]["value"], "khac")
        self.assertEqual(accepted[0]["evidence_quote"], "chạy ồn quá")
        self.assertEqual(fact_evidence(Slot.OBJECTION, "dat_qua", "set", text, [],
                                       "chạy ồn quá").reason,
                         FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW)
        self.assertEqual(fact_evidence(Slot.OBJECTION, "khac", "set", text, [],
                                       "chạy êm quá").reason,
                         FactRejectReason.QUOTE_NOT_FOUND)
        self.assertEqual(fact_evidence(Slot.OBJECTION, "phân vân giữa mua và thuê",
                                       "set", "Tôi phân vân giữa mua và thuê", []).reason,
                         FactRejectReason.NEUTRAL_CHOICE_NOT_OBJECTION)

    def test_questions_negation_and_hypothesis_do_not_become_objections(self):
        for text, reason in (
            ("nó không đắt", FactRejectReason.NEGATED_CONTEXT),
            ("giá có đắt không?", FactRejectReason.QUESTION_CONTEXT),
            ("nếu đắt thì thôi", FactRejectReason.HYPOTHETICAL_CONTEXT),
        ):
            with self.subTest(text=text):
                self.assertEqual(fact_evidence(Slot.OBJECTION, "đắt", "set",
                                               text, []).reason, reason)

    def test_objection_requires_a_purchase_concern_in_the_quoted_clause(self):
        rejected = (
            ("đi công tác nhiều ngày", FactRejectReason.CIRCUMSTANCE_NOT_OBJECTION),
            ("thích đồ dễ vệ sinh", FactRejectReason.PREFERENCE_NOT_OBJECTION),
            ("không thích giày có dây", FactRejectReason.PREFERENCE_NOT_OBJECTION),
            ("nhà không có thang máy", FactRejectReason.CIRCUMSTANCE_NOT_OBJECTION),
            ("tôi thích máy gọn nhẹ", FactRejectReason.PREFERENCE_NOT_OBJECTION),
            ("nhà tôi ở tầng cao", FactRejectReason.CIRCUMSTANCE_NOT_OBJECTION),
        )
        for text, reason in rejected:
            with self.subTest(text=text):
                evidence = fact_evidence(Slot.OBJECTION, text, "set", text, [])
                self.assertEqual(evidence.reason, reason)
                self.assertEqual(accepted_candidates(text, [], [
                    {"key": Slot.OBJECTION, "value": text,
                     "evidence_quote": text}]), [])

        accepted = (
            ("sợ hàng không bền", "khac"),
            ("chưa tin hàng này", "khac"),
            ("giao lâu quá", "khac"),
            ("bên kia rẻ hơn", "khac"),
            ("đắt quá", "dat_qua"),
            ("tôi lo bảo hành", "khac"),
            ("máy sấy chạy ồn quá", "khac"),
            ("phí giao hàng cao quá", "khac"),
        )
        for text, normalized in accepted:
            with self.subTest(text=text):
                evidence = fact_evidence(Slot.OBJECTION, text, "set", text, [], text)
                self.assertEqual(evidence.source, "customer")
                self.assertEqual(evidence.normalized_value, normalized)

        customer = "Tôi thích máy gọn nhẹ, nhưng lo chất lượng không bền."
        self.assertEqual(fact_evidence(Slot.OBJECTION, "thích máy gọn nhẹ", "set",
                                       customer, [], "thích máy gọn nhẹ").reason,
                         FactRejectReason.PREFERENCE_NOT_OBJECTION)
        self.assertEqual(fact_evidence(Slot.OBJECTION, "lo chất lượng không bền",
                                       "set", customer, [],
                                       "lo chất lượng không bền").source, "customer")
        self.assertEqual(fact_evidence(Slot.OBJECTION, "lo bảo hành", "set",
                                       "Nếu tôi lo bảo hành thì sao?", []).reason,
                         FactRejectReason.HYPOTHETICAL_CONTEXT)

    def test_payment_and_color_use_value_window(self):
        payment = fact_evidence(Slot.PAYMENT, "MoMo", "set",
                                "Tôi thanh toán qua MoMo", [])
        self.assertEqual(payment.normalized_value, "momo")
        self.assertEqual(payment.source, "customer")
        self.assertEqual(fact_evidence(Slot.PAYMENT, "bank", "set",
                                       "Tôi chuyển khoản nhé", []).source,
                         "customer")
        color = fact_evidence(Slot.PREFERRED_COLOR, "xanh dương", "set",
                              "Tôi chọn màu xanh dương", [])
        self.assertEqual(color.source, "customer")
        self.assertEqual(fact_evidence(Slot.PAYMENT, "MoMo", "set",
                                       "Thanh toán qua MoMo được không?", []).reason,
                         FactRejectReason.QUESTION_CONTEXT)
        self.assertEqual(fact_evidence(Slot.PAYMENT, "momo", "set",
                                       "Tôi thanh toán COD, MoMo thì sao?", [],
                                       "thanh toán COD").reason,
                         FactRejectReason.VALUE_NOT_IN_QUOTE_WINDOW)
        self.assertEqual(fact_evidence(Slot.PREFERRED_COLOR, "xanh dương", "set",
                                       "Tôi không chọn màu xanh dương", []).reason,
                         FactRejectReason.NEGATED_CONTEXT)
        self.assertEqual(fact_evidence(Slot.PAYMENT, "bank", "set",
                                       "Tôi không chuyển khoản", []).reason,
                         FactRejectReason.NEGATED_CONTEXT)
        self.assertEqual(fact_evidence(Slot.BUDGET_VND, 5_000_000, "set",
                                       "Nhà có con nhỏ và ngân sách 5 triệu", [],
                                       "Nhà có con nhỏ và ngân sách 5 triệu").source,
                         "customer")

    def test_closed_domains_are_not_free_text(self):
        self.assertEqual(SLOT_SPEC_BY_KEY[Slot.PAYMENT].allowed_values,
                         ("COD", "bank", "momo", "zalopay"))
        examples = (
            (Slot.PAYMENT, "tiền mặt", "Tôi thanh toán tiền mặt",
             FactRejectReason.VALUE_OUT_OF_DOMAIN),
            (Slot.HAS_CHILDREN, "false", "Tôi chưa có con",
             FactRejectReason.TYPE_INVALID),
            (Slot.BUDGET_VND, "4000000", "Ngân sách 4 triệu",
             FactRejectReason.TYPE_INVALID),
            (Slot.ROOM_AREA_M2, -20, "Phòng âm 20 m²",
             FactRejectReason.VALUE_OUT_OF_DOMAIN),
            (Slot.PROMO_EXPIRY, "2026-13-01", "",
             FactRejectReason.VALUE_OUT_OF_DOMAIN),
        )
        for key, value, text, reason in examples:
            with self.subTest(key=key, value=value):
                self.assertEqual(fact_evidence(key, value, "set", text, []).reason,
                                 reason)


if __name__ == "__main__":
    unittest.main()
