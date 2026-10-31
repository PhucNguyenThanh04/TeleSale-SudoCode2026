"""Real PostgreSQL memory contract in an automatically removed test database."""

import os
import json
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg

from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection, store_dsn
from app.mcp_servers.mcp_memory.distiller_worker import process_one
from app.schemas.langmem import ProfileFactCandidate
from langgraph.store.postgres.aio import AsyncPostgresStore
from app.mcp_servers.mcp_memory.services.erasure import request_erasure
from app.mcp_servers.mcp_memory.services.erasure_executor import execute_erasure
from app.mcp_servers.mcp_memory.services.memory import read, write
from eval_harness.benchmark_runner import read_distillation_writes, wait_for_distillation
from scripts.backfill_langmem_store import backfill_customer


@unittest.skipUnless(os.getenv("MEMORY_INTEGRATION_ADMIN_DSN"),
                     "requires MEMORY_INTEGRATION_ADMIN_DSN with CREATEDB")
class MemoryPostgresIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_migration_can_be_reapplied(self):
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        migrations = sorted(migration_dir.glob("*.sql"))
        self.assertEqual([item.name for item in migrations],
                         ["0001_memory.sql", "0002_runtime_schema.sql"])
        async with self.repo.transaction() as conn:
            session = uuid4()
            await conn.execute("""INSERT INTO runtime.turns
                (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text)
                VALUES($1,1,NULL,'hotline','2026-10-15','Ẩn danh','Dạ')""", session)
            await conn.execute("""INSERT INTO runtime.episodes
                (session_id,customer_id,channel,on_date,summary)
                VALUES($1,'C901','hotline','2026-10-15','Đã kiểm toán thủ công')""", session)
            await conn.execute(migrations[1].read_text())
            self.assertEqual(await conn.fetchval("""SELECT summary
                FROM runtime.episodes WHERE session_id=$1""", session),
                "Đã kiểm toán thủ công")
            self.assertEqual(await conn.fetchval("""SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema='runtime'
                AND table_name='langmem_distillation_jobs'
                AND column_name IN ('accepted_writes','accepted_proposals','verified_outcome')"""), 3)

    async def test_eval_wait_is_scoped_to_source_turn(self):
        session, pending_source = str(uuid4()), str(uuid4())
        await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Tôi thích màu xanh", "agent_text": "Dạ",
            "on": "2026-10-15", "channel": "hotline",
            "client_msg_id": pending_source, "facts": []}, langmem_mode="enabled")
        await wait_for_distillation(self.dsn, str(uuid4()), timeout_seconds=0.05)
        with self.assertRaises(TimeoutError):
            await wait_for_distillation(self.dsn, pending_source, timeout_seconds=0.05)

    async def test_unfinished_store_write_is_hidden_until_job_completes(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        projection = LangMemProjection(self.dsn)
        await projection.put_facts("C901", str(uuid4()), str(uuid4()), "2026-10-15",
            [{"key": "preferred_color", "value": "xanh", "op": "set",
              "scope_type": "global", "scope_id": "", "source_kind": "customer",
              "evidence_quote": "màu xanh"}], revision=999)
        loaded = await read(self.repo, "C901", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(loaded["profile"], {})

    async def test_unfinished_supersession_keeps_last_completed_fact_and_episode(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        projection = LangMemProjection(self.dsn)
        session = str(uuid4())
        fact = {"key": "preferred_color", "value": "xanh", "op": "set",
                "scope_type": "global", "scope_id": "", "source_kind": "customer",
                "evidence_quote": "màu xanh"}
        await projection.put_facts("C901", session, str(uuid4()), "2026-10-15",
                                   [fact], revision=-1)
        await projection.put_episode("C901", session, {"summary": "Thích màu xanh",
            "on_date": "2026-10-15", "topics": [], "resolved_prior_items": []})
        await projection.put_facts("C901", session, str(uuid4()), "2026-10-16",
                                   [{**fact, "value": "trắng", "op": "supersede"}],
                                   revision=999)
        await projection.put_episode("C901", session, {"summary": "Thích màu trắng",
            "on_date": "2026-10-16", "topics": [], "resolved_prior_items": []},
            revision=999)
        loaded = await read(self.repo, "C901", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(loaded["profile"]["preferred_color"]["value"], "xanh")
        self.assertEqual(loaded["episodes"][0]["summary"], "Thích màu xanh")
        await projection.put_facts("C901", session, str(uuid4()), "2026-10-17",
                                   [{**fact, "op": "delete"}], revision=1000)
        after_pending_delete = await read(self.repo, "C901", str(uuid4()),
                                          langmem_mode="enabled", projector=projection)
        self.assertEqual(after_pending_delete["profile"]["preferred_color"]["value"],
                         "xanh")
        source = str(uuid4())
        await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Lên đơn giúp tôi", "agent_text": "Dạ",
            "on": "2026-10-18", "channel": "hotline", "client_msg_id": source,
            "facts": [], "outcome": "chot_don"}, langmem_mode="enabled")
        async def no_new_facts(_messages, _existing):
            return [], None
        self.assertTrue(await process_one(self.repo, no_new_facts, projection))
        after_completed_turn = await read(self.repo, "C901", str(uuid4()),
                                          langmem_mode="enabled", projector=projection)
        self.assertIn("Thích màu xanh", after_completed_turn["episodes"][0]["summary"])
        self.assertNotIn("Thích màu trắng", after_completed_turn["episodes"][0]["summary"])

    async def test_backfill_preserves_legacy_fact_for_primary_read(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        session, source = str(uuid4()), str(uuid4())
        old = await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Phòng tôi 25 m²", "agent_text": "Dạ em ghi nhận",
            "on": "2026-10-15", "channel": "hotline", "client_msg_id": source,
            "facts": [{"key": "room_area_m2", "value": 25, "op": "set",
                       "source_kind": "customer", "evidence_quote": "Phòng tôi 25 m²"}]},
            langmem_mode="off")
        self.assertEqual(old["memory_writes"][0]["value"], 25)
        projection = LangMemProjection(self.dsn)
        counts = await backfill_customer(self.repo, projection, "C901")
        self.assertEqual(counts["facts"], 1)
        self.assertEqual(counts["episodes"], 1)
        self.assertEqual(await backfill_customer(self.repo, projection, "C901"),
                         {"facts": 0, "episodes": 0, "skipped": 0})
        loaded = await read(self.repo, "C901", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(loaded["profile"]["room_area_m2"]["value"], 25)
        self.assertEqual(loaded["episodes"][0]["session_id"], session)

    async def test_worker_admits_fact_projects_episode_then_erases(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        projection = LangMemProjection(self.dsn)
        session, source = str(uuid4()), str(uuid4())
        await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Phòng tôi 25 m²", "agent_text": "Dạ em ghi nhận",
            "on": "2026-10-15", "channel": "hotline", "client_msg_id": source,
            "facts": []}, langmem_mode="enabled")
        async def extractor(messages, _existing):
            payload = json.loads(messages[0]["content"])
            return ([ProfileFactCandidate(key="room_area_m2", value=25,
                source_kind="customer", source_turn_id=payload["turn_id"],
                evidence_quote="Phòng tôi 25 m²", observed_on=date(2026, 10, 15))], None)
        self.assertTrue(await process_one(self.repo, extractor, projection))
        attributed = await read_distillation_writes(self.dsn, [source])
        self.assertEqual(attributed[source][0]["key"], "room_area_m2")
        loaded = await read(self.repo, "C901", str(uuid4()),
                            langmem_mode="enabled", projector=projection)
        self.assertEqual(loaded["profile"]["room_area_m2"]["value"], 25)
        self.assertEqual(loaded["episodes"][0]["summary"], "Phòng tôi 25 m²")
        key = str(uuid4())
        await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-901", verified_by="operator-1", scope=["ai_memory"])
        erased = await execute_erasure(self.repo, key, projection)
        self.assertEqual(erased["status"], "completed")
        self.assertEqual(await projection.list_facts("C901"), [])
        self.assertEqual(await projection.list_episodes("C901", 5), [])

    async def test_langmem_store_isolated_schema_persists_across_instances(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        first = LangMemProjection(self.dsn)
        await first.put_episode("C901", "session-1", {"summary": "Đang cân nhắc",
            "topics": [], "resolved_prior_items": []})
        second = LangMemProjection(self.dsn)
        self.assertEqual(len(await second.list_episodes("C901", 5)), 1)
        self.assertEqual(await second.list_episodes("C902", 5), [])
        async with self.repo.transaction() as conn:
            self.assertEqual(await conn.fetchval("""SELECT count(*) FROM pg_tables
                WHERE schemaname='runtime' AND tablename='store'"""), 1)
            self.assertEqual(await conn.fetchval("""SELECT count(*) FROM pg_tables
                WHERE schemaname='public' AND tablename='store'"""), 0)
        self.assertEqual(await second.delete_customer("C901"), 1)
        self.assertEqual(await first.list_episodes("C901", 5), [])

    async def test_distillation_job_is_durable_and_reclaims_expired_lease(self):
        session, source = str(uuid4()), str(uuid4())
        payload = {"customer_text": "Tôi thích màu xanh", "agent_text": "Dạ",
                   "on": "2026-10-15", "channel": "hotline", "client_msg_id": source,
                   "facts": [], "tool_observations": []}
        key = f"{session}:{source}:commit_turn"
        first = await write(self.repo, "commit_turn", "C901", session, payload,
                            operation_key=key, langmem_mode="shadow")
        again = await write(self.repo, "commit_turn", "C901", session, payload,
                            operation_key=key, langmem_mode="shadow")
        self.assertEqual(first, again)
        async with self.repo.transaction() as conn:
            self.assertEqual(await conn.fetchval("""SELECT count(*)
                FROM runtime.langmem_distillation_jobs WHERE session_id=$1""",
                UUID(session)), 1)
            job = await self.repo.claim_distillation(conn, 1)
            self.assertEqual(str(job["source_turn_id"]), source)
            await conn.execute("""UPDATE runtime.langmem_distillation_jobs
                SET lease_until=now()-interval '1 second' WHERE job_id=$1""", job["job_id"])
        async with self.repo.transaction() as conn:
            reclaimed = await self.repo.claim_distillation(conn, 1)
            self.assertEqual(reclaimed["job_id"], job["job_id"])
            self.assertEqual(reclaimed["attempts"], 2)

    async def test_structured_issue_resolves_across_sessions(self):
        first, second = str(uuid4()), str(uuid4())
        opened = await write(self.repo, "commit_turn", "C901", first, {
            "customer_text": "SKU-GAMMA giao cuối tuần được không?",
            "agent_text": "Để em kiểm tra.", "on": "2026-10-15",
            "channel": "chat_fanpage", "client_msg_id": str(uuid4()), "facts": [],
            "episode_delta": {"topic_updates": [{"scope_type": "product",
                "scope_id": "SKU-GAMMA", "add_items": [{"kind": "question",
                    "text": "Giao cuối tuần?", "evidence_quote": "giao cuối tuần được không?"}]}]}})
        self.assertEqual(opened["turn_no"], 1)
        prior = await read(self.repo, "C901", second)
        item = prior["episodes"][0]["topics"][0]["items"][0]
        self.assertEqual(item["status"], "open")
        resolved = await write(self.repo, "commit_turn", "C901", second, {
            "customer_text": "Tôi hỏi lại về SKU-GAMMA", "agent_text": "Có giao cuối tuần ạ.",
            "on": "2026-10-16", "channel": "hotline", "client_msg_id": str(uuid4()),
            "facts": [], "episode_delta": {"topic_updates": [{
                "scope_type": "product", "scope_id": "SKU-GAMMA",
                "resolve_items": [{"item_id": item["item_id"],
                                   "evidence_quote": "Có giao cuối tuần ạ."}]}]}})
        self.assertEqual(resolved["turn_no"], 1)
        again = await read(self.repo, "C901", str(uuid4()))
        self.assertIn(item["item_id"], {marker["item_id"] for episode in again["episodes"]
                                      for marker in episode["resolved_prior_items"]})

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
            await conn.execute("""INSERT INTO runtime.pending_facts
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
            rows = await conn.fetch("""SELECT customer_id,customer_text FROM runtime.turns
                WHERE session_id=$1""", UUID(session))
            self.assertEqual([(row["customer_id"], row["customer_text"]) for row in rows],
                             [(None, "Tôi đang xem thử")])
            self.assertEqual(await conn.fetchval("""SELECT count(*) FROM runtime.pending_facts
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
                    f"SELECT count(*) FROM runtime.{table} WHERE customer_id='C901'")
                self.assertEqual(count, 0, table)
            other = await conn.fetchval("""SELECT count(*) FROM runtime.facts
                WHERE customer_id='C902' AND status='active'""")
            self.assertEqual(other, 1)
            replay = await conn.fetchval("""SELECT result->>'error' FROM runtime.write_operations
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
            backend_migrations = Path(__file__).resolve().parents[2] / "backend" / "migrations"
            for migration in sorted(backend_migrations.glob("000*.sql")):
                await connection.execute(migration.read_text())
            migration_dir = Path(__file__).resolve().parents[1] / "migrations"
            for migration in sorted(migration_dir.glob("0*.sql")):
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
