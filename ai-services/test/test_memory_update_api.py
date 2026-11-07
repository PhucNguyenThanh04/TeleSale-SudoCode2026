"""Chat metadata and asynchronous memory reads with offline dependencies."""

import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage

from app.agent.harness.runtime import AgentHarnessRuntime
from app.agent.memory.store import MCPMemoryStore
from app.api.chat import get_harness
from app.configs import get_settings
from app.main import app
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


class MemoryUpdateApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_reports_pending_without_waiting_for_worker(self):
        request = turn("Alo")
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Dạ, em nghe ạ.")]),
                                      FakeGateway(), memory, agent_kind="react")
        result = await runtime.run(request)
        self.assertEqual(result.memory_update.model_dump(),
            {"turn_saved": True, "status": "pending", "changes": []})
        self.assertEqual(len(memory.turns[str(request.session_id)]), 1)

    async def test_anonymous_chat_is_saved_without_claiming_long_term_memory(self):
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Dạ.")]),
                                      FakeGateway(), FakeMemory(), agent_kind="react")
        result = await runtime.run(turn("Alo").model_copy(update={"channel_identity": None}))
        self.assertTrue(result.memory_update.turn_saved)
        self.assertEqual(result.memory_update.status, "not_applicable")

    async def test_status_is_authenticated_bound_and_uses_actual_mcp_result(self):
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "memory.turn_status":
                    self.calls.append((name, args))
                    return {"turn_saved": True, "status": "completed", "changes": [{
                        "field": "room_area_m2", "action": "added", "value": 25,
                        "source": "customer", "scope_type": "global", "scope_id": ""}]}
                return await super().invoke(name, args)

        gateway = Gateway()
        model = FakeToolModel(replies=[])
        runtime = AgentHarnessRuntime(model, gateway, MCPMemoryStore(gateway))
        request = turn("Alo")
        payload = {key: getattr(request, key) for key in
                   ("session_id", "client_msg_id", "channel", "channel_identity", "on")}
        payload = {key: str(value) if key in {"session_id", "client_msg_id", "on"} else value
                   for key, value in payload.items()}
        headers = {"X-AI-Internal-Token": get_settings().ai_internal_token.get_secret_value()}

        async def harness():
            return runtime

        app.dependency_overrides[get_harness] = harness
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                denied = await client.post("/v1/chat/turns/memory", json=payload)
                self.assertEqual(denied.status_code, 401)
                result = await client.post("/v1/chat/turns/memory", json=payload, headers=headers)
                self.assertEqual(result.status_code, 200)
                body = result.json()
                self.assertEqual(body["client_msg_id"], payload["client_msg_id"])
                self.assertEqual(body["memory_update"]["changes"][0]["value"], 25)
                conflict = await client.post("/v1/chat/turns/memory",
                    json=payload | {"channel_identity": "different"}, headers=headers)
                self.assertEqual(conflict.status_code, 409)
        finally:
            app.dependency_overrides.clear()
        status_args = next(args for name, args in gateway.calls if name == "memory.turn_status")
        self.assertEqual(status_args, {"session_id": payload["session_id"],
            "client_msg_id": payload["client_msg_id"], "customer_id": "C001"})
        self.assertEqual(model.seen, [])
