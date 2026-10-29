"""Distillation is durable, identity bound, and outside turn response latency."""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.mcp_servers.mcp_memory.distiller_worker import process_one
from app.mcp_servers.mcp_memory.services.memory import write


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def repo(self):
        repo = MagicMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        repo.transaction = transaction
        for name in ("lock_key", "is_erasure_blocked", "owner", "next_turn",
                     "customer_turns", "session_facts", "episode_state",
                     "prior_open_items", "insert_turn", "upsert_episode_state",
                     "enqueue_distillation", "claim_distillation",
                     "distillation_turn", "finish_distillation"):
            setattr(repo, name, AsyncMock())
        return repo

    async def test_commit_queues_once_only_when_opted_in(self):
        repo = self.repo()
        repo.owner.return_value = None
        repo.next_turn.return_value = 1
        repo.customer_turns.return_value = []
        repo.session_facts.return_value = []
        repo.episode_state.return_value = None
        repo.prior_open_items.return_value = {}
        repo.claim_operation.return_value = None
        repo.is_erasure_blocked.return_value = False
        repo.turn_count.return_value = 0
        session, turn = str(uuid4()), str(uuid4())
        data = {"client_msg_id": turn, "customer_text": "Tôi thích màu xanh",
                "agent_text": "Dạ", "channel": "hotline", "on": "2026-10-15",
                "facts": [], "tool_observations": [{"name": "pricing.get_quote",
                    "args": {"sku": "SKU-A"}, "result": {"final_price_vnd": 5000000}}]}
        with patch("app.mcp_servers.mcp_memory.services.memory.build_episode_summary", return_value=""):
            await write(repo, "commit_turn", "C1", session, data,
                        langmem_mode="enabled")
        repo.enqueue_distillation.assert_awaited_once()

    async def test_worker_timeout_does_not_mark_complete(self):
        repo = self.repo()
        repo.claim_distillation.return_value = {"job_id": 1, "customer_id": "C1",
            "session_id": str(uuid4()), "source_turn_id": str(uuid4()), "attempts": 1}
        repo.distillation_turn.return_value = {"customer_text": "Tôi thích màu xanh",
            "agent_text": "Dạ", "on_date": "2026-10-15", "channel": "hotline"}
        repo.is_erasure_blocked.return_value = False
        extractor = AsyncMock(side_effect=TimeoutError())
        self.assertTrue(await process_one(repo, extractor, None))
        repo.finish_distillation.assert_awaited_once()
        self.assertEqual(repo.finish_distillation.await_args.args[2], "pending")
