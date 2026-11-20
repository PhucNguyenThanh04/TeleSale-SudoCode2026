
import unittest

from app.agent.memory.reported_facts import reported_tool_candidates


class MemoryRefinementTest(unittest.TestCase):
    def test_unique_catalog_name_suffix_is_reported_product(self):
        calls = [{"name": "catalog.search", "args": {}, "result": {"items": [
            {"sku": "SKU-A", "name": "Máy lọc không khí AirPure X"},
            {"sku": "SKU-B", "name": "Máy lọc không khí AirPure Y"}]}}]
        self.assertEqual([(x["key"], x["value"]) for x in reported_tool_candidates(
            "Em tư vấn AirPure Y cho phòng này.", calls)], [("product_advised", "SKU-B")])

    def test_reported_promo_is_retained_only_when_communicated(self):
        calls = [{"name": "pricing.get_quote", "args": {"sku": "SKU-A"},
                  "result": {"sku": "SKU-A", "final_price_vnd": 4_890_000,
                             "applied_promos": [{"promo_code": "GIFT-X", "type": "gift",
                                                 "gift_sku": "SKU-FILTER",
                                                 "valid_until": "2026-10-22"}]}}]
        self.assertEqual({x["key"] for x in reported_tool_candidates(
            "Mẫu này được tặng kèm một màng lọc thay thế ạ.", calls)},
            {"promo_code", "promo_expiry"})
        self.assertEqual(reported_tool_candidates("Em kiểm tra ưu đãi ạ.", calls), [])
