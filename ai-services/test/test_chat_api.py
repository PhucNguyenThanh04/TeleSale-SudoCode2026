"""HTTP contract checks for the text-turn harness endpoint."""

import unittest

import httpx
from app.api.chat import get_harness
from app.main import app
from app.configs import get_settings
from app.schemas.agent import TextTurnResponse


class _Harness:
    async def run(self, turn):
        return TextTurnResponse(client_msg_id=turn.client_msg_id,
                                session_id=turn.session_id,
                                agent_text="Dạ, em có thể hỗ trợ gì ạ?")


class ChatApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        async def fake_harness():
            return _Harness()
        app.dependency_overrides[get_harness] = fake_harness
        self.headers = {"X-AI-Internal-Token": get_settings().ai_internal_token.get_secret_value()}
        self.transport = httpx.ASGITransport(app=app)
        self.payload = {
            "client_msg_id": "11111111-1111-4111-8111-111111111111",
            "session_id": "22222222-2222-4222-8222-222222222222",
            "channel": "chat_fanpage",
            "channel_identity": "fb.hạnh.274",
            "on": "2026-10-15",
            "text": "shop oi ...",
            "input_mode": "chat_teencode",
        }

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    async def post(self, payload, headers=None):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            return await client.post("/v1/chat/turns", json=payload,
                                     headers=self.headers if headers is None else headers)

    async def test_text_turn_echoes_identifiers(self) -> None:
        response = await self.post(self.payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["client_msg_id"], self.payload["client_msg_id"])
        self.assertEqual(body["session_id"], self.payload["session_id"])
        self.assertEqual(body["agent_text"], "Dạ, em có thể hỗ trợ gì ạ?")
        self.assertFalse(body["needs_handoff"])
        self.assertIsNone(body["handoff_ticket_id"])

    async def test_invalid_request_is_rejected(self) -> None:
        for change in (
            {"client_msg_id": "not-a-uuid"},
            {"on": "tomorrow"},
            {"text": "   "},
            {"input_mode": "unknown"},
        ):
            with self.subTest(change=change):
                response = await self.post(self.payload | change)
                self.assertEqual(response.status_code, 422)

        missing = self.payload.copy()
        del missing["channel_identity"]
        self.assertEqual((await self.post(missing)).status_code, 422)

    async def test_first_turn_generates_session_id(self) -> None:
        response = await self.post(self.payload | {"session_id": None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["session_id"])
        self.assertEqual(response.json()["client_msg_id"], self.payload["client_msg_id"])

    async def test_requires_backend_token(self) -> None:
        self.assertEqual((await self.post(self.payload, headers={})).status_code, 401)

    async def test_openapi_exposes_request_and_response(self) -> None:
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            document = (await client.get("/openapi.json")).json()
        endpoint = document["paths"]["/v1/chat/turns"]["post"]
        self.assertEqual(
            endpoint["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ChatRequest",
        )
        self.assertIn("200", endpoint["responses"])


if __name__ == "__main__":
    unittest.main()
