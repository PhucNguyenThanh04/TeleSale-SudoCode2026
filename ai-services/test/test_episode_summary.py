"""Long summaries keep structured decisions without leaking personal data."""

import unittest

from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary


class EpisodeSummaryTest(unittest.TestCase):
    def test_four_confirmed_products_survive_long_recent_tail(self):
        facts = [{"key": "product_advised", "value": sku, "scope_type": "product",
                  "scope_id": sku, "status": "active"}
                 for sku in ("SKU-A1", "SKU-B2", "SKU-C3", "SKU-D4")]
        turns = [{"customer_text": "Tôi đang cân nhắc thêm chi tiết " + str(i) * 15,
                  "agent_text": "Dạ"} for i in range(30)]
        summary = build_episode_summary(facts, turns, 200)
        self.assertLessEqual(len(summary), 200)
        for sku in ("SKU-A1", "SKU-B2", "SKU-C3", "SKU-D4"):
            self.assertIn(sku, summary)

    def test_mask_personal_data_and_keep_room_constraints(self):
        facts = [{"key": "room_area_m2", "value": 12, "scope_type": "room",
                  "scope_id": "phong_ngu", "status": "active"},
                 {"key": "room_area_m2", "value": 45, "scope_type": "room",
                  "scope_id": "phong_khach", "status": "active"}]
        turns = [{"customer_text": "Gọi tôi 0912345678", "agent_text": "Dạ"}]
        summary = build_episode_summary(facts, turns, 200)
        self.assertIn("phong_ngu", summary)
        self.assertIn("phong_khach", summary)
        self.assertNotIn("0912345678", summary)

    def test_many_required_facts_use_bounded_reference_to_structured_facts(self):
        facts = [{"key": "product_advised", "value": f"SKU-{i:03d}",
                  "scope_type": "product", "scope_id": f"SKU-{i:03d}",
                  "status": "active"} for i in range(30)]
        summary = build_episode_summary(facts, [{"customer_text": "Chi tiết mới"}], 32)
        self.assertLessEqual(len(summary), 32)
        self.assertIn("cấu trúc", summary)
        self.assertNotIn("SKU-000", summary)
