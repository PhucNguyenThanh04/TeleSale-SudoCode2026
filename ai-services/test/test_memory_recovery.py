"""Regression coverage for session memory and recoverable read failures."""
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4
from langchain_core.messages import AIMessage
from app.agent.harness.context import load_context
from app.agent.harness.agent_nodes import MEMORY_UNAVAILABLE
from app.agent.harness.runtime import AgentHarnessRuntime
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


class MemoryRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_memory_errors_skip_model_without_handoff_promise(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                memory = FakeMemory()
                memory.read_context = AsyncMock(return_value={"error": "tool_unavailable"})
                if raises:
                    memory.read_context.side_effect = RuntimeError("private details")
                model = FakeToolModel(replies=[])
                runtime = AgentHarnessRuntime(model, FakeGateway(), memory, guardrails_enabled=False)
                request = turn("Xin chào")
                with self.assertLogs("app.agent", level="WARNING") as logs:
                    response = await runtime.run(request)
                self.assertEqual(response.agent_text, MEMORY_UNAVAILABLE)
                self.assertFalse(response.needs_handoff)
                self.assertEqual(model.seen, [])
                self.assertNotIn("private details", str(logs.output))
                self.assertEqual(runtime.state_for(request)["memory_failure"], "memory.read")

    async def test_commit_failure_is_not_success(self):
        memory = FakeMemory()
        memory.commit_turn = AsyncMock(return_value={"error": "tool_unavailable"})
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Xin chào")]), FakeGateway(), memory)
        with self.assertRaisesRegex(RuntimeError, "memory_turn_write_failed"):
            await runtime.run(turn("Xin chào"))

    async def test_episodes_deduplicated_and_bounded(self):
        memory = FakeMemory()
        memory.max_episodes = 2
        memory.read_context = AsyncMock(return_value={"history": [], "profile": {}, "episodes": [
            {"session_id": "old", "on": "2026-10-14", "summary": "memory", "channel": "hotline"}]})
        state = {"request": turn("Tiếp tục"), "customer_id": "C001", "crm_sessions": [
            {"session_id": "old", "date": "2026-10-14", "summary": "crm", "channel": "hotline"},
            {"session_id": "older", "date": "2026-10-13", "summary": "older", "channel": "hotline"},
            {"session_id": "oldest", "date": "2026-10-12", "summary": "oldest", "channel": "hotline"}]}
        result = await load_context(state, memory, FakeGateway(), lambda: None)
        self.assertEqual([e["summary"] for e in result["episodes"]], ["memory", "older"])
        memory.include_prior = False
        self.assertEqual((await load_context(state, memory, FakeGateway(), lambda: None))["episodes"], [])

    async def test_returning_product_refresh_uses_request_date(self):
        memory = FakeMemory()
        memory.read_context = AsyncMock(return_value={"history": [], "profile": {
            "product_advised": {"value": "SKU-AP-X"},
            "price_quoted_vnd": {"value": 4890000}}, "episodes": [
            {"session_id": "previous", "on": "2026-10-15", "summary": "AirPure X", "channel": "hotline"}]})
        request = turn("Giá còn như cũ không?")
        from datetime import date
        request = request.model_copy(update={"on": date(2026, 10, 22)})
        gateway = FakeGateway()
        result = await load_context({"request": request, "customer_id": "C001"},
                                    memory, gateway, lambda: None)
        self.assertEqual([name for name, _ in gateway.calls], ["inventory.check", "pricing.get_quote"])
        self.assertTrue(all(args["on"] == "2026-10-22" for _, args in gateway.calls))
        self.assertEqual(len(result["tool_calls"]), 2)

    async def test_runtime_restart_reads_session_history(self):
        memory = FakeMemory()
        session = uuid4()
        first = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Đã ghi nhận")]), FakeGateway(), memory)
        await first.run(turn("Phòng 25 m²", session))
        model = FakeToolModel(replies=[AIMessage(content="Mình tiếp tục nhé")])
        await AgentHarnessRuntime(model, FakeGateway(), memory).run(turn("Tiếp tục", session))
        self.assertIn("Phòng 25 m²", model.seen[0])
