"""Grounding checks for customer facts and reported sales history."""

import unittest

from app.agent.memory.fact_candidates import (
    accepted_candidates, customer_slot_cues, resolved_blockers,
)
from app.agent.memory.reported_facts import reported_tool_candidates


class MemoryRefinementTest(unittest.TestCase):
    def test_reported_price_requires_final_text_and_matching_quote(self):
        calls = [{"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X", "on": "2026-10-15"},
                  "result": {"sku": "SKU-AP-X", "final_price_vnd": 5_200_000}}]
        proposal = [{"key": "price_quoted_vnd", "value": 5_200_000}]
        self.assertEqual(accepted_candidates("Giá bao nhiêu?", calls, proposal,
                                             "Dạ, em kiểm tra lại ạ."), [])
        for answer in ("Dạ, giá là 5.200.000đ ạ.", "Dạ, giá 5,2 triệu ạ.",
                       "Dạ, giá 5tr2 ạ.", "Dạ, giá năm triệu hai ạ."):
            with self.subTest(answer=answer):
                self.assertEqual(accepted_candidates("Giá bao nhiêu?", calls, proposal,
                                                     answer)[0]["value"], 5_200_000)

    def test_product_and_promo_are_only_saved_when_reported(self):
        calls = [{"name": "catalog.search", "args": {}, "result": {"items": [
            {"sku": "SKU-AP-X", "name": "AirPure X"}]}},
            {"name": "pricing.get_quote", "args": {"sku": "SKU-AP-X"},
             "result": {"sku": "SKU-AP-X", "final_price_vnd": 4_890_000,
                        "applied_promos": [{"promo_code": "GIFT-FILTER",
                                            "valid_until": "2026-10-22"}]}}]
        proposals = [{"key": "product_advised", "value": "SKU-AP-X"},
                     {"key": "promo_code", "value": "GIFT-FILTER"},
                     {"key": "promo_expiry", "value": "2026-10-22"}]
        self.assertEqual(accepted_candidates("Chị được giảm GIFT-FILTER đúng không?",
                                             calls, proposals, "Dạ, em kiểm tra ạ."), [])
        facts = accepted_candidates("Có KM gì?", calls, proposals,
                                    "AirPure X có quà GIFT-FILTER ạ.")
        self.assertEqual({item["key"] for item in facts},
                         {"product_advised", "promo_code", "promo_expiry"})
        self.assertEqual(reported_tool_candidates("Dạ, em kiểm tra ạ.", calls), [])
        self.assertEqual({item["key"] for item in reported_tool_candidates(
            "AirPure X có quà GIFT-FILTER ạ.", calls)},
            {"product_advised", "promo_code", "promo_expiry"})

    def test_customer_negation_and_third_party(self):
        self.assertEqual(accepted_candidates("Chị chưa có con", [],
                         [{"key": "has_children", "value": False}])[0]["value"], False)
        self.assertEqual(accepted_candidates("Chị chưa có con", [],
                         [{"key": "has_children", "value": True}]), [])
        self.assertEqual(accepted_candidates("Bạn tôi có con nhỏ", [],
                         [{"key": "has_children", "value": True}]), [])
        self.assertEqual(accepted_candidates("khong co con nho", [],
                         [{"key": "has_children", "value": False}])[0]["value"], False)
        self.assertEqual(accepted_candidates("ngan sach anh nam trieu ruoi", [],
                         [{"key": "budget_vnd", "value": 5_500_000}])[0]["value"],
                         5_500_000)
        self.assertEqual(accepted_candidates("phong anh hai chuc met vuong", [],
                         [{"key": "room_area_m2", "value": 20}])[0]["value"], 20)

    def test_fallback_cues_and_blocker_closure(self):
        self.assertIn("has_children", customer_slot_cues("khong co con nho"))
        self.assertIn("room_area_m2", customer_slot_cues("phong hai chuc met vuong"))
        self.assertEqual(resolved_blockers("Vợ anh đồng ý rồi", {
            "blocker": {"value": "can hoi vo"}}, []),
            [{"key": "blocker", "op": "delete", "source_kind": "customer"}])
        self.assertEqual(resolved_blockers("Vợ anh đồng ý rồi", {
            "blocker": {"value": "can hoi vo"}},
            [{"key": "blocker", "value": "chờ nhận lương"}]), [])


if __name__ == "__main__":
    unittest.main()
