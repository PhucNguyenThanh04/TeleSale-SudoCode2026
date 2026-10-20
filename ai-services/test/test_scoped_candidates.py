"""Tool and customer evidence cannot jump between products or rooms."""

import unittest

from app.agent.memory.fact_candidates import accepted_candidates
from app.agent.memory.reported_facts import reported_tool_candidates


class ScopedCandidatesTest(unittest.TestCase):
    def test_equal_price_quotes_are_bound_to_each_named_sku(self):
        calls = [{"name": "pricing.get_quote", "args": {"sku": sku, "on": "2026-10-15"},
                  "result": {"sku": sku, "final_price_vnd": 2_500_000,
                             "applied_promos": []}}
                 for sku in ("SKU-ALPHA", "SKU-BETA")]
        answer = "SKU-ALPHA giá 2.500.000 đồng; SKU-BETA giá 2.500.000 đồng."
        candidates = reported_tool_candidates(answer, calls)
        accepted = accepted_candidates("Giá hai mẫu ra sao?", calls, candidates, answer)
        self.assertEqual({(item.get("scope_id"), item["value"])
                          for item in accepted if item["key"] == "price_quoted_vnd"},
                         {("SKU-ALPHA", 2_500_000), ("SKU-BETA", 2_500_000)})

    def test_stock_wording_does_not_cross_assign_sku(self):
        calls = [{"name": "inventory.check", "args": {"sku": "SKU-ALPHA", "on": "2026-10-15"},
                  "result": {"sku": "SKU-ALPHA", "in_stock": True}},
                 {"name": "inventory.check", "args": {"sku": "SKU-BETA", "on": "2026-10-15"},
                  "result": {"sku": "SKU-BETA", "in_stock": False}}]
        answer = "SKU-ALPHA còn hàng; SKU-BETA hết hàng."
        accepted = accepted_candidates("Hai mẫu còn hàng không?", calls,
                                       reported_tool_candidates(answer, calls), answer)
        self.assertEqual({(item.get("scope_id"), item["value"])
                          for item in accepted if item["key"] == "in_stock"},
                         {("SKU-ALPHA", True), ("SKU-BETA", False)})

    def test_model_cannot_attach_other_skus_stock_observation(self):
        calls = [{"name": "inventory.check", "args": {"sku": "SKU-ALPHA", "on": "2026-10-15"},
                  "result": {"sku": "SKU-ALPHA", "in_stock": True}},
                 {"name": "inventory.check", "args": {"sku": "SKU-BETA", "on": "2026-10-15"},
                  "result": {"sku": "SKU-BETA", "in_stock": False}}]
        accepted = accepted_candidates("Hai mẫu còn không?", calls, [{
            "key": "in_stock", "value": True, "scope_type": "product",
            "scope_id": "SKU-BETA"}])
        self.assertEqual(accepted, [])

    def test_two_explicit_rooms_are_retained_without_a_global_area(self):
        text = "Phòng ngủ 12 m², phòng khách 45 m²."
        proposals = [{"key": "room_area_m2", "value": 12,
                      "scope_type": "room", "scope_id": "phong_ngu"},
                     {"key": "room_area_m2", "value": 45,
                      "scope_type": "room", "scope_id": "phong_khach"}]
        accepted = accepted_candidates(text, [], proposals)
        self.assertEqual({(item.get("scope_id"), item["value"]) for item in accepted},
                         {("phong_ngu", 12), ("phong_khach", 45)})

    def test_unmentioned_room_scope_is_not_trusted(self):
        text = "Phòng ngủ 12 m²."
        accepted = accepted_candidates(text, [], [{"key": "room_area_m2", "value": 12,
            "scope_type": "room", "scope_id": "phong_khach"}])
        self.assertEqual(accepted, [])

    def test_second_room_is_an_assertion_and_hypothetical_is_not(self):
        actual = accepted_candidates("Phòng thứ hai 45 m², tôi muốn máy mạnh hơn.", [], [
            {"key": "room_area_m2", "value": 45}])
        self.assertEqual([(item.get("scope_id"), item["value"]) for item in actual],
                         [("phong_2", 45)])
        hypothetical = accepted_candidates("Nếu thử phòng thứ hai 45 m² thì sao?", [], [
            {"key": "room_area_m2", "value": 45}])
        self.assertEqual(hypothetical, [])

    def test_single_global_preference_stays_global(self):
        accepted = accepted_candidates("Tôi thích màu trắng.", [], [
            {"key": "preferred_color", "value": "trắng"}])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["key"], "preferred_color")
        self.assertNotIn("scope_id", accepted[0])
