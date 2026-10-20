"""Real PostgreSQL memory contract in an automatically removed test database."""

import os
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg

from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.services.erasure import request_erasure
from app.mcp_servers.mcp_memory.services.erasure_executor import execute_erasure
from app.mcp_servers.mcp_memory.services.memory import read, write


@unittest.skipUnless(os.getenv("MEMORY_INTEGRATION_ADMIN_DSN"),
                     "requires MEMORY_INTEGRATION_ADMIN_DSN with CREATEDB")
class MemoryPostgresIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_request_key_rejects_changed_verification_evidence(self):
        key = str(uuid4())
        first = await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-901", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(first["status"], "pending")
        changed = await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-902", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(changed, {"error": "request_key_conflict"})

    async def test_mixed_session_keeps_anonymous_turn_and_marks_unowned_pending(self):
        session = str(uuid4())
        await write(self.repo, "turn", None, session, {
            "customer_text": "Tôi đang xem thử", "agent_text": "Dạ",
            "on": "2026-10-15", "channel": "hotline"})
        async with self.repo.transaction() as conn:
            await conn.execute("""INSERT INTO ai_memory.pending_facts
                (session_id,source_turn_id,turn_no,key,value,op,source_kind,on_date)
                VALUES($1,$2,1,'preferred_color',$3::jsonb,'set','customer',$4)""",
                UUID(session), uuid4(), '"xanh"', date(2026, 10, 15))
        await write(self.repo, "turn", "C901", session, {
            "customer_text": "Tôi chọn màu đen", "agent_text": "Dạ",
            "on": "2026-10-15", "channel": "hotline"})
        key = str(uuid4())
        await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-902", verified_by="operator-1", scope=["ai_memory"])
        result = await execute_erasure(self.repo, key)
        self.assertEqual(result["status"], "partial")
        async with self.repo.transaction() as conn:
            rows = await conn.fetch("""SELECT customer_id,customer_text FROM ai_memory.turns
                WHERE session_id=$1""", UUID(session))
            self.assertEqual([(row["customer_id"], row["customer_text"]) for row in rows],
                             [(None, "Tôi đang xem thử")])
            self.assertEqual(await conn.fetchval("""SELECT count(*) FROM ai_memory.pending_facts
                WHERE session_id=$1""", UUID(session)), 1)

    async def test_memory_only_erasure_removes_owned_rows_and_retry_is_safe(self):
        customer_session, other_session = str(uuid4()), str(uuid4())
        for customer_id, session in (("C901", customer_session), ("C902", other_session)):
            await write(self.repo, "commit_turn", customer_id, session, {
                "customer_text": "Tôi thích màu xanh", "agent_text": "Dạ",
                "on": "2026-10-15", "channel": "hotline",
                "client_msg_id": str(uuid4()), "facts": [{
                    "key": "preferred_color", "value": "xanh", "op": "set",
                    "source_kind": "customer"}]}, operation_key=f"{session}:turn-1")
        request_key = str(uuid4())
        await request_erasure(self.repo, customer_id="C901", request_key=request_key,
            verification_ref="case-901", verified_by="operator-1", scope=["ai_memory"])
        first = await execute_erasure(self.repo, request_key)
        second = await execute_erasure(self.repo, request_key)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        async with self.repo.transaction() as conn:
            for table in ("facts", "episodes", "turns", "order_links"):
                count = await conn.fetchval(
                    f"SELECT count(*) FROM ai_memory.{table} WHERE customer_id='C901'")
                self.assertEqual(count, 0, table)
            other = await conn.fetchval("""SELECT count(*) FROM ai_memory.facts
                WHERE customer_id='C902' AND status='active'""")
            self.assertEqual(other, 1)
            replay = await conn.fetchval("""SELECT result->>'error' FROM ai_memory.write_operations
                WHERE operation_key=$1""", f"{customer_session}:turn-1")
            self.assertEqual(replay, "erased")

    async def asyncSetUp(self):
        raw = os.environ["MEMORY_INTEGRATION_ADMIN_DSN"]
        self.admin = await asyncpg.connect(raw)
        self.database = "sudocode_memory_test_" + uuid4().hex[:12]
        await self.admin.execute(f'CREATE DATABASE "{self.database}"')
        parts = urlsplit(raw)
        self.dsn = urlunsplit((parts.scheme, parts.netloc,
                               "/" + self.database, parts.query, parts.fragment))
        connection = await asyncpg.connect(self.dsn)
        try:
            await connection.execute("CREATE SCHEMA app_runtime")
            migration_dir = Path(__file__).resolve().parents[1] / "migrations"
            for migration in sorted(migration_dir.glob("000*.sql")):
                await connection.execute(migration.read_text())
        finally:
            await connection.close()
        self.repo = MemoryRepo(self.dsn)

    async def asyncTearDown(self):
        if hasattr(self, "repo"):
            await self.repo.close()
        if hasattr(self, "admin"):
            if hasattr(self, "database"):
                await self.admin.execute("""SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity WHERE datname=$1""", self.database)
                await self.admin.execute(f'DROP DATABASE IF EXISTS "{self.database}"')
            await self.admin.close()

    async def test_scoped_facts_survive_restart_then_verified_barrier_blocks_owner(self):
        session = str(uuid4())
        facts = [{"key": "product_advised", "value": sku, "op": "set",
                  "source_kind": "tool", "source_tool": "pricing.get_quote",
                  "scope_type": "product", "scope_id": sku}
                 for sku in ("SKU-ALPHA", "SKU-BETA")]
        facts.extend({"key": "room_area_m2", "value": area, "op": "set",
                      "source_kind": "customer", "scope_type": "room", "scope_id": room}
                     for room, area in (("phong_ngu", 12), ("phong_khach", 45)))
        result = await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Hai phòng 12 và 45 m², hỏi hai mẫu.",
            "agent_text": "Em tư vấn SKU-ALPHA và SKU-BETA.",
            "on": "2026-10-15", "channel": "hotline",
            "client_msg_id": str(uuid4()), "facts": facts})
        self.assertEqual(len(result["memory_writes"]), 4)
        second_repo = MemoryRepo(self.dsn)
        try:
            loaded = await read(second_repo, "C901", str(uuid4()))
            self.assertEqual(set(loaded["scoped_facts"]["product"]),
                             {"SKU-ALPHA", "SKU-BETA"})
            self.assertEqual({room: values["room_area_m2"]["value"]
                              for room, values in loaded["scoped_facts"]["room"].items()},
                             {"phong_ngu": 12, "phong_khach": 45})
            registered = await request_erasure(self.repo, customer_id="C901",
                request_key=str(uuid4()), verification_ref="case-901",
                verified_by="operator-1", scope=["ai_memory"])
            self.assertEqual(registered["status"], "pending")
            self.assertEqual(await read(second_repo, "C901", str(uuid4())),
                             {"error": "customer_erasure_in_progress"})
            self.assertEqual((await read(second_repo, "C902", str(uuid4())))["profile"], {})
            blocked = await write(second_repo, "fact", "C901", session, {
                "key": "preferred_color", "value": "xanh", "op": "set", "source": "test"})
            self.assertEqual(blocked, {"error": "customer_erasure_in_progress"})
        finally:
            await second_repo.close()
