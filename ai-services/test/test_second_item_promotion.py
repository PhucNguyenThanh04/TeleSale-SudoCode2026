"""Second-item promotion applies to both products through applies_to."""

import unittest

from app.mcp_servers.mcp_shared.commerce_rules import quote


PRODUCTS = [
    {"sku": "SKU-AP-X", "category": "gia-dung/may-loc-khong-khi",
     "list_price_vnd": 4_890_000, "variants": []},
    {"sku": "SKU-AP-Y", "category": "gia-dung/may-loc-khong-khi/cao-cap",
     "list_price_vnd": 5_200_000, "variants": []},
    {"sku": "SKU-SN-RUN1", "category": "thoi-trang/giay-chay-bo",
     "list_price_vnd": 2_000_000, "variants": []},
]
AIR_SECOND = {
    "promo_code": "AIR-2ND-50", "applies_to": ["category:gia-dung/may-loc-khong-khi"],
    "type": "percent_second_item", "discount_percent": 50,
    "start": "2026-10-05", "end": "2026-11-04", "stackable": False,
    "conditions": {"min_qty": 2},
}


class SecondItemPromotionTest(unittest.TestCase):
    def test_two_air_purifiers_discount_cheaper_one_as_before(self):
        result = quote(PRODUCTS, [AIR_SECOND], {
            "sku": "SKU-AP-X", "on": "2026-10-15", "basket_skus": ["SKU-AP-Y"]})
        self.assertEqual(result["final_price_vnd"], 2_445_000)
        self.assertEqual(result["applied_promos"], [{
            "promo_code": "AIR-2ND-50", "type": "percent_second_item",
            "discount_vnd": 2_445_000}])

    def test_air_purifier_with_shoe_does_not_discount(self):
        result = quote(PRODUCTS, [AIR_SECOND], {
            "sku": "SKU-AP-X", "on": "2026-10-15", "basket_skus": ["SKU-SN-RUN1"]})
        self.assertEqual(result["final_price_vnd"], 4_890_000)
        self.assertEqual(result["applied_promos"], [])
        self.assertEqual(result["ineligible_promos"], [{
            "promo_code": "AIR-2ND-50", "reason": "not_cheapest_item"}])

    def test_single_item_order_fails_min_qty(self):
        # basket_skus lists other products; an empty list means one item total.
        result = quote(PRODUCTS, [AIR_SECOND], {
            "sku": "SKU-AP-X", "on": "2026-10-15", "basket_skus": []})
        self.assertEqual(result["final_price_vnd"], 4_890_000)
        self.assertEqual(result["ineligible_promos"], [{
            "promo_code": "AIR-2ND-50", "reason": "min_qty"}])

    def test_sku_list_applies_to_both_items(self):
        promotion = {**AIR_SECOND, "promo_code": "PAIR-RUN",
                     "applies_to": ["SKU-SN-RUN1", "SKU-AP-X"]}
        result = quote(PRODUCTS, [promotion], {
            "sku": "SKU-SN-RUN1", "on": "2026-10-15", "basket_skus": ["SKU-AP-X"]})
        self.assertEqual(result["final_price_vnd"], 1_000_000)
        self.assertEqual(result["applied_promos"], [{
            "promo_code": "PAIR-RUN", "type": "percent_second_item",
            "discount_vnd": 1_000_000}])


if __name__ == "__main__":
    unittest.main()
