"""The two-schema layout preserves operational and LangGraph rows."""

import os
import unittest
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.mcp_servers.mcp_memory.repos.langmem_projection import store_dsn


@unittest.skipUnless(os.getenv("MEMORY_INTEGRATION_ADMIN_DSN"),
                     "requires MEMORY_INTEGRATION_ADMIN_DSN with CREATEDB")
class RuntimeSchemaMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_existing_turn_job_and_langmem_row_survive_migration(self):
        root = Path(__file__).resolve().parents[1]
        migration = root / "migrations" / "0002_runtime_schema.sql"
        self.assertTrue(migration.is_file())
        raw = os.environ["MEMORY_INTEGRATION_ADMIN_DSN"]
        admin = await asyncpg.connect(raw)
        database = "sudocode_runtime_test_" + uuid4().hex[:12]
        try:
            await admin.execute(f'CREATE DATABASE "{database}"')
            parts = urlsplit(raw)
            dsn = urlunsplit((parts.scheme, parts.netloc,
                              "/" + database, parts.query, parts.fragment))
            conn = await asyncpg.connect(dsn)
            try:
                for path in sorted((root.parent / "backend" / "migrations").glob("000*.sql")):
                    await conn.execute(path.read_text())
                await conn.execute((root / "migrations" / "0001_memory.sql").read_text())
                session_id, turn_id = uuid4(), uuid4()
                await conn.execute("""INSERT INTO ai_memory.turns
                    (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text)
                    VALUES($1,1,'C-test','hotline','2026-10-15','Xin chào','Dạ')""",
                    session_id)
                await conn.execute("""INSERT INTO ai_memory.langmem_distillation_jobs
                    (session_id,customer_id,source_turn_id,turn_no,mode)
                    VALUES($1,'C-test',$2,1,'enabled')""", session_id, turn_id)
            finally:
                await conn.close()
            async with AsyncPostgresStore.from_conn_string(store_dsn(dsn), index=None) as store:
                await store.setup()
                await store.aput(("customers", "C-test", "facts"), "room_area_m2",
                                {"key": "room_area_m2", "value": 25}, index=False)
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(migration.read_text())
                await conn.execute(migration.read_text())
                self.assertEqual(await conn.fetchval(
                    "SELECT count(*) FROM runtime.turns WHERE session_id=$1", session_id), 1)
                self.assertEqual(await conn.fetchval(
                    "SELECT count(*) FROM runtime.langmem_distillation_jobs WHERE session_id=$1",
                    session_id), 1)
                self.assertEqual(await conn.fetchval("SELECT count(*) FROM runtime.store"), 1)
                self.assertIsNone(await conn.fetchval("""SELECT nspname FROM pg_namespace
                    WHERE nspname IN ('app_runtime','ai_memory','langmem_store','public') LIMIT 1"""))
            finally:
                await conn.close()
        finally:
            await admin.execute("""SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity WHERE datname=$1""", database)
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
            await admin.close()
