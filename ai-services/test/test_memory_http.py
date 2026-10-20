"""Opt-in tests: point MEMORY_TEST_URL at an isolated MCP memory database."""
import os
import unittest
from uuid import uuid4
from app.agent.mcp.gateway import MCPGateway
from app.agent.memory.store import MCPMemoryStore


@unittest.skipUnless(os.environ.get("MEMORY_TEST_URL"), "requires isolated MCP HTTP server")
class MemoryHTTPTest(unittest.IsolatedAsyncioTestCase):
    async def test_history_supersession_and_isolation(self):
        gateway = MCPGateway(None, None, os.environ["MEMORY_TEST_URL"],
                             os.environ["MEMORY_TEST_TOKEN"])
        memory = MCPMemoryStore(gateway, namespace="test-" + uuid4().hex)
        session, later, message = [str(uuid4()) for _ in range(3)]
        fact = {"key": "room_area_m2", "value": 25, "op": "set", "source_kind": "customer"}
        result = await memory.commit_turn(session, "customer", "Phòng 25 m²", "Đã ghi nhận",
                                          "2026-10-15", "hotline", message, [fact])
        self.assertEqual(result["memory_writes"][0]["value"], 25)
        self.assertEqual(await memory.commit_turn(session, "customer", "Phòng 25 m²",
                         "Đã ghi nhận", "2026-10-15", "hotline", message, [fact]), result)
        # New adapter models a restarted process; all state comes from MCP.
        restarted = MCPMemoryStore(gateway, namespace=memory.namespace)
        same = await restarted.read_context(session, "customer")
        self.assertEqual(same["history"][0]["customer"], "Phòng 25 m²")
        cross = await restarted.read_context(later, "customer")
        self.assertEqual(cross["profile"]["room_area_m2"]["value"], 25)
        self.assertEqual((await restarted.read_context(later, "different"))["profile"], {})
        self.assertEqual((await restarted.read_context(session, "different"))["error"], "session_owner_mismatch")
        restarted.include_prior = False
        self.assertEqual((await restarted.read_context(later, "customer"))["profile"], {})
        self.assertEqual(len((await restarted.read_context(session, "customer"))["history"]), 1)
        restarted.include_prior = True
        newer = str(uuid4())
        args = (later, "customer", "Phòng 30 m²", "Đã cập nhật", "2026-10-17", "zalo_oa", newer,
                [{**fact, "value": 30}])
        updated = await restarted.commit_turn(*args)
        self.assertEqual(updated["memory_writes"][0]["op"], "supersede")
        self.assertEqual(await restarted.commit_turn(*args), updated)
        for index in range(13):
            await restarted.commit_turn(later, "customer", f"Lượt {index}", "Đã ghi nhận",
                                        "2026-10-17", "zalo_oa", str(uuid4()), [])
        context = await restarted.read_context(later, "customer")
        self.assertEqual(context["turn_count"], 14)
        self.assertEqual(len(context["history"]), 12)
        self.assertEqual(context["history"][-1]["customer"], "Lượt 12")
        self.assertEqual(context["profile"]["room_area_m2"]["value"], 30)
