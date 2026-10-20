"""Only verified customer sessions are removed; shared-phone peers survive."""

import os
import json
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.erasure import erase_verified_customer_chats
from app.services.chat_service import handle_chat_turn
from app.schemas.chat import ChatRequest


@unittest.skipUnless(os.getenv("BACKEND_INTEGRATION_ADMIN_DSN"),
                     "requires BACKEND_INTEGRATION_ADMIN_DSN with CREATEDB")
class BackendErasureIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        raw = os.environ["BACKEND_INTEGRATION_ADMIN_DSN"]
        self.admin = await asyncpg.connect(raw)
        self.database = "sudocode_backend_test_" + uuid4().hex[:12]
        await self.admin.execute(f'CREATE DATABASE "{self.database}"')
        parts = urlsplit(raw)
        dsn = urlunsplit((parts.scheme, parts.netloc,
                          "/" + self.database, parts.query, parts.fragment))
        connection = await asyncpg.connect(dsn)
        try:
            for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("000*.sql")):
                await connection.execute(path.read_text())
            await connection.execute("""CREATE SCHEMA btc_source;
                CREATE TABLE btc_source.customers (
                    customer_id text, phone text, fb_id text, zalo_id text)""")
        finally:
            await connection.close()
        self.engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
        self.sessions = async_sessionmaker(self.engine)

    async def asyncTearDown(self):
        if hasattr(self, "engine"):
            await self.engine.dispose()
        if hasattr(self, "admin"):
            if hasattr(self, "database"):
                await self.admin.execute("""SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity WHERE datname=$1""", self.database)
                await self.admin.execute(f'DROP DATABASE IF EXISTS "{self.database}"')
            await self.admin.close()

    async def test_suppressed_seed_identity_cannot_start_new_verified_chat(self):
        async with self.sessions() as session, session.begin():
            await session.execute(text("""INSERT INTO btc_source.customers
                (customer_id,phone) VALUES('C901','0900000901')"""))
        async with self.sessions() as session:
            await erase_verified_customer_chats(session, "C901", str(uuid4()))
        called = []
        def answer(request):
            called.append(request)
            return httpx.Response(200, json={})
        async with self.sessions() as session, httpx.AsyncClient(
            base_url="http://ai", transport=httpx.MockTransport(answer)) as client:
            with self.assertRaises(HTTPException) as error:
                await handle_chat_turn(session, client, "operator", ChatRequest(
                    text="Xin chào", caller_phone="0900000901", channel="hotline",
                    call_date=date(2026, 10, 15)))
        self.assertEqual(error.exception.status_code, 410)
        self.assertEqual(called, [])

    async def test_shared_phone_with_one_suppressed_owner_stays_ambiguous(self):
        async with self.sessions() as session, session.begin():
            await session.execute(text("""INSERT INTO btc_source.customers
                (customer_id,phone) VALUES('C901','0900000901'),('C902','0900000901')"""))
        async with self.sessions() as session:
            await erase_verified_customer_chats(session, "C901", str(uuid4()))
        payloads = []
        def answer(request):
            payload = json.loads(request.content)
            payloads.append(payload)
            return httpx.Response(200, json={"session_id": payload["session_id"],
                "client_msg_id": payload["client_msg_id"], "agent_text": "Dạ, xin xác minh thêm."})
        async with self.sessions() as session, httpx.AsyncClient(
            base_url="http://ai", transport=httpx.MockTransport(answer)) as client:
            result = await handle_chat_turn(session, client, "operator", ChatRequest(
                text="Tôi muốn hỏi tiếp", caller_phone="0900000901", channel="hotline",
                call_date=date(2026, 10, 15)))
        self.assertEqual(result.identity_status, "ambiguous")
        self.assertIsNone(payloads[0]["verified_customer_id"])

    async def test_erasure_selects_customer_id_not_shared_phone(self):
        ids = [str(uuid4()) for _ in range(3)]
        async with self.sessions() as session, session.begin():
            for session_id, owner, status in zip(ids, ("C901", "C902", None),
                                                  ("known", "known", "ambiguous")):
                await session.execute(text("""INSERT INTO app_runtime.chat_sessions
                    (id,created_by,caller_phone,channel,call_date,customer_id,identity_status)
                    VALUES (:id,'operator','0900000901','hotline',:on,:owner,:status)"""),
                    {"id": session_id, "on": date(2026, 10, 15),
                     "owner": owner, "status": status})
                await session.execute(text("""INSERT INTO app_runtime.chat_messages
                    (session_id,turn_no,role,content) VALUES (:id,1,'customer','Xin chào')"""),
                    {"id": session_id})
        key = str(uuid4())
        async with self.sessions() as session:
            first = await erase_verified_customer_chats(session, "C901", key)
        async with self.sessions() as session:
            second = await erase_verified_customer_chats(session, "C901", key)
            rows = (await session.execute(text("""SELECT id,customer_id
                FROM app_runtime.chat_sessions ORDER BY customer_id NULLS LAST"""))).all()
            messages = (await session.execute(text("""SELECT session_id
                FROM app_runtime.chat_messages"""))).all()
            suppression = (await session.execute(text("""SELECT customer_id,request_key
                FROM app_runtime.erasure_suppressions"""))).one()
        self.assertEqual(first["deleted_sessions"], 1)
        self.assertEqual(second["deleted_sessions"], 0)
        self.assertEqual({str(row.id) for row in rows}, {ids[1], ids[2]})
        self.assertEqual({str(row.session_id) for row in messages}, {ids[1], ids[2]})
        self.assertEqual(suppression.customer_id, "C901")
        self.assertEqual(str(suppression.request_key), key)
