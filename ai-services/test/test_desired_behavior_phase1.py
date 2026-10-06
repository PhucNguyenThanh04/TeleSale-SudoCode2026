"""Desired general behavior for Phase 0 type B findings.

Expected failures document existing gaps; Phase 1 does not change source code.
"""

import unittest
from uuid import UUID

from app.agent.guardrails import check_answer
from app.agent.nodes import _price_catalog_query, _single_price_sku
from app.agent.policy import _catalog_query, response_price_precondition
from app.agent.price_intent import detect_price_intent
from app.agent.state import Decision
from app.mcp_servers.mcp_shared.commerce_rules import quote
from app.schemas.agent import TextTurnRequest


class DesiredBehavior(unittest.TestCase):
    def test_non_prefixed_sku_in_response_is_resolved_from_catalog(self):
        request = TextTurnRequest(
            client_msg_id=UUID("11111111-1111-4111-8111-111111111111"),
            session_id=UUID("22222222-2222-4222-8222-222222222222"),
            channel="web_chat", channel_identity=None, on="2026-10-15",
            text="AIRPURE-X giá bao nhiêu?", input_mode="clean",
        )
        state = {
            "request": request,
            "decision": Decision(action="respond", response="AIRPURE-X giá 2 triệu đồng."),
            "tool_calls": [{"name": "catalog.search", "args": {}, "result": {
                "items": [{"sku": "AIRPURE-X", "name": "AirPure X"},
                          {"sku": "AIRPURE-Y", "name": "AirPure Y"}]}}],
        }
        self.assertEqual(response_price_precondition(state),
                         ("price_without_quote", "AIRPURE-X"))
        quote_call = {"name": "pricing.get_quote",
                      "args": {"sku": "AIRPURE-X", "on": "2026-10-15"},
                      "result": {"sku": "AIRPURE-X", "final_price_vnd": 2_000_000}}
        self.assertEqual(check_answer("AIRPURE-X giá 2 triệu đồng.", [quote_call])[1], None)
        catalog_call = {"name": "catalog.search", "args": {}, "result": {
            "items": [{"sku": "AIRPURE-X", "name": "AirPure X"},
                      {"sku": "AIRPURE-Y", "name": "AirPure Y"}]}}
        stock_call = {"name": "inventory.check", "args": {"sku": "AIRPURE-X"},
                      "result": {"sku": "AIRPURE-X", "in_stock": True, "qty": 1}}
        self.assertEqual(check_answer("AIRPURE-X còn hàng.", [catalog_call, stock_call])[1], None)
        self.assertEqual(check_answer("AIRPURE-Y còn hàng.", [catalog_call, stock_call])[1],
                         "stock_sku_mismatch")

    @unittest.expectedFailure
    def test_second_item_promotion_uses_promotion_category_data(self):
        products = [
            {"sku": "RUN-A", "category": "giay/chay-bo", "list_price_vnd": 1_000_000,
             "variants": []},
            {"sku": "RUN-B", "category": "giay/chay-bo", "list_price_vnd": 2_000_000,
             "variants": []},
        ]
        promos = [{"promo_code": "SECOND-SHOE", "type": "percent_second_item",
                   "applies_to": ["category:giay/chay-bo"],
                   "start": "2026-10-01", "end": "2026-10-31",
                   "discount_percent": 10, "stackable": False}]
        result = quote(products, promos, {"sku": "RUN-A", "on": "2026-10-15",
                                         "basket_skus": ["RUN-B"]})
        self.assertEqual(result["final_price_vnd"], 900_000)

    @unittest.expectedFailure
    def test_alternate_price_question_keeps_only_product_terms_for_catalog(self):
        self.assertEqual(_price_catalog_query("Xin báo chi phí của AirPure X giúp mình?"),
                         "AirPure X")

    @unittest.expectedFailure
    def test_model_catalog_query_removes_alternate_question_words(self):
        self.assertEqual(_catalog_query("Xin báo chi phí của AirPure X giúp mình?"),
                         "AirPure X")

    @unittest.expectedFailure
    def test_accessory_synonym_does_not_select_machine_sku(self):
        items = [{"sku": "AIRPURE-X", "category": "gia-dung/may-loc-khong-khi"},
                 {"sku": "FILTER-X", "category": "gia-dung/phu-kien"}]
        self.assertIsNone(_single_price_sku(items, "Lõi lọc dự phòng giá bao nhiêu?"))

    @unittest.expectedFailure
    def test_alternate_price_intent_is_recognized(self):
        self.assertTrue(detect_price_intent("Chi phí AirPure X thế nào?").needs_price)


if __name__ == "__main__":
    unittest.main()
