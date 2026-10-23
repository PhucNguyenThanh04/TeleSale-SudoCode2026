"""Structured episode items retain evidence and transition without inventing state."""

import unittest
import json
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary
from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.agent.memory.store import MCPMemoryStore


class EpisodeStateTest(unittest.TestCase):
    def test_summary_uses_session_state_without_repeating_facts_or_dialogue(self):
        facts = [{"key": "room_area_m2", "value": 25, "scope_type": "room",
                  "scope_id": "phong_ngu", "status": "active"}]
        turns = [{"customer_text": "Alo, phòng ngủ 25 mét vuông."},
                 {"customer_text": "Để tôi hỏi ông xã rồi gọi lại."}]
        state = {"topics": [{"scope_type": "unknown", "scope_id": "",
            "customer_goal": "Tìm máy lọc cho phòng ngủ",
            "next_step": "Khách sẽ liên hệ lại",
            "items": [{"kind": "blocker", "status": "open",
                       "text": "hỏi ông xã"}]}]}
        summary = build_episode_summary(facts, turns, 200, episode_state=state)
        self.assertIn("Tìm máy lọc cho phòng ngủ", summary)
        self.assertIn("Khách sẽ liên hệ lại", summary)
        self.assertIn("hỏi ông xã", summary)
        self.assertNotIn("25 m²", summary)
        self.assertNotIn("Alo", summary)
        self.assertNotIn("Để tôi hỏi", summary)

    def test_summary_uses_verified_state_when_dialogue_exceeds_budget(self):
        turns = [{"customer_text": "Earlier request"},
                 {"customer_text": "Latest decision " + "x" * 200}]
        state = {"topics": [{"next_step": "Khách sẽ gọi lại", "items": []}]}
        summary = build_episode_summary([], turns, 80, episode_state=state)
        self.assertIn("Khách sẽ gọi lại", summary)
        self.assertNotIn("Earlier request", summary)
        self.assertNotIn("Latest decision", summary)
        self.assertLessEqual(len(summary), 80)

    def test_repeated_utterance_is_not_copied_into_summary(self):
        turns = [{"customer_text": "Tôi chưa quyết định"},
                 {"customer_text": "Hỏi mẫu khác"},
                 {"customer_text": "Cần tư vấn thêm"},
                 {"customer_text": "Tôi chưa quyết định"}]
        summary = build_episode_summary([], turns, 70)
        self.assertNotIn("Tôi chưa quyết định", summary)
        self.assertIn("Chưa có diễn biến", summary)

    def test_long_summary_keeps_latest_open_issue(self):
        turns = [{"customer_text": f"Tôi hỏi mẫu {index}", "agent_text": "Dạ"}
                 for index in range(30)]
        turns.append({"customer_text": "Cuối cùng tôi cần hỏi người thân trước",
                      "agent_text": "Dạ em sẽ gọi lại"})
        state = {"topics": [{"scope_type": "unknown", "scope_id": "", "items": [
            {"kind": "blocker", "text": "Cần hỏi người thân trước", "status": "open"}]}]}
        summary = build_episode_summary([], turns, 180, episode_state=state)
        self.assertIn("Cần hỏi người thân trước", summary)
        self.assertNotIn("Tôi hỏi mẫu 0", summary)
        self.assertLessEqual(len(summary), 180)

    def test_open_then_resolve_question_with_current_turn_evidence(self):
        first = str(uuid4())
        opened = apply_episode_delta({}, {"topic_updates": [{
            "scope_type": "product", "scope_id": "SKU-GAMMA",
            "add_items": [{"kind": "question", "text": "Có giao cuối tuần không?",
                           "evidence_quote": "Có giao cuối tuần không?"}],
        }]}, source_turn_id=first,
            customer_text="Có giao cuối tuần không?", agent_text="Em sẽ kiểm tra.")
        item = opened["topics"][0]["items"][0]
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["source_turn_id"], first)
        second = str(uuid4())
        resolved = apply_episode_delta(opened, {"topic_updates": [{
            "scope_type": "product", "scope_id": "SKU-GAMMA",
            "resolve_items": [{"item_id": item["item_id"],
                               "evidence_quote": "Có giao cuối tuần ạ."}],
        }]}, source_turn_id=second,
            customer_text="Vâng", agent_text="Có giao cuối tuần ạ.")
        updated = resolved["topics"][0]["items"][0]
        self.assertEqual(updated["status"], "resolved")
        self.assertEqual(updated["source_turn_id"], first)
        self.assertEqual(updated["resolved_turn_id"], second)

    def test_forged_evidence_rejected(self):
        with self.assertRaises(ValueError):
            apply_episode_delta({}, {"topic_updates": [{
                "scope_type": "unknown", "scope_id": "",
                "add_items": [{"kind": "blocker", "text": "Cần hỏi chồng",
                               "evidence_quote": "Cần hỏi chồng"}],
            }]}, source_turn_id=str(uuid4()), customer_text="Tôi đồng ý mua",
                agent_text="Dạ vâng")

    def test_unrelated_quote_cannot_support_blocker(self):
        with self.assertRaises(ValueError):
            apply_episode_delta({}, {"topic_updates": [{
                "scope_type": "unknown", "scope_id": "",
                "add_items": [{"kind": "blocker", "text": "Customer cannot afford it",
                               "evidence_quote": "Yes, I want to purchase it."}],
            }]}, source_turn_id=str(uuid4()),
                customer_text="Yes, I want to purchase it.", agent_text="Okay")

    def test_agent_words_cannot_become_customer_blocker(self):
        with self.assertRaises(ValueError):
            apply_episode_delta({}, {"topic_updates": [{
                "scope_type": "unknown", "scope_id": "",
                "add_items": [{"kind": "blocker", "text": "Cần hỏi người thân",
                               "evidence_quote": "Cần hỏi người thân"}],
            }]}, source_turn_id=str(uuid4()), customer_text="Tôi đồng ý mua",
                agent_text="Cần hỏi người thân không ạ?")

    def test_narrative_requires_current_turn_evidence(self):
        with self.assertRaises(ValueError):
            apply_episode_delta({}, {"topic_updates": [{
                "scope_type": "unknown", "scope_id": "",
                "next_step": "Gọi khách tuần sau"}]},
                source_turn_id=str(uuid4()), customer_text="Tôi cần xem thêm",
                agent_text="Dạ")

    def test_resolution_of_prior_session_item_is_recorded_by_id(self):
        state = apply_episode_delta({}, {"topic_updates": [{
            "scope_type": "unknown", "scope_id": "",
            "resolve_items": [{"item_id": "old-question-1",
                               "evidence_quote": "Có giao cuối tuần ạ."}]}]},
            source_turn_id=str(uuid4()), customer_text="Vâng",
            agent_text="Có giao cuối tuần ạ.",
            prior_open_items={"old-question-1": ("unknown", "")})
        self.assertEqual(state["resolved_prior_items"][0]["item_id"], "old-question-1")


class PriorItemQueryTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_episode_update_preserves_existing_write_payload(self):
        class Gateway:
            def __init__(self):
                self.args = None

            async def invoke(self, _name, args):
                self.args = args
                return {"turn_no": 1, "memory_writes": []}

        gateway = Gateway()
        store = MCPMemoryStore(gateway)
        await store.commit_turn(str(uuid4()), "C01", "Xin chào", "Dạ",
                                "2026-10-15", "hotline", str(uuid4()), [])
        self.assertNotIn("episode_delta", gateway.args["data"])
        self.assertNotIn("outcome", gateway.args["data"])

    async def test_seeded_episode_still_owns_session(self):
        class Connection:
            async def fetchval(self, query, *_):
                return "C01" if "ai_memory.episodes" in query else None

        repo = MemoryRepo("postgresql://localhost/test")
        self.assertEqual(await repo.owner(Connection(), str(uuid4())), "C01")

    async def test_decodes_jsonb_and_filters_resolved_prior_ids(self):
        class Connection:
            async def fetch(self, *_):
                return [
                    {"topics": json.dumps([{"scope_type": "product",
                        "scope_id": "SKU-GAMMA", "items": [
                            {"item_id": "q-1", "kind": "question", "status": "open"},
                            {"item_id": "q-2", "kind": "question", "status": "open"}]}]),
                     "resolved_prior_items": "[]"},
                    {"topics": "[]", "resolved_prior_items": '[{"item_id":"q-1"}]'},
                ]

        repo = MemoryRepo("postgresql://localhost/test")
        items = await repo.prior_open_items(Connection(), "C01", str(uuid4()))
        self.assertEqual(items, {"q-2": ("product", "SKU-GAMMA")})
