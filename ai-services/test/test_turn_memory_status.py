"""Only committed worker results may be displayed as remembered facts."""

import unittest
from contextlib import asynccontextmanager
from uuid import uuid4


class StatusRepo:
    def __init__(self):
        self.customer = "C1"
        self.blocked = False
        self.row = {"customer_id": "C1", "status": "pending",
                    "error_code": None, "accepted_writes": []}

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def lock_key(self, *_):
        pass

    async def is_erasure_blocked(self, *_):
        return self.blocked

    async def owner(self, *_):
        return self.customer

    async def turn_memory_status(self, *_):
        return self.row


class TurnMemoryStatusTest(unittest.IsolatedAsyncioTestCase):
    async def lookup(self, repo, customer="C1"):
        from app.mcp_servers.mcp_memory.services.turn_status import read_turn_status
        return await read_turn_status(repo, customer, str(uuid4()), str(uuid4()))

    async def test_pending_job_never_exposes_proposals_or_partial_writes(self):
        repo = StatusRepo()
        repo.row["accepted_writes"] = [{"key": "room_area_m2", "value": 25, "op": "set"}]
        for state in ("pending", "leased", "failed"):
            repo.row["status"] = state
            result = await self.lookup(repo)
            self.assertTrue(result["turn_saved"])
            self.assertEqual(result["status"], "failed" if state == "failed" else "pending")
            self.assertEqual(result["changes"], [])

    async def test_completed_changes_are_masked_scoped_and_whitelisted(self):
        repo = StatusRepo()
        repo.row.update(status="completed", accepted_writes=[
            {"key": "room_area_m2", "value": 25, "op": "set", "customer_id": "private",
             "evidence_quote": "Tôi ở 12 Phố Kiểm Thử", "scope_type": "room", "scope_id": "room_a"},
            {"key": "budget_vnd", "value": 6000000, "op": "supersede"},
            {"key": "preferred_color", "op": "delete"},
            {"key": "blocker", "value": "Gọi 0901234567", "op": "set"},
            {"key": "phone", "value": "0901234567", "op": "set"},
            {"key": "room_area_m2", "value": {"phone": "0901234567"}, "op": "set"},
        ])
        result = await self.lookup(repo)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["changes"]), 4)
        self.assertEqual(result["changes"][0], {"field": "room_area_m2", "action": "added",
            "value": 25, "source": "customer", "scope_type": "room", "scope_id": "room_a"})
        self.assertEqual(result["changes"][1]["action"], "updated")
        self.assertEqual(result["changes"][2]["action"], "deleted")
        self.assertNotIn("0901234567", str(result))
        self.assertNotIn("evidence_quote", str(result))
        self.assertNotIn("private", str(result))

    async def test_erasure_wrong_owner_or_wrong_turn_never_exposes_changes(self):
        repo = StatusRepo()
        repo.blocked = True
        self.assertEqual((await self.lookup(repo))["error"], "customer_erasure_in_progress")
        repo.blocked = False
        self.assertEqual((await self.lookup(repo, "other"))["error"], "session_owner_mismatch")
        repo.row["customer_id"] = "other"
        self.assertEqual((await self.lookup(repo))["error"], "session_owner_mismatch")

    async def test_missing_turn_anonymous_and_completed_empty_are_distinct(self):
        repo = StatusRepo()
        repo.row = None
        self.assertEqual(await self.lookup(repo),
            {"turn_saved": False, "status": "unavailable", "changes": []})
        repo.customer = None
        repo.row = {"customer_id": None, "status": None}
        self.assertEqual((await self.lookup(repo, None))["status"], "not_applicable")
        repo.customer = "C1"
        repo.row = {"customer_id": "C1", "status": "completed", "accepted_writes": []}
        self.assertEqual(await self.lookup(repo),
            {"turn_saved": True, "status": "completed", "changes": []})
