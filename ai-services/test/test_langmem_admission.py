"""Only evidence-backed LangMem proposals become canonical writes."""

import unittest
from datetime import date

from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


def candidate(key, value, quote, *, op="set", turn="turn-1", source="customer"):
    return ProfileFactCandidate(key=key, value=value, op=op,
        source_kind=source, source_turn_id=turn, evidence_quote=quote,
        observed_on=date(2026, 10, 15))


class AdmissionTests(unittest.TestCase):
    def test_model_customer_id_in_global_scope_is_normalized(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        proposal = candidate("has_children", True, "Nhà chị có bé nhỏ")
        proposal.scope_id = "C001"
        accepted, rejected = admit_profile_candidates("C001", "session-1", [proposal],
            [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
              "customer_text": "Nhà chị có bé nhỏ"}], [])
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["scope_id"], "")

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

    def test_accepts_order_id_from_successful_tool_without_customer_quote(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        proposal = candidate("order_id", "OD682761", "order.create:OD682761",
                             source="tool")
        proposal.source_tool = "order.create"
        accepted, rejected = admit_profile_candidates("C001", "session-1", [proposal],
            [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
              "customer_text": "Lên đơn giúp tôi", "agent_text": "Dạ, đã tạo đơn."}],
            [{"name": "order.create", "source_turn_id": "turn-1",
              "args": {"sku": "SKU-SN-CAS-39-DEN"},
              "result": {"status": "created", "order_id": "OD682761"}}])
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["value"], "OD682761")

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

    def test_normalised_blocker_admitted_when_supported_by_quote(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
        from app.schemas.langmem import EvidencedText
        episode = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-1", channel="hotline",
            on=date(2026, 10, 15), source_turn_ids=["turn-1"],
            open_blockers=[EvidencedText(text="cần hỏi ông xã",
                                         evidence_quote="để chị hỏi ông xã rồi gọi lại")])
        turns = [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
                  "customer_text": "Thôi để chị hỏi ông xã rồi gọi lại nhé"}]
        result = admit_episode_candidate("C001", "session-1", episode, turns, [])
        self.assertIsNotNone(result)
        self.assertEqual(result["topic_updates"][0]["add_items"][0]["text"],
                         "cần hỏi ông xã")
        self.assertEqual(result["topic_updates"][0]["add_items"][0]["evidence_quote"],
                         "để chị hỏi ông xã rồi gọi lại")

    def test_unsupported_blocker_is_rejected(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
        from app.schemas.langmem import EvidencedText
        episode = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-1", channel="hotline",
            on=date(2026, 10, 15), source_turn_ids=["turn-1"],
            open_blockers=[EvidencedText(text="chờ lương về cuối tháng",
                                         evidence_quote="để chị hỏi ông xã rồi gọi lại")])
        turns = [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
                  "customer_text": "Thôi để chị hỏi ông xã rồi gọi lại nhé"}]
        self.assertIsNone(admit_episode_candidate("C001", "session-1", episode, turns, []))

    def test_product_topic_scope_kept_when_sku_in_tools_else_downgraded(self):
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
        from app.schemas.langmem import EvidencedText, TopicProposal
        topic_ok = TopicProposal(
            scope_type="product", scope_id="SKU-AP-X",
            advice_given=EvidencedText(
                text="Tư vấn mẫu SKU-AP-X cho phòng 25m2",
                evidence_quote="Em tư vấn mẫu SKU-AP-X phù hợp phòng 25m2"))
        topic_unknown = TopicProposal(
            scope_type="product", scope_id="SKU-FAKE",
            next_step=EvidencedText(
                text="Gọi lại chiều mai chốt đơn",
                evidence_quote="Chiều mai em gọi lại hỗ trợ chốt đơn"))
        episode = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-1", channel="hotline",
            on=date(2026, 10, 15), source_turn_ids=["turn-1"],
            topics=[topic_ok, topic_unknown])
        turns = [{"turn_id": "turn-1", "customer_id": "C001", "session_id": "session-1",
                  "customer_text": "Tư vấn cho chị máy lọc không khí",
                  "agent_text": "Em tư vấn mẫu SKU-AP-X phù hợp phòng 25m2. Chiều mai em gọi lại hỗ trợ chốt đơn."}]
        calls = [{"name": "pricing.get_quote", "source_turn_id": "turn-1",
                  "args": {"sku": "SKU-AP-X"}, "result": {"sku": "SKU-AP-X", "final_price_vnd": 4890000}}]
        result = admit_episode_candidate("C001", "session-1", episode, turns, calls)
        scopes = {(u["scope_type"], u["scope_id"]) for u in result["topic_updates"]}
        self.assertIn(("product", "SKU-AP-X"), scopes)
        self.assertIn(("global", ""), scopes)
        self.assertNotIn(("product", "SKU-FAKE"), scopes)

    def test_sample_01_flow_resolves_prior_blocker_across_sessions(self):
        from uuid import uuid4
        from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
        from app.schemas.langmem import EvidencedText, ResolvedItem, TopicProposal

        turn1_id, turn2_id = str(uuid4()), str(uuid4())
        ep1 = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-1", channel="hotline",
            on=date(2026, 10, 10), source_turn_ids=[turn1_id],
            open_blockers=[EvidencedText(text="hỏi ông xã",
                                         evidence_quote="Để chị hỏi ông xã đã nhé")])
        turns1 = [{"turn_id": turn1_id, "customer_id": "C001", "session_id": "session-1",
                   "customer_text": "Để chị hỏi ông xã đã nhé", "agent_text": "Dạ vâng ạ"}]
        delta1 = admit_episode_candidate("C001", "session-1", ep1, turns1, [])
        state1 = apply_episode_delta({"topics": []}, delta1, source_turn_id=turn1_id,
                                     customer_text=turns1[0]["customer_text"],
                                     agent_text=turns1[0]["agent_text"])
        item_id = state1["topics"][0]["items"][0]["item_id"]
        prior_open = {item_id: ("unknown", "")}

        ep2 = CustomerCallEpisodeCandidate(
            customer_id="C001", session_id="session-2", channel="hotline",
            on=date(2026, 10, 15), source_turn_ids=[turn2_id],
            topics=[TopicProposal(
                scope_type="global", scope_id="",
                resolved_items=[ResolvedItem(item_id=item_id,
                                             evidence_quote="Ông xã chị đồng ý rồi em ơi")])])
        turns2 = [{"turn_id": turn2_id, "customer_id": "C001", "session_id": "session-2",
                   "customer_text": "Ông xã chị đồng ý rồi em ơi, lên đơn cho chị",
                   "agent_text": "Dạ vâng ạ"}]
        delta2 = admit_episode_candidate("C001", "session-2", ep2, turns2, [], prior_open)
        state2 = apply_episode_delta({"topics": []}, delta2, source_turn_id=turn2_id,
                                     customer_text=turns2[0]["customer_text"],
                                     agent_text=turns2[0]["agent_text"],
                                     prior_open_items=prior_open)
        self.assertEqual(state2["resolved_prior_items"][0]["item_id"], item_id)
