"""Integration checks for the eval-only runtime data reset."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

from app.configs import Settings
from app.mcp_servers.mcp_shared.config import database_url


class RuntimeResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_configurations_reset_before_each_run(self):
        from eval_harness.benchmark_runner import main

        with tempfile.TemporaryDirectory() as folder:
            dataset = Path(folder) / "scenarios.json"
            dataset.write_text('{"scenarios": [{"scenario_id":"X","calls":{"call_1":{"customer_turns":["Xin chào"]}}}]}', encoding="utf-8")
            output = Path(folder) / "report.json"
            fake_runtime = SimpleNamespace(tools=SimpleNamespace(), run=AsyncMock(return_value=SimpleNamespace(agent_text="Dạ",call_brief=None)), state_for=lambda request: {}, memory=SimpleNamespace(
                include_prior=True, namespace=""))
            args = ["benchmark_runner", "--agent", "deep", "--config", "both",
                    "--scenarios", str(dataset), "--out", str(output),
                    "--btc-root", str(Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS"), "--expected-database", "telesale"]
            with patch("app.knowledge.context.capture_release",new_callable=AsyncMock,return_value={"release_id":"btc-only","manifest_hash":"btc-only"}), patch("eval_harness.benchmark_runner.preflight_runtime",new_callable=AsyncMock), patch("eval_harness.benchmark_runner.warm_up_configuration",new_callable=AsyncMock), patch("eval_harness.benchmark_runner.wait_for_distillation",new_callable=AsyncMock), patch("eval_harness.benchmark_runner.read_distillation_writes",new_callable=AsyncMock,return_value={}), patch.object(sys, "argv", args), patch(
                "eval_harness.benchmark_runner.build_runtime", return_value=fake_runtime
            ), patch(
                "eval_harness.benchmark_runner.prepare_runtime_for_eval",
                new_callable=AsyncMock,
                return_value={"database": "telesale", "host": "localhost", "port": 5432},
            ) as reset, patch("eval_harness.benchmark_runner.print_cli_summary"):
                await main()
            self.assertEqual(reset.await_count, 2)

    async def test_failed_reset_does_not_write_a_score_report(self):
        from eval_harness.benchmark_runner import main

        with tempfile.TemporaryDirectory() as folder:
            dataset = Path(folder) / "scenarios.json"
            dataset.write_text('{"scenarios": [{"scenario_id":"X","calls":{"call_1":{"customer_turns":["Xin chào"]}}}]}', encoding="utf-8")
            output = Path(folder) / "report.json"
            args = ["benchmark_runner", "--agent", "deep", "--scenarios",
                    str(dataset), "--out", str(output), "--btc-root", str(Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS"), "--expected-database", "telesale"]
            with patch("app.knowledge.context.capture_release",new_callable=AsyncMock,return_value={"release_id":"btc-only","manifest_hash":"btc-only"}), patch("eval_harness.benchmark_runner.preflight_runtime",new_callable=AsyncMock), patch("eval_harness.benchmark_runner.warm_up_configuration",new_callable=AsyncMock), patch("eval_harness.benchmark_runner.wait_for_distillation",new_callable=AsyncMock), patch("eval_harness.benchmark_runner.read_distillation_writes",new_callable=AsyncMock,return_value={}), patch.object(sys, "argv", args), patch(
                "eval_harness.benchmark_runner.build_runtime",
                return_value=SimpleNamespace(tools=SimpleNamespace(), memory=SimpleNamespace()),
            ), patch(
                "eval_harness.benchmark_runner.prepare_runtime_for_eval",
                new_callable=AsyncMock, side_effect=RuntimeError("reset failed"),
            ), patch("eval_harness.benchmark_runner.print_cli_summary"):
                with self.assertRaisesRegex(RuntimeError, "configuration_failed"):
                    await main()
            self.assertFalse(output.exists())

    async def test_prepare_rejects_mismatched_mcp_databases_before_reset(self):
        from eval_harness.benchmark_runner import prepare_runtime_for_eval

        class Tools:
            async def database_identity(self, service):
                return {"database": "telesale" if service != "order" else "other",
                        "host": "postgres", "port": 5432,
                        "server_started_at": "2026-11-01T00:00:00+00:00"}

        runtime = SimpleNamespace(tools=Tools())
        with self.assertRaisesRegex(RuntimeError, "Cannot verify order"):
            await prepare_runtime_for_eval(runtime, SimpleNamespace(app_env="test"),
                expected_database="telesale", release={})

    async def test_reset_rejects_production_before_connecting(self):
        from eval_harness.runtime_reset import reset_runtime_database

        with self.assertRaisesRegex(ValueError, "production"):
            await reset_runtime_database("postgresql://invalid", app_env="production")

    @unittest.skipUnless(os.getenv("EVAL_RESET_TEST_DB") == "1", "requires isolated PostgreSQL")
    async def test_reset_clears_runtime_rows_but_keeps_schema_and_store_migrations(self):
        from eval_harness.runtime_reset import reset_runtime_database

        source = make_url(database_url(Settings()))
        admin = await asyncpg.connect(
            source.set(database="postgres").render_as_string(hide_password=False)
            .replace("postgresql+asyncpg://", "postgresql://", 1)
        )
        name = "telesale_eval_reset_" + uuid4().hex[:12]
        try:
            await admin.execute(f'CREATE DATABASE "{name}"')
            target_url = source.set(database=name).render_as_string(hide_password=False)
            target_dsn = target_url.replace("postgresql+asyncpg://", "postgresql://", 1)
            target = await asyncpg.connect(target_dsn)
            try:
                await target.execute("CREATE SCHEMA runtime")
                await target.execute("CREATE SEQUENCE runtime.tool_order_seq START WITH 600001")
                await target.execute("CREATE TABLE runtime.store_migrations (version integer PRIMARY KEY)")
                await target.execute("CREATE TABLE runtime.tool_orders (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY)")
                await target.execute("CREATE TABLE runtime.store (id integer PRIMARY KEY)")
                await target.execute("CREATE TABLE runtime.demo_users (id integer PRIMARY KEY)")
                await target.execute("INSERT INTO runtime.demo_users VALUES (42)")
                await target.execute("INSERT INTO runtime.store_migrations VALUES (1)")
                await target.execute("INSERT INTO runtime.tool_orders DEFAULT VALUES")
                await target.execute("INSERT INTO runtime.store VALUES (7)")
                await target.fetchval("SELECT nextval('runtime.tool_order_seq')")

                with self.assertRaisesRegex(ValueError, "server"):
                    await reset_runtime_database(target_dsn, expected_database=name,
                                                 expected_server_started_at="wrong-server",
                                                 app_env="test")
                self.assertEqual(await target.fetchval(
                    "SELECT count(*) FROM runtime.tool_orders"), 1)

                await reset_runtime_database(target_dsn, expected_database=name, app_env="test")

                self.assertEqual(await target.fetchval("SELECT count(*) FROM runtime.tool_orders"), 0)
                self.assertEqual(await target.fetchval("SELECT count(*) FROM runtime.store"), 0)
                self.assertEqual(await target.fetchval("SELECT count(*) FROM runtime.store_migrations"), 1)
                self.assertEqual(await target.fetchval("SELECT id FROM runtime.demo_users"), 42)
                self.assertEqual(await target.fetchval("SELECT nextval('runtime.tool_order_seq')"), 600001)
                self.assertEqual(await target.fetchval(
                    "INSERT INTO runtime.tool_orders DEFAULT VALUES RETURNING id"), 1)
            finally:
                await target.close()
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.close()

    @unittest.skipUnless(os.getenv("EVAL_RESET_TEST_DB") == "1", "requires isolated PostgreSQL")
    async def test_reset_refuses_to_touch_a_different_database(self):
        from eval_harness.runtime_reset import reset_runtime_database

        source = make_url(database_url(Settings()))
        with self.assertRaisesRegex(ValueError, "database identity"):
            await reset_runtime_database(
                source.render_as_string(hide_password=False),
                expected_database="telesale_eval_other", app_env="test",
            )


class OfflineResetScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_sql_preserves_sources_knowledge_and_migration_metadata(self):
        from contextlib import asynccontextmanager
        from datetime import datetime, timezone
        from eval_harness.runtime_reset import reset_runtime_database
        started=datetime(2026,1,1,tzinfo=timezone.utc)
        @asynccontextmanager
        async def transaction():
            yield
        async def fetchval(sql):
            if 'current_database' in sql:
                return 'telesale'
            if 'pg_postmaster' in sql:
                return started
            return True
        connection=SimpleNamespace(transaction=transaction,fetchval=fetchval,
            fetchrow=AsyncMock(return_value={'host':'10.0.0.2','port':5432}),
            fetch=AsyncMock(return_value=[{'tablename':x} for x in ('store_migrations','demo_users','turns','tool_orders')]),
            execute=AsyncMock(),close=AsyncMock())
        with patch('asyncpg.connect',new_callable=AsyncMock,return_value=connection):
            await reset_runtime_database('postgresql://offline',expected_database='telesale',
                expected_server_started_at=started.isoformat(),expected_server_host='10.0.0.2',
                expected_server_port=5432,app_env='test')
        sql=' '.join(call.args[0] for call in connection.execute.call_args_list)
        self.assertIn('runtime."turns"',sql)
        for forbidden in ('btc_source','knowledge.','store_migrations','demo_users'):
            self.assertNotIn(forbidden,sql)
