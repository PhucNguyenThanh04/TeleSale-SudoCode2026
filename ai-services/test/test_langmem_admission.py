"""Only evidence-backed LangMem proposals become canonical writes."""

import unittest
from datetime import date

from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


def candidate(key, value, quote, *, op="set", turn="turn-1", source="customer"):
    return ProfileFactCandidate(key=key, value=value, op=op,
        source_kind=source, source_turn_id=turn, evidence_quote=quote,
        observed_on=date(2026, 10, 15))


class AdmissionTests(unittest.TestCase):
    def test_accepts_customer_correction_with_source_turn(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        accepted, rejected = admit_profile_candidates("C001", "session-1", [
            candidate("color", "trang", "anh lấy màu trắng", op="supersede")],
            [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
              "customer_text": "Thôi anh lấy màu trắng", "agent_text": "Dạ."}], [])
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["key"], "color")
        self.assertEqual(accepted[0]["op"], "supersede")

    def test_rejects_wrong_customer_turn(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        accepted, rejected = admit_profile_candidates("C001", "session-1", [
            candidate("room_area_m2", 25, "25 mét vuông")],
            [{"turn_id": "turn-1", "customer_id": "C002", "session_id": "session-1",
              "customer_text": "Phòng 25 mét vuông"}], [])
        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["reason"], "identity_mismatch")

    def test_rejects_hypothetical_change(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        accepted, rejected = admit_profile_candidates("C001", "session-1", [
            candidate("color", "trang", "Nếu lấy màu trắng", op="supersede")],
            [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
              "customer_text": "Nếu lấy màu trắng thì sao?"}], [])
        self.assertEqual(accepted, [])
        self.assertTrue(rejected)

    def test_rejects_tool_fact_without_successful_tool(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        proposal = candidate("price_quoted_vnd", 4890000, "4.890.000",
                             source="tool")
        proposal.source_tool = "pricing.get_quote"
        accepted, rejected = admit_profile_candidates("C001", "session-1", [proposal],
            [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
              "customer_text": "Giá bao nhiêu?", "agent_text": "Giá 4.890.000 đồng"}], [])
        self.assertEqual(accepted, [])
        self.assertTrue(rejected)

    def test_conflicting_values_in_one_turn_are_not_admitted(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        accepted, rejected = admit_profile_candidates("C001", "session-1", [
            candidate("color", "den", "màu đen"),
            candidate("color", "trang", "màu trắng")],
            [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
              "customer_text": "Tôi thích màu đen, nhưng thôi lấy màu trắng"}], [])
        self.assertEqual(accepted, [])
        self.assertIn("conflicting_values", [item["reason"] for item in rejected])

    def test_episode_requires_same_customer_and_literal_blocker(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
        episode = CustomerCallEpisodeCandidate(customer_id="C001", session_id="session-1",
            channel="hotline", on=date(2026, 10, 15), source_turn_ids=["turn-1"],
            open_blockers=["hỏi chồng"])
        turns = [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
                  "customer_text": "Để tôi hỏi chồng rồi gọi lại"}]
        result = admit_episode_candidate("C001", "session-1", episode, turns, [])
        self.assertEqual(result["topic_updates"][0]["add_items"][0]["kind"], "blocker")

    def test_episode_goal_requires_literal_evidence(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
        episode = CustomerCallEpisodeCandidate(customer_id="C001", session_id="session-1",
            channel="hotline", on=date(2026, 10, 15), source_turn_ids=["turn-1"],
            customer_goal="Tôi muốn mua máy lọc khí")
        turns = [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
                  "customer_text": "Tôi muốn mua máy lọc khí"}]
        result = admit_episode_candidate("C001", "session-1", episode, turns, [])
        self.assertEqual(result["topic_updates"][0]["customer_goal"],
                         "Tôi muốn mua máy lọc khí")
