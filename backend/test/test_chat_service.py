"""Focused checks for identity isolation and chat persistence boundaries."""

import json
import unittest
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.schemas.chat import ChatRequest
from app.services.chat_service import handle_chat_turn


class _Result:
    def __init__(self, rows=None, scalar=None):
        self.rows = rows or []
        self.scalar = scalar

    def __iter__(self):
        return iter(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.scalar


class _Transaction:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.previous = dict(self.db.sessions), list(self.db.messages)
        return self

    async def __aexit__(self, error_type, *_):
        if error_type:
            self.db.sessions, self.db.messages = self.previous


class _Database:
    def __init__(self, customer_ids):
        self.customer_ids = customer_ids
        self.sessions = {}
        self.messages = []

    def begin(self):
        return _Transaction(self)

    async def execute(self, statement, values=None):
        sql = str(statement)
        if "FROM btc_source.customers" in sql:
            return _Result([SimpleNamespace(customer_id=key) for key in self.customer_ids])
        if "INSERT INTO app_runtime.chat_sessions" in sql:
            self.sessions[values["id"]] = SimpleNamespace(
                id=UUID(values["id"]), created_by=values["operator_id"],
                caller_phone=values["caller_phone"],
                channel_identity=values["channel_identity"],
                customer_id=values["customer_id"], identity_status=values["identity_status"],
                channel=values["channel"], call_date=values["call_date"], status="open",
            )
            return _Result()
        if "FROM app_runtime.chat_sessions" in sql:
            session = self.sessions.get(values["id"])
            return _Result([session] if session else [])
        if "MAX(turn_no)" in sql:
            return _Result(scalar=max((message["turn_no"] for message in self.messages), default=0) + 1)
        if "INSERT INTO app_runtime.chat_messages" in sql:
            self.messages.append(values)
            return _Result()
        if "UPDATE app_runtime.chat_sessions" in sql:
            return _Result()
        raise AssertionError(sql)


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.first_turn = ChatRequest(
            text="Số của chị 0984726714", caller_phone="0984726714",
            channel="hotline", call_date=date(2026, 10, 15),
        )

    async def test_known_customer_and_continuing_session(self):
        calls = []

        def answer(request):
            payload = json.loads(request.content)
            calls.append(payload)
            return httpx.Response(200, json={
                "client_msg_id": payload["client_msg_id"],
                "session_id": payload["session_id"], "agent_text": "Dạ, em đã nhận được ạ.",
            })

        db = _Database(["C001"])
        async with httpx.AsyncClient(base_url="http://ai", transport=httpx.MockTransport(answer)) as client:
            first = await handle_chat_turn(db, client, "operator", self.first_turn)
            second = await handle_chat_turn(
                db, client, "operator", ChatRequest(session_id=first.session_id, text="Còn hàng không?"),
            )
        self.assertEqual(first.identity_status, "known")
        self.assertEqual(first.session_id, second.session_id)
        self.assertEqual([row["turn_no"] for row in db.messages], [1, 1, 2, 2])
        self.assertEqual(calls[0]["channel_identity"], "0984726714")
        self.assertEqual(calls[0]["on"], "2026-10-15")
        self.assertEqual(calls[0]["input_mode"], "clean")
        self.assertNotIn("caller_phone", calls[0])
        self.assertIn("***6714", calls[0]["text"])

    async def test_shared_phone_does_not_reach_ai(self):
        db = _Database(["C034", "C035"])
        def unexpected(_request):
            raise AssertionError("AI should not receive an ambiguous identity")
        async with httpx.AsyncClient(base_url="http://ai", transport=httpx.MockTransport(unexpected)) as client:
            result = await handle_chat_turn(db, client, "operator", self.first_turn)
        self.assertEqual(result.identity_status, "ambiguous")
        self.assertEqual(len(db.messages), 2)

    async def test_fanpage_identity_reaches_ai_without_phone(self):
        payloads = []
        def answer(request):
            payload = json.loads(request.content)
            payloads.append(payload)
            return httpx.Response(200, json={
                "client_msg_id": payload["client_msg_id"],
                "session_id": payload["session_id"], "agent_text": "Dạ, em kiểm tra ạ.",
            })
        db = _Database(["C001"])
        async with httpx.AsyncClient(base_url="http://ai", transport=httpx.MockTransport(answer)) as client:
            response = await handle_chat_turn(db, client, "operator", ChatRequest(
                text="shop oi", channel="chat_fanpage", channel_identity="fb.hoa.479",
                call_date=date(2026, 10, 15), customer_input_mode="chat_teencode"))
        self.assertEqual(response.identity_status, "known")
        self.assertEqual(payloads[0]["channel_identity"], "fb.hoa.479")
        self.assertEqual(payloads[0]["input_mode"], "chat_teencode")

    async def test_ai_error_rolls_back_new_session_and_messages(self):
        db = _Database(["C001"])
        async with httpx.AsyncClient(
            base_url="http://ai", transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        ) as client:
            with self.assertRaises(HTTPException) as caught:
                await handle_chat_turn(db, client, "operator", self.first_turn)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(db.sessions, {})
        self.assertEqual(db.messages, [])

    async def test_other_operator_cannot_continue_session(self):
        db = _Database(["C001"])
        def answer(request):
            payload = json.loads(request.content)
            return httpx.Response(200, json={
                "client_msg_id": payload["client_msg_id"],
                "session_id": payload["session_id"], "agent_text": "Dạ, em đã nhận được ạ.",
            })
        async with httpx.AsyncClient(base_url="http://ai", transport=httpx.MockTransport(answer)) as client:
            first = await handle_chat_turn(db, client, "operator-a", self.first_turn)
            with self.assertRaises(HTTPException) as caught:
                await handle_chat_turn(
                    db, client, "operator-b", ChatRequest(session_id=first.session_id, text="Tiếp tục"),
                )
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(len(db.messages), 2)
