
import unittest
from contextlib import asynccontextmanager
from uuid import uuid4

from pydantic import ValidationError

from app.mcp_servers.mcp_memory.services.memory import read, write
from app.mcp_servers.mcp_memory.schemas import WriteInput


class FakeRepo:
    def __init__(self):
        self.active = None
        self.statuses = []
        self.facts = []
        self.operations = {}

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def claim_operation(self, _conn, key, digest):
        old = self.operations.get(key)
        if old and old[0] != digest:
            return {"error": "operation_key_conflict"}
        return old[1] if old else None

    async def finish_operation(self, _conn, key, result):
        self.operations[key] = (self.digest, result)

    async def lock_key(self, *_):
        pass

    async def active_fact(self, *_):
        return self.active

    async def set_fact_status(self, _conn, fact_id, status):
        self.statuses.append((fact_id, status))

    async def insert_fact(self, _conn, fact_id, customer_id, key, value, source, session_id, previous):
        self.facts.append((fact_id, previous))
        self.active = fact_id


class TurnRepo(FakeRepo):
    def __init__(self):
        super().__init__()
        self.rows = {}
        self.episode_summaries = {}

    async def claim_operation(self, conn, key, digest):
        self.digest = digest
        return await super().claim_operation(conn, key, digest)

    async def owner(self, _conn, session_id):
        rows = self.rows.get(session_id, [])
        return next((row["customer_id"] for row in rows
                     if row["customer_id"] is not None), None)

    async def next_turn(self, _conn, session_id):
        return len(self.rows.get(session_id, [])) + 1

    async def insert_turn(self, _conn, session_id, number, customer_id,
                          channel, on, customer_text, agent_text,
                          client_msg_id=None, tool_observations=None, outcome="khac"):
        self.rows.setdefault(session_id, []).append({
            "turn_no": number, "customer_id": customer_id,
            "customer_text": customer_text, "agent_text": agent_text,
            "client_msg_id": client_msg_id, "tool_observations":tool_observations or [],
            "verified_outcome":outcome,
        })

    async def attribute_anonymous_turns(self, _conn, session_id, customer_id):
        attributed = []
        for row in self.rows.get(session_id, []):
            if row["customer_id"] is None:
                row["customer_id"] = customer_id
                row["attributed_after_verification"] = True
                attributed.append({"turn_no": row["turn_no"],
                                   "source_turn_id": row["client_msg_id"],
                                   "tool_observations":row["tool_observations"],
                                   "verified_outcome":row["verified_outcome"]})
        return attributed

    async def turns(self, _conn, session_id):
        return self.rows.get(session_id, [])

    async def customer_turns(self, _conn, session_id, customer_id):
        return [row for row in self.rows.get(session_id, [])
                if row["customer_id"] == customer_id]

    async def recent_customer_turns(self, _conn, session_id, customer_id, maximum):
        return (await self.customer_turns(_conn, session_id, customer_id))[-maximum:]

    async def recent_turns(self, _conn, session_id, maximum):
        return self.rows.get(session_id, [])[-maximum:]

    async def turn_count(self, _conn, session_id):
        return len(self.rows.get(session_id, []))

    async def upsert_episode(self, _conn, session_id, _customer_id,
                             _channel, _on, summary, _outcome):
        self.episode_summaries[session_id] = summary


class MemoryServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_commit_stores_turn_and_queues_distillation_once(self):
        from unittest.mock import AsyncMock
        repo = TurnRepo()
        repo.enqueue_distillation = AsyncMock()
        repo.link_order = AsyncMock()
        session_id, turn_id = str(uuid4()), str(uuid4())
        data = {"customer_text": "Tôi thích màu xanh", "agent_text": "Dạ",
                "on": "2026-10-15", "channel": "hotline", "client_msg_id": turn_id}
        first = await write(repo, "commit_turn", "C001", session_id, data, "op-1")
        replay = await write(repo, "commit_turn", "C001", session_id, data, "op-1")
        self.assertEqual(first, {"turn_no": 1, "memory_writes": []})
        self.assertEqual(replay, first)
        self.assertEqual(len(repo.rows[session_id]), 1)
        repo.enqueue_distillation.assert_awaited_once()

    async def test_anonymous_session_history_is_immediate(self):
        repo = TurnRepo()
        session_id = str(uuid4())
        turn_id = str(uuid4())
        result = await write(repo, "commit_turn", None, session_id, {
            "customer_text": "Xin chào", "agent_text": "Dạ chào anh/chị",
            "on": "2026-10-15", "channel": "hotline",
            "client_msg_id": turn_id})
        self.assertEqual(result["turn_no"], 1)
        remembered = await read(repo, None, session_id)
        self.assertEqual(remembered["history"],
                         [{"customer": "Xin chào", "agent": "Dạ chào anh/chị",
                           "source_turn_id": turn_id}])

    async def test_verified_customer_keeps_earlier_anonymous_turn_in_same_session(self):
        from unittest.mock import AsyncMock

        repo = TurnRepo()
        repo.enqueue_distillation = AsyncMock()
        repo.link_order = AsyncMock()
        repo.order_links = AsyncMock(return_value=[])
        session_id = str(uuid4())
        for customer_id, text in ((None, "Tôi muốn size 39"),
                                  ("C001", "Tôi là khách đã xác minh")):
            result = await write(repo, "commit_turn", customer_id, session_id, {
                "customer_text": text, "agent_text": "Dạ", "on": "2026-10-15",
                "channel": "hotline", "client_msg_id": str(uuid4())})
            self.assertEqual(result["turn_no"], len(repo.rows[session_id]))

        class Projection:
            async def list_fact_versions(self, _customer_id):
                return []

            async def list_episode_versions(self, _customer_id):
                return []

        context = await read(repo, "C001", session_id, projector=Projection())
        self.assertEqual(len(context["history"]), 2)
        self.assertEqual(context["history"][0]["customer"], "Tôi muốn size 39")

    async def test_late_verification_queues_prior_anonymous_turns_once(self):
        from unittest.mock import AsyncMock

        repo = TurnRepo()
        repo.enqueue_distillation = AsyncMock()
        repo.link_order = AsyncMock()
        session_id = str(uuid4())
        for customer_id, text in ((None, "Size 39"), (None, "Màu đen"),
                                  ("C001", "Tôi xác nhận danh tính")):
            await write(repo, "commit_turn", customer_id, session_id, {
                "customer_text": text, "agent_text": "Dạ", "on": "2026-10-15",
                "channel": "hotline", "client_msg_id": str(uuid4())})
        self.assertEqual([row["customer_id"] for row in repo.rows[session_id]],
                         ["C001", "C001", "C001"])
        self.assertEqual([row.get("attributed_after_verification")
                          for row in repo.rows[session_id]], [True, True, None])
        self.assertEqual(repo.enqueue_distillation.await_count, 3)

    async def test_old_actions_and_proposals_are_unavailable(self):
        repo = TurnRepo()
        session_id = str(uuid4())
        self.assertEqual(await write(repo, "fact", "C001", session_id,
                                     {"key": "color", "value": "xanh"}),
                         {"error": "unknown_memory_action"})
        self.assertEqual(await write(repo, "commit_turn", "C001", session_id, {
            "customer_text": "Xin chào", "agent_text": "Dạ", "on": "2026-10-15",
            "channel": "hotline", "client_msg_id": str(uuid4()), "facts": []}),
            {"error": "legacy_memory_action_disabled"})
        with self.assertRaises(ValidationError):
            WriteInput(action="fact", customer_id="C001", session_id=uuid4(),
                       data={"key": "color", "value": "xanh"})
