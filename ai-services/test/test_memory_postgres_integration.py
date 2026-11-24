
import os
import asyncio
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


@unittest.skipUnless(os.getenv("MEMORY_INTEGRATION_ADMIN_DSN"),
                     "requires MEMORY_INTEGRATION_ADMIN_DSN with CREATEDB")
class MemoryPostgresIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_drop_refuses_nonempty_table(self):
        migration = (Path(__file__).resolve().parents[1] / "migrations" /
                     "0001_current_memory_schema.sql").read_text()
        conn = await asyncpg.connect(self.dsn)
        try:
            await conn.execute("CREATE TABLE runtime.pending_facts (id integer PRIMARY KEY)")
            await conn.execute("INSERT INTO runtime.pending_facts VALUES (1)")
            with self.assertRaisesRegex(asyncpg.RaiseError, "contains rows"):
                await conn.execute(migration)
            await conn.execute("ROLLBACK")
            self.assertEqual(await conn.fetchval(
                "SELECT count(*) FROM runtime.pending_facts"), 1)
            await conn.execute("DELETE FROM runtime.pending_facts")
            await conn.execute(migration)
            self.assertIsNone(await conn.fetchval(
                "SELECT to_regclass('runtime.pending_facts')"))
        finally:
            await conn.close()

    async def test_runtime_migration_can_be_reapplied(self):
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        migrations = [migration_dir / name for name in (
            '0001_current_memory_schema.sql', '0004_memory_job_order.sql',
            '0005_durable_turn_evidence.sql', '0006_private_delivery_context.sql',
            '0007_turn_retry_hash.sql')]
        async with self.repo.transaction() as conn:
            session = uuid4()
            await conn.execute("""INSERT INTO runtime.turns
                (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text)
                VALUES($1,1,NULL,'hotline','2026-10-15','Ẩn danh','Dạ')""", session)
            for migration in migrations:
                await conn.execute(migration.read_text())
            self.assertEqual(await conn.fetchval("""SELECT count(*)
                FROM runtime.turns WHERE session_id=$1""", session), 1)
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
            "client_msg_id": pending_source})
        anonymous_source = str(uuid4())
        await write(self.repo, 'commit_turn', None, str(uuid4()), {
            'customer_text': 'Chào', 'agent_text': 'Dạ', 'on': '2026-10-15',
            'channel': 'hotline', 'client_msg_id': anonymous_source})
        await wait_for_distillation(self.dsn, anonymous_source, timeout_seconds=0.05)
        with self.assertRaisesRegex(RuntimeError, 'missing turn'):
            await wait_for_distillation(self.dsn, str(uuid4()), timeout_seconds=0.05)
        with self.assertRaises(TimeoutError):
            await wait_for_distillation(self.dsn, pending_source, timeout_seconds=0.05)

    async def test_eval_writes_include_only_the_committed_delivery_for_the_completed_job(self):
        source = str(uuid4())
        for customer, address in (('C901', '12 Lê Lợi, Hà Nội'), ('C902', '45 Lê Lợi, Hà Nội')):
            result = await write(self.repo, 'commit_turn', customer, str(uuid4()), {
                'customer_text': 'Giao về địa chỉ đã xác nhận', 'agent_text': 'Dạ',
                'on': '2026-10-15', 'channel': 'hotline', 'client_msg_id': source,
                'private_delivery': {'address': address, 'source_turn_id': source,
                    'source_on': '2026-10-15', 'source_customer_text': '[ĐỊA CHỈ ĐÃ ẨN]'}})
            self.assertEqual(result['turn_no'], 1)
        async with self.repo.transaction() as conn:
            await conn.execute("UPDATE runtime.langmem_distillation_jobs SET status='completed' WHERE customer_id='C901'")

        self.assertEqual(await read_distillation_writes(self.dsn, [source]), {source: [
            {'key': 'address', 'value': '12 Lê Lợi, Hà Nội', 'op': 'set', 'customer_id': 'C901'}]})

    async def test_unfinished_store_write_is_hidden_until_job_completes(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        projection = LangMemProjection(self.dsn)
        await projection.put_facts("C901", str(uuid4()), str(uuid4()), "2026-10-15",
            [{"key": "preferred_color", "value": "xanh", "op": "set",
              "scope_type": "global", "scope_id": "", "source_kind": "customer",
              "evidence_quote": "màu xanh"}], revision=999)
        loaded = await read(self.repo, "C901", str(uuid4()),
                            projector=projection)
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
                            projector=projection)
        self.assertEqual(loaded["profile"]["preferred_color"]["value"], "xanh")
        self.assertEqual(loaded["episodes"][0]["summary"], "Thích màu xanh")
        await projection.put_facts("C901", session, str(uuid4()), "2026-10-17",
                                   [{**fact, "op": "delete"}], revision=1000)
        after_pending_delete = await read(self.repo, "C901", str(uuid4()),
                                          projector=projection)
        self.assertEqual(after_pending_delete["profile"]["preferred_color"]["value"],
                         "xanh")
        source = str(uuid4())
        await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Lên đơn giúp tôi", "agent_text": "Dạ",
            "on": "2026-10-18", "channel": "hotline", "client_msg_id": source,
            "outcome": "chot_don"})
        async def no_new_facts(_messages, _existing):
            return [], None
        self.assertTrue(await process_one(self.repo, no_new_facts, projection))
        after_completed_turn = await read(self.repo, "C901", str(uuid4()),
                                          projector=projection)
        self.assertIn("Thích màu xanh", after_completed_turn["episodes"][0]["summary"])
        self.assertNotIn("Thích màu trắng", after_completed_turn["episodes"][0]["summary"])

    async def test_worker_admits_fact_projects_episode_then_erases(self):
        async with AsyncPostgresStore.from_conn_string(store_dsn(self.dsn), index=None) as store:
            await store.setup()
        projection = LangMemProjection(self.dsn)
        session, source = str(uuid4()), str(uuid4())
        await write(self.repo, "commit_turn", "C901", session, {
            "customer_text": "Phòng tôi 25 m²", "agent_text": "Dạ em ghi nhận",
            "on": "2026-10-15", "channel": "hotline", "client_msg_id": source})
        async def extractor(messages, _existing):
            payload = json.loads(messages[0]["content"])
            return ([ProfileFactCandidate(key="room_area_m2", value=25,
                source_kind="customer", source_turn_id=payload["turn_id"],
                evidence_quote="Phòng tôi 25 m²", observed_on=date(2026, 10, 15))], None)
        async def reviewer(facts, *_args):
            return facts
        self.assertTrue(await process_one(self.repo, extractor, projection,
                                         fact_reviewer=reviewer))
        attributed = await read_distillation_writes(self.dsn, [source])
        self.assertEqual(attributed[source][0]["key"], "room_area_m2")
        loaded = await read(self.repo, "C901", str(uuid4()),
                            projector=projection)
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
                   "tool_observations": []}
        key = f"{session}:{source}:commit_turn"
        first = await write(self.repo, "commit_turn", "C901", session, payload,
                            operation_key=key)
        again = await write(self.repo, "commit_turn", "C901", session, payload,
                            operation_key=key)
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

    async def test_historical_shadow_job_is_not_claimed(self):
        session, source = uuid4(), uuid4()
        async with self.repo.transaction() as conn:
            await conn.execute("""INSERT INTO runtime.langmem_distillation_jobs
                (session_id,customer_id,source_turn_id,turn_no,mode)
                VALUES($1,'C901',$2,1,'shadow')""", session, source)
            self.assertIsNone(await self.repo.claim_distillation(conn, 1))

    async def test_crashed_final_attempt_does_not_block_later_customer_session(self):
        first, second = uuid4(), uuid4()
        async with self.repo.transaction() as conn:
            exhausted = await conn.fetchval('''INSERT INTO runtime.langmem_distillation_jobs
                (session_id,customer_id,source_turn_id,turn_no,mode,status,attempts,lease_until)
                VALUES($1,'C901',$2,1,'enabled','leased',5,now()-interval '1 second') RETURNING job_id''',
                first, uuid4())
            following = await conn.fetchval('''INSERT INTO runtime.langmem_distillation_jobs
                (session_id,customer_id,source_turn_id,turn_no,mode)
                VALUES($1,'C901',$2,1,'enabled') RETURNING job_id''', second, uuid4())
        async def unexpected_extraction(*args):
            raise AssertionError('An exhausted job must not call the model again')
        self.assertTrue(await process_one(self.repo, unexpected_extraction, None))
        async with self.repo.transaction() as conn:
            self.assertEqual(await conn.fetchval('''SELECT status FROM runtime.langmem_distillation_jobs
                WHERE job_id=$1''', exhausted), 'failed')
            next_job = await self.repo.claim_distillation(conn, 1)
            self.assertEqual(next_job['job_id'], following)

    async def test_claim_serializes_customer_sessions_but_allows_other_customers(self):
        async with self.repo.transaction() as conn:
            ids = []
            for customer in ('C901', 'C901', 'C902'):
                ids.append(await conn.fetchval('''INSERT INTO runtime.langmem_distillation_jobs
                    (session_id,customer_id,source_turn_id,turn_no,mode)
                    VALUES($1,$2,$3,1,'enabled') RETURNING job_id''', uuid4(), customer, uuid4()))
        async with self.repo.transaction() as first_connection:
            first = await self.repo.claim_distillation(first_connection, 1)
            self.assertEqual(first['job_id'], ids[0])
            async with self.repo.transaction() as other_connection:
                concurrent = await self.repo.claim_distillation(other_connection, 1)
                self.assertEqual(concurrent['job_id'], ids[2])
            await self.repo.finish_distillation(first_connection, ids[0], 'completed')
        async with self.repo.transaction() as conn:
            following = await self.repo.claim_distillation(conn, 1)
            self.assertEqual(following['job_id'], ids[1])
            await conn.execute('''UPDATE runtime.langmem_distillation_jobs
                SET lease_until=now()-interval '1 second' WHERE job_id=$1''', ids[1])
            reclaimed = await self.repo.claim_distillation(conn, 1)
            self.assertEqual(reclaimed['job_id'], ids[1])
            self.assertFalse(await self.repo.distillation_claim_current(conn, ids[1], following['attempts']))
            self.assertTrue(await self.repo.distillation_claim_current(conn, ids[1], reclaimed['attempts']))

    async def test_basket_lines_and_promotion_are_transactional_in_postgres(self):
        from dataloader_offline.postgres import import_release
        from test_november_pricing import reference
        from app.mcp_servers.mcp_catalog.repos.postgres import CatalogRepo
        from app.mcp_servers.mcp_catalog.services.catalog import get_quote_order
        from app.mcp_servers.mcp_order.repos.postgres import OrderRepo
        from app.mcp_servers.mcp_order.services.order import invoke
        data = reference.__wrapped__()
        phone = '0900000000'
        await import_release(self.dsn, {'products': {'products': data.PRODUCTS},
            'promotions': {'promotions': data.PROMOS}, 'inventory': {'events': data.INV},
            'crm': {'customers': [{'customer_id': 'C901', 'phone': phone, 'name': 'Offline buyer'}]},
            'chunks': []})
        sqlalchemy_dsn = self.dsn.replace('postgresql://', 'postgresql+asyncpg://', 1)
        catalog, orders = CatalogRepo(sqlalchemy_dsn), OrderRepo(sqlalchemy_dsn)
        payload = {'customer_phone': phone, 'source_channel': 'hotline', 'source_identity': phone,
                   'on': '2026-10-15', 'lines': [{'sku': 'SKU-AP-PRO', 'qty': 2}], 'payment': 'bank'}
        try:
            async with catalog.transaction() as session:
                quote = await get_quote_order(catalog, session, payload)
            create_args = {**payload, 'lines': [{'sku': unit['sku'], 'qty': 1,
                'price_vnd': unit['final_price_vnd']} for unit in quote['units']]}
            results = await asyncio.gather(*(invoke(orders, 'order.create',
                {**create_args, 'operation_key': key}) for key in ('basket-A', 'basket-B')))
            self.assertEqual(sum(result.get('status') == 'created' for result in results), 1)
            self.assertEqual(sum(result.get('error') == 'price_mismatch' for result in results), 1)
            winner = next(index for index, result in enumerate(results) if result.get('status') == 'created')
            replay = await invoke(orders, 'order.create', {**create_args,
                'operation_key': ('basket-A', 'basket-B')[winner]})
            self.assertEqual(replay, results[winner])
            status = await invoke(orders, 'order.status', {
                'source_channel': 'hotline', 'source_identity': phone, 'order_id': replay['order_id']})
            self.assertEqual(status['orders'][0]['lines'], create_args['lines'])
            async with self.repo.transaction() as conn:
                self.assertEqual(await conn.fetchval('SELECT count(*) FROM runtime.tool_orders'), 1)
                await conn.execute('''INSERT INTO runtime.tool_orders
                    (order_id,customer_id,customer_phone,sku,qty,price_vnd,total_vnd,payment,created_on)
                    VALUES('LEGACY','C901',$1,'SKU-AP-PRO',1,100,100,'bank','2026-10-14')''', phone)
                await conn.execute((Path(__file__).resolve().parents[2] / 'backend/migrations/0006_order_lines.sql').read_text())
                self.assertEqual(json.loads(await conn.fetchval(
                    "SELECT lines FROM runtime.tool_orders WHERE order_id='LEGACY'")),
                    [{'sku': 'SKU-AP-PRO', 'qty': 1, 'price_vnd': 100}])
            async with catalog.transaction() as session:
                refreshed = await get_quote_order(catalog, session, payload)
            self.assertGreater(refreshed['total_vnd'], quote['total_vnd'])
        finally:
            await catalog.close()
            await orders.close()


    async def test_request_key_rejects_changed_verification_evidence(self):
        key = str(uuid4())
        first = await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-901", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(first["status"], "pending")
        changed = await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-902", verified_by="operator-1", scope=["ai_memory"])
        self.assertEqual(changed, {"error": "request_key_conflict"})

    async def test_mixed_session_keeps_anonymous_turn(self):
        session = str(uuid4())
        async with self.repo.transaction() as conn:
            await conn.execute("""INSERT INTO runtime.turns
                (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text,client_msg_id)
                VALUES($1,1,NULL,'hotline',$2,'Tôi đang xem thử','Dạ',$3),
                      ($1,2,'C901','hotline',$2,'Tôi chọn màu đen','Dạ',$4)""",
                UUID(session), date(2026, 10, 15), uuid4(), uuid4())
        key = str(uuid4())
        await request_erasure(self.repo, customer_id="C901", request_key=key,
            verification_ref="case-902", verified_by="operator-1", scope=["ai_memory"])
        result = await execute_erasure(self.repo, key)
        self.assertEqual(result["status"], "completed")
        async with self.repo.transaction() as conn:
            rows = await conn.fetch("""SELECT customer_id,customer_text FROM runtime.turns
                WHERE session_id=$1""", UUID(session))
            self.assertEqual([(row["customer_id"], row["customer_text"]) for row in rows],
                             [(None, "Tôi đang xem thử")])

    async def test_memory_only_erasure_removes_owned_rows_and_retry_is_safe(self):
        customer_session, other_session = str(uuid4()), str(uuid4())
        for customer_id, session in (("C901", customer_session), ("C902", other_session)):
            await write(self.repo, "commit_turn", customer_id, session, {
                "customer_text": "Tôi thích màu xanh", "agent_text": "Dạ",
                "on": "2026-10-15", "channel": "hotline",
                "client_msg_id": str(uuid4())}, operation_key=f"{session}:turn-1")
        request_key = str(uuid4())
        await request_erasure(self.repo, customer_id="C901", request_key=request_key,
            verification_ref="case-901", verified_by="operator-1", scope=["ai_memory"])
        first = await execute_erasure(self.repo, request_key)
        second = await execute_erasure(self.repo, request_key)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        async with self.repo.transaction() as conn:
            for table in ("turns", "order_links"):
                count = await conn.fetchval(
                    f"SELECT count(*) FROM runtime.{table} WHERE customer_id='C901'")
                self.assertEqual(count, 0, table)
            other = await conn.fetchval("""SELECT count(*) FROM runtime.turns
                WHERE customer_id='C902'""")
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
            from dataloader_offline.postgres import DDL
            await connection.execute(DDL)
            backend_migrations = Path(__file__).resolve().parents[2] / "backend" / "migrations"
            for migration in sorted(backend_migrations.glob("000*.sql")):
                await connection.execute(migration.read_text())
            migration_dir = Path(__file__).resolve().parents[1] / "migrations"
            await connection.execute((migration_dir /
                "0001_current_memory_schema.sql").read_text())
            await connection.execute((migration_dir /
                "0004_memory_job_order.sql").read_text())
            await connection.execute((migration_dir /
                "0005_durable_turn_evidence.sql").read_text())
            await connection.execute((migration_dir /
                "0006_private_delivery_context.sql").read_text())
            await connection.execute((migration_dir /
                "0007_turn_retry_hash.sql").read_text())
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
