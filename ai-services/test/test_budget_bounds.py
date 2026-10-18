"""Spending ceilings are budget facts; spending floors need a distinct slot."""

import unittest

from app.agent.guardrails.checks import (FactRejectReason, customer_budget_amounts,
                                         fact_evidence)
from app.agent.memory.fact_candidates import accepted_candidates, customer_slot_cues
from app.constants import Slot


class BudgetBoundsTests(unittest.TestCase):
    def test_standalone_ceilings_are_grounded(self):
        for text in ("không quá 4 triệu", "không hơn 4 triệu", "không vượt 4 triệu",
                     "tối đa 4 triệu", "dưới 4 triệu", "khong vuot 4tr",
                     "tôi muốn máy giá dưới 4 triệu"):
            with self.subTest(text=text):
                self.assertIn(Slot.BUDGET_VND, customer_slot_cues(text))
                self.assertEqual(customer_budget_amounts(text), {4_000_000})
                self.assertEqual(fact_evidence(Slot.BUDGET_VND, 4_000_000, "set", text, []).source,
                                 "customer")
        self.assertEqual(customer_budget_amounts("tối đa 3,8 triệu"), {3_800_000})
        self.assertEqual(customer_budget_amounts("không vượt 800k"), {800_000})

    def test_floors_never_become_budget_ceiling(self):
        for text in ("không dưới 4 triệu", "không thấp hơn 4 triệu", "tối thiểu 4 triệu", "ít nhất 4 triệu",
                     "ngân sách không dưới 4 triệu", "ngan sach khong duoi 4tr",
                     "tôi định chi ít nhất 4 triệu"):
            with self.subTest(text=text):
                self.assertNotIn(4_000_000, customer_budget_amounts(text))
                self.assertEqual(fact_evidence(Slot.BUDGET_VND, 4_000_000, "set", text, []).reason,
                                 FactRejectReason.UNSUPPORTED_FLOOR)
                self.assertEqual(accepted_candidates(text, [], [
                    {"key": Slot.BUDGET_VND, "value": 4_000_000}]), [])

    def test_an_independent_ceiling_survives_a_floor(self):
        text = "Tôi chi ít nhất 4 triệu nhưng tối đa 6 triệu."
        self.assertEqual(customer_budget_amounts(text), {6_000_000})
        self.assertEqual(fact_evidence(Slot.BUDGET_VND, 4_000_000, "set", text, []).reason,
                         FactRejectReason.UNSUPPORTED_FLOOR)
        self.assertEqual(fact_evidence(Slot.BUDGET_VND, 6_000_000, "set", text, []).source,
                         "customer")

    def test_price_reports_questions_and_hypotheticals_are_not_budget(self):
        self.assertNotIn(4_000_000, customer_budget_amounts("Shop báo giá dưới 4 triệu."))
        for text in ("Dưới 4 triệu được không?", "Nếu tôi chi không quá 4 triệu thì sao?"):
            with self.subTest(text=text):
                self.assertIsNone(fact_evidence(Slot.BUDGET_VND, 4_000_000, "set", text, []).source)

    def test_ranges_store_only_ceiling(self):
        for text in ("từ 3 đến 5 triệu", "3-5 triệu", "tầm 3 đến 5 triệu",
                     "ngân sách từ 3 triệu đến 5 triệu"):
            with self.subTest(text=text):
                self.assertEqual(customer_budget_amounts(text), {5_000_000})
                self.assertEqual(fact_evidence(Slot.BUDGET_VND, 5_000_000, "set", text, []).source,
                                 "customer")
                self.assertEqual(fact_evidence(Slot.BUDGET_VND, 3_000_000, "set", text, []).reason,
                                 FactRejectReason.UNSUPPORTED_FLOOR)
        self.assertEqual(customer_budget_amounts("ngân sách 5-3 triệu"), set())

    def test_ceiling_words_need_money_units(self):
        for text, value in (("phòng dưới 25m2", 25), ("tối đa 2 cái", 2),
                            ("dưới 3 người", 3)):
            with self.subTest(text=text):
                self.assertEqual(customer_budget_amounts(text), set())
                self.assertIsNone(fact_evidence(Slot.BUDGET_VND, value, "set", text, []).source)

    def test_amount_spellings_require_spending_context(self):
        spellings = (("4tr", 4_000_000), ("4 củ", 4_000_000),
                     ("4 triệu rưỡi", 4_500_000), ("4tr5", 4_500_000),
                     ("800k", 800_000), ("4.000.000đ", 4_000_000),
                     ("4,5 triệu", 4_500_000))
        for spelling, amount in spellings:
            with self.subTest(spelling=spelling):
                self.assertEqual(customer_budget_amounts(spelling), set())
                self.assertIsNone(fact_evidence(Slot.BUDGET_VND, amount, "set", spelling, []).source)
                statement = "Ngân sách của tôi " + spelling
                self.assertEqual(customer_budget_amounts(statement), {amount})
                self.assertEqual(fact_evidence(Slot.BUDGET_VND, amount, "set", statement, []).source,
                                 "customer")


if __name__ == "__main__":
    unittest.main()
