"""The enabled path uses LangGraph store for durable customer knowledge."""

import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.memory import read, write
from app.mcp_servers.mcp_memory.distiller_worker import process_one
from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_memory.services.memory import _valid_scope
from types import SimpleNamespace
from datetime import date, datetime, timezone
from test_mcp_memory import TurnRepo


class PrimaryMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_long_term_actions_are_rejected_in_primary_mode(self):
        self.assertEqual(await write(None, "fact", "C1", str(uuid4()),
            {"key": "preferred_color", "op": "set", "value": "xanh",
             "source": "customer"}, langmem_mode="enabled"),
            {"error": "legacy_memory_action_disabled"})
        self.assertEqual(await write(None, "seed_episode", "C1", str(uuid4()),
            {"on": "2026-10-15", "summary": "hỏi máy lọc"},
            langmem_mode="enabled"),
            {"error": "legacy_memory_action_disabled"})
        self.assertEqual(await write(None, "commit_turn", "C1", str(uuid4()),
            {"client_msg_id": str(uuid4()), "customer_text": "Tôi thích màu xanh",
             "agent_text": "Dạ", "channel": "hotline", "on": "2026-10-15",
             "facts": [{"key": "preferred_color", "value": "xanh", "op": "set",
                        "source_kind": "customer", "evidence_quote": "màu xanh"}]},
            langmem_mode="enabled"),
            {"error": "legacy_memory_action_disabled"})

    def test_phone_cannot_be_used_as_fact_scope(self):
        self.assertFalse(_valid_scope({"key": "product_advised",
                                       "scope_type": "product", "scope_id": "0912345678"}))

    def test_primary_business_tools_hide_old_fact_proposals(self):
        tools = BusinessTools(None, {"langmem_primary": True}, 10,
                              lambda: datetime.now(timezone.utc)).langchain_tools()
        self.assertNotIn("memory.propose_fact", [tool.name for tool in tools])
        for tool in tools:
            self.assertNotIn("fact_candidates", tool.args_schema.model_fields)

    async def test_agent_commits_turn_without_legacy_proposals(self):
        memory = AsyncMock()
        memory.langmem_primary = True
        memory.supports_tool_observations = True
        memory.commit_turn.return_value = {"turn_no": 1, "memory_writes": []}
        nodes = AgentNodes(None, None, memory, 10, 5,
                           lambda: datetime.now(timezone.utc))
        request = SimpleNamespace(session_id=uuid4(), client_msg_id=uuid4(),
                                  on=date(2026, 10, 15), channel="hotline")
        from unittest.mock import patch
        with patch("app.agent.harness.agent_nodes.accepted_candidates",
                   side_effect=AssertionError("legacy extraction used")):
            result = await nodes.persist_agent({"request": request,
                "safe_text": "Tôi thích màu xanh", "agent_text": "Dạ",
                "customer_id": "C1", "tool_calls": []})
        self.assertEqual(result, {"memory_writes": []})
        self.assertEqual(memory.commit_turn.await_args.args[7], [])

    async def test_read_uses_store_without_legacy_fact_or_episode_queries(self):
        class Repo(TurnRepo):
            async def facts(self, *_):
                raise AssertionError("legacy facts queried")

            async def episodes(self, *_):
                raise AssertionError("legacy episodes queried")

            async def episode_state(self, *_):
                raise AssertionError("legacy episode state queried")

            async def order_links(self, *_):
                return []

        repo = Repo()
        projection = AsyncMock()
        projection.list_fact_versions.return_value = [{"key": "preferred_color", "value": "xanh",
            "scope_type": "global", "scope_id": "", "source_kind": "customer",
            "source_turn_id": str(uuid4()), "session_id": str(uuid4()),
            "on": "2026-10-15", "schema_version": 1}]
        projection.list_episode_versions.return_value = []
        result = await read(repo, "C1", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(result["profile"]["preferred_color"]["value"], "xanh")
        projection.list_fact_versions.assert_awaited_once_with("C1")

    async def test_store_outage_fails_closed(self):
        projection = AsyncMock()
        projection.list_fact_versions.side_effect = OSError("unavailable")
        class Repo(TurnRepo):
            async def order_links(self, *_):
                return []
        result = await read(Repo(), "C1", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(result, {"error": "memory_store_unavailable"})

    async def test_commit_does_not_write_legacy_facts_or_episodes(self):
        repo = AsyncMock()
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        repo.owner.return_value = None
        repo.next_turn.return_value = 1
        repo.claim_operation.return_value = None
        repo.is_erasure_blocked.return_value = False
        session, turn = str(uuid4()), str(uuid4())
        result = await write(repo, "commit_turn", "C1", session,
            {"client_msg_id": turn, "customer_text": "Tôi thích màu xanh",
             "agent_text": "Dạ", "channel": "hotline", "on": "2026-10-15",
             "facts": []}, langmem_mode="enabled")
        self.assertEqual(result, {"turn_no": 1, "memory_writes": []})
        repo.enqueue_distillation.assert_awaited_once()
        repo.insert_fact.assert_not_awaited()
        repo.upsert_episode_state.assert_not_awaited()

    async def test_worker_writes_accepted_knowledge_only_to_store(self):
        from contextlib import asynccontextmanager
        repo = AsyncMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        session, turn = str(uuid4()), str(uuid4())
        repo.claim_distillation.return_value = {"job_id": 1, "customer_id": "C1",
            "session_id": session, "source_turn_id": turn, "attempts": 1,
            "mode": "enabled", "tool_observations": []}
        repo.distillation_turn.return_value = {"customer_text": "Tôi thích màu xanh",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        projection = AsyncMock()
        projection.list_facts.return_value = []
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = []
        projection.get_episode.return_value = None
        extractor = AsyncMock(return_value=([ProfileFactCandidate(
            key="preferred_color", value="xanh", source_kind="customer",
            source_turn_id=turn, evidence_quote="màu xanh", observed_on="2026-10-15")],
            CustomerCallEpisodeCandidate(customer_id="C1", session_id=session,
                channel="hotline", on="2026-10-15", source_turn_ids=[turn],
                customer_goal="màu xanh")))
        self.assertTrue(await process_one(repo, extractor, projection))
        projection.put_facts.assert_awaited_once()
        projection.put_episode.assert_awaited_once()
        repo.insert_fact.assert_not_awaited()
        repo.upsert_episode_state.assert_not_awaited()
        self.assertEqual(repo.finish_distillation.await_args.args[2], "completed")

    async def test_fact_only_turn_creates_evidenced_call_episode(self):
        from contextlib import asynccontextmanager
        repo = AsyncMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        session, turn = str(uuid4()), str(uuid4())
        repo.claim_distillation.return_value = {"job_id": 1, "customer_id": "C1",
            "session_id": session, "source_turn_id": turn, "attempts": 1,
            "mode": "enabled", "tool_observations": []}
        repo.distillation_turn.return_value = {"customer_text": "Phòng tôi 25 m²",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        projection = AsyncMock()
        projection.list_facts.return_value = []
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = []
        projection.get_episode.return_value = None
        extractor = AsyncMock(return_value=([ProfileFactCandidate(
            key="room_area_m2", value=25, source_kind="customer",
            source_turn_id=turn, evidence_quote="Phòng tôi 25 m²",
            observed_on="2026-10-15")], None))
        self.assertTrue(await process_one(repo, extractor, projection))
        projection.put_episode.assert_awaited_once()
        self.assertIn("Phòng tôi 25 m²", projection.put_episode.await_args.args[2]["summary"])

    async def test_episode_blocker_is_also_admitted_as_profile_fact(self):
        from contextlib import asynccontextmanager
        repo = AsyncMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        session, turn = str(uuid4()), str(uuid4())
        repo.claim_distillation.return_value = {"job_id": 1, "customer_id": "C1",
            "session_id": session, "source_turn_id": turn, "attempts": 1,
            "mode": "enabled", "tool_observations": []}
        repo.distillation_turn.return_value = {"customer_text": "Để chị hỏi ông xã rồi gọi lại",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        projection = AsyncMock()
        projection.list_facts.return_value = []
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = []
        projection.get_episode.return_value = None
        extractor = AsyncMock(return_value=([], CustomerCallEpisodeCandidate(
            customer_id="C1", session_id=session, channel="hotline", on="2026-10-15",
            source_turn_ids=[turn], open_blockers=["hỏi ông xã"])))
        self.assertTrue(await process_one(repo, extractor, projection))
        self.assertEqual(projection.put_facts.await_args.args[4][0]["key"], "blocker")

    async def test_retry_reuses_admitted_proposals_after_partial_store_write(self):
        from contextlib import asynccontextmanager
        repo = AsyncMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        session, turn = str(uuid4()), str(uuid4())
        job = {"job_id": 5, "customer_id": "C1", "session_id": session,
               "source_turn_id": turn, "attempts": 1, "mode": "enabled",
               "tool_observations": [], "accepted_proposals": None}
        repo.claim_distillation.side_effect = [job, {**job, "attempts": 2,
            "accepted_proposals": {"facts": [{"key": "room_area_m2", "value": 25,
                "op": "set", "source_kind": "customer", "scope_type": "global",
                "scope_id": "", "evidence_quote": "Phòng tôi 25 m²"}],
                "delta": None, "outcome": "khac"}}]
        repo.distillation_turn.return_value = {"customer_text": "Phòng tôi 25 m²",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        projection = AsyncMock()
        projection.list_facts.return_value = []
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = []
        projection.get_episode.return_value = None
        projection.put_facts.return_value = [{"key": "room_area_m2", "value": 25,
                                              "op": "set", "customer_id": "C1"}]
        projection.put_episode.side_effect = [OSError("offline"), None]
        extractor = AsyncMock(return_value=([ProfileFactCandidate(
            key="room_area_m2", value=25, source_kind="customer",
            source_turn_id=turn, evidence_quote="Phòng tôi 25 m²",
            observed_on="2026-10-15")], None))
        self.assertTrue(await process_one(repo, extractor, projection))
        self.assertTrue(await process_one(repo, extractor, projection))
        extractor.assert_awaited_once()
        repo.save_distillation_proposals.assert_awaited_once()
        self.assertEqual(repo.finish_distillation.await_args.kwargs["accepted_writes"][0]["key"],
                         "room_area_m2")

    async def test_verified_order_outcome_creates_episode_without_fact(self):
        from contextlib import asynccontextmanager
        repo = AsyncMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        session, turn = str(uuid4()), str(uuid4())
        repo.claim_distillation.return_value = {"job_id": 8, "customer_id": "C1",
            "session_id": session, "source_turn_id": turn, "attempts": 1,
            "mode": "enabled", "tool_observations": [], "verified_outcome": "chot_don"}
        repo.distillation_turn.return_value = {"customer_text": "Lên đơn giúp tôi",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        projection = AsyncMock()
        projection.list_facts.return_value = []
        projection.list_fact_versions.return_value = []
        projection.list_episode_versions.return_value = []
        projection.get_episode.return_value = None
        extractor = AsyncMock(return_value=([], None))
        self.assertTrue(await process_one(repo, extractor, projection))
        self.assertEqual(projection.put_episode.await_args.args[2]["outcome"], "chot_don")
