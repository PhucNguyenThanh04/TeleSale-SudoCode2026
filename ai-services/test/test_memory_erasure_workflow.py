"""Verified requests block reads and writes before any physical purge."""

import unittest
from contextlib import asynccontextmanager
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.erasure import request_erasure
from app.mcp_servers.mcp_memory.services.memory import read, write
from app.agent.harness.runtime import DeepHarnessRuntime
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


class Repo:
    def __init__(self):
        self.requests = {}
        self.blocked = set()
        self.write_count = 0

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def lock_key(self, *_):
        pass

    async def create_erasure_request(self, _conn, request_key, customer_id,
                                     verification_ref, verified_by, scope):
        previous = self.requests.get(request_key)
        if previous:
            return previous if previous["customer_id"] == customer_id else {"error": "request_key_conflict"}
        result = {"request_key": request_key, "customer_id": customer_id,
                  "status": "pending", "scope": scope}
        self.requests[request_key] = result
        self.blocked.add(customer_id)
        return result

    async def is_erasure_blocked(self, _conn, customer_id):
        return customer_id in self.blocked

    async def owner(self, *_):
        return None

    async def recent_customer_turns(self, *_):
        return []

    async def turn_count(self, *_):
        return 0

    async def facts(self, *_):
        return []

    async def episodes(self, *_):
        return []

    async def order_links(self, *_):
        return []

    async def next_turn(self, *_):
        return 1

    async def insert_turn(self, *_):
        self.write_count += 1


class ErasureWorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_memory_still_routes_erasure_request_without_rewriting(self):
        class BlockedMemory(FakeMemory):
            async def read_context(self, _session_id, _customer_id):
                return {"error": "customer_erasure_in_progress"}

            async def commit_turn(self, *_args, **_kwargs):
                raise AssertionError("blocked customer must not be persisted")

        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": True, "customer_id": "C901", "phone": "0900000901",
                            "orders": [], "sessions": []}
                if name == "handoff.transfer":
                    return {"status": "queued", "ticket_id": "case-901"}
                return {"error": "unavailable"}

        gateway = Gateway()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), gateway, BlockedMemory())
        request = turn("Xin xóa hồ sơ cá nhân của tôi.").model_copy(update={
            "channel_identity": "0900000901", "verified_customer_id": "C901",
            "verified_phone": "0900000901"})
        response = await runtime.run(request)
        self.assertTrue(response.needs_handoff)
        self.assertEqual(response.handoff_ticket_id, "case-901")
        self.assertIn("handoff.transfer", [name for name, _ in gateway.calls])

    async def test_request_requires_verification_and_is_idempotent(self):
        repo = Repo()
        key = str(uuid4())
        missing = await request_erasure(repo, customer_id="C901", request_key=key,
            verification_ref="", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(missing, {"error": "verification_required"})
        self.assertEqual(repo.requests, {})
        created = await request_erasure(repo, customer_id="C901", request_key=key,
            verification_ref="case-42", verified_by="operator-1", scope=["ai_memory"])
        repeated = await request_erasure(repo, customer_id="C901", request_key=key,
            verification_ref="case-42", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(repeated, created)
        conflict = await request_erasure(repo, customer_id="C902", request_key=key,
            verification_ref="case-43", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(conflict, {"error": "request_key_conflict"})

    async def test_customer_barrier_does_not_block_other_shared_phone_owner(self):
        repo = Repo()
        session = str(uuid4())
        await request_erasure(repo, customer_id="C901", request_key=str(uuid4()),
            verification_ref="case-42", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(await read(repo, "C901", session),
                         {"error": "customer_erasure_in_progress"})
        other = await read(repo, "C902", session)
        self.assertEqual(other["profile"], {})
        blocked = await write(repo, "turn", "C901", session, {
            "customer_text": "Xin chào", "agent_text": "Dạ", "on": "2026-10-15",
            "channel": "hotline"})
        self.assertEqual(blocked, {"error": "customer_erasure_in_progress"})
        self.assertEqual(repo.write_count, 0)
