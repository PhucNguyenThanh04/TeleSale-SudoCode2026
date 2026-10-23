"""Long summaries keep structured decisions without leaking personal data."""

import unittest

from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary


class EpisodeSummaryTest(unittest.TestCase):
    def test_products_stay_in_facts_not_session_summary(self):
        facts = [{"key": "product_advised", "value": sku, "scope_type": "product",
                  "scope_id": sku, "status": "active"}
                 for sku in ("SKU-A1", "SKU-B2", "SKU-C3", "SKU-D4")]
        turns = [{"customer_text": "Tôi đang cân nhắc thêm chi tiết " + str(i) * 15,
                  "agent_text": "Dạ"} for i in range(30)]
        summary = build_episode_summary(facts, turns, 200, episode_state={
            "topics": [{"next_step": "Khách sẽ so sánh trước khi quyết định",
                        "items": []}]})
        self.assertLessEqual(len(summary), 200)
        self.assertIn("Khách sẽ so sánh", summary)
        for sku in ("SKU-A1", "SKU-B2", "SKU-C3", "SKU-D4"):
            self.assertNotIn(sku, summary)

    def test_mask_personal_data_and_leave_room_constraints_in_facts(self):
        facts = [{"key": "room_area_m2", "value": 12, "scope_type": "room",
                  "scope_id": "phong_ngu", "status": "active"},
                 {"key": "room_area_m2", "value": 45, "scope_type": "room",
                  "scope_id": "phong_khach", "status": "active"}]
        turns = [{"customer_text": "Gọi tôi 0912345678", "agent_text": "Dạ"}]
        summary = build_episode_summary(facts, turns, 200, episode_state={
            "topics": [{"next_step": "Gọi 0912345678 để xác nhận", "items": []}]})
        self.assertNotIn("phong_ngu", summary)
        self.assertNotIn("phong_khach", summary)
        self.assertNotIn("0912345678", summary)

    def test_many_facts_do_not_displace_structured_session_state(self):
        facts = [{"key": "product_advised", "value": f"SKU-{i:03d}",
                  "scope_type": "product", "scope_id": f"SKU-{i:03d}",
                  "status": "active"} for i in range(30)]
        summary = build_episode_summary(facts, [{"customer_text": "Chi tiết mới"}], 32,
                                        episode_state={"topics": [
                                            {"next_step": "Chờ khách xác nhận", "items": []}]})
        self.assertLessEqual(len(summary), 32)
        self.assertIn("Chờ khách", summary)
        self.assertNotIn("SKU-000", summary)
