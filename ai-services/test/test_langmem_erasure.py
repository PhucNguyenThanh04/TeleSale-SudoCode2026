"""Customer erasure spans canonical and projected memory."""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.erasure_executor import execute_erasure
from app.mcp_servers.mcp_memory.distiller_worker import process_one


class Repo:
    def __init__(self):
        self.results = {}

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def erasure_request(self, _conn, _key, for_update=False):
        return {"customer_id": "C1", "scope": ["ai_memory"], "status": "pending",
                "store_results": self.results}

    async def lock_key(self, *_):
        pass

    async def purge_customer_memory(self, *_):
        return {"status": "completed", "deleted_rows": {"turns": 1}}

    async def finish_erasure_request(self, _conn, _key, status, results):
        self.results = results


class ErasureTests(unittest.IsolatedAsyncioTestCase):
    async def test_inflight_worker_cannot_recreate_erased_customer(self):
        worker_repo = MagicMock()
        @asynccontextmanager
        async def transaction():
            yield object()
        worker_repo.transaction = transaction
        worker_repo.claim_distillation = AsyncMock(return_value={
            "job_id": 1, "session_id": str(uuid4()), "source_turn_id": str(uuid4()),
            "customer_id": "C1", "mode": "enabled", "attempts": 1})
        worker_repo.distillation_turn = AsyncMock(return_value={
            "customer_text": "Tôi thích màu xanh", "agent_text": "Dạ",
            "on_date": "2026-10-15", "channel": "hotline"})
        worker_repo.lock_key = AsyncMock()
        worker_repo.is_erasure_blocked = AsyncMock(return_value=True)
        worker_repo.save_distillation_proposals = AsyncMock()
        worker_repo.finish_distillation = AsyncMock()
        projector = AsyncMock()
        self.assertTrue(await process_one(worker_repo,
            AsyncMock(return_value=([], None)), projector))
        projector.put_episode.assert_not_awaited()
        worker_repo.finish_distillation.assert_awaited_once()
        self.assertEqual(worker_repo.finish_distillation.await_args.args[3],
                         "erasure_blocked")

    async def test_projection_failure_is_partial_then_retry_completes(self):
        repo = Repo()
        projector = AsyncMock()
        projector.delete_customer.side_effect = [OSError("offline"), 1]
        key = str(uuid4())
        first = await execute_erasure(repo, key, projector)
        self.assertEqual(first["status"], "partial")
        self.assertEqual(first["store_results"]["langmem_store"]["status"], "pending")
        second = await execute_erasure(repo, key, projector)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["store_results"]["langmem_store"]["deleted_rows"], 1)
