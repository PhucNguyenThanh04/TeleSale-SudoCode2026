"""Incomplete benchmark traces must remain diagnostic artifacts, not scores."""

import json
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


class TraceReadinessTests(unittest.TestCase):
    def test_missing_turn_and_memory_error_invalidate_a_run(self):
        from eval_harness.benchmark_runner import assert_trace_ready

        scenarios = {"CASE-1": {"calls": {"call_1": {
            "customer_turns": ["Một", "Hai"]}}}}
        first = {"scenario_id": "CASE-1", "call": "call_1", "turn": 1,
                 "agent_text": "Dạ", "tool_calls": []}
        second = {**first, "turn": 2}
        with self.assertRaisesRegex(RuntimeError, "coverage"):
            assert_trace_ready(scenarios, {("CASE-1", "call_1"): [first]})
        with self.assertRaisesRegex(RuntimeError, "memory"):
            assert_trace_ready(scenarios, {("CASE-1", "call_1"): [
                first, {**second, "memory_error": "job_failed"}]})
        assert_trace_ready(scenarios, {("CASE-1", "call_1"): [first, second]})


class RunnerFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_turn_keeps_trace_but_does_not_publish_score(self):
        from eval_harness.benchmark_runner import main

        class Runtime:
            memory = SimpleNamespace(include_prior=True, namespace="")

            async def run(self, request):
                if request.text == "Hai":
                    raise RuntimeError("synthetic failure")
                return SimpleNamespace(agent_text="Dạ", call_brief=None)

            def state_for(self, request):
                return {"tool_calls": [], "memory_writes": [], "profile": {},
                        "scoped_facts": {}}

        with tempfile.TemporaryDirectory() as folder:
            dataset = Path(folder) / "dataset.json"
            dataset.write_text(json.dumps({"scenarios": [{
                "scenario_id": "CASE-1", "customer_phone": "0900000000",
                "calls": {"call_1": {"customer_turns": ["Một", "Hai"]}}}]}),
                encoding="utf-8")
            report = Path(folder) / "report.json"
            args = ["benchmark_runner", "--agent", "deep", "--scenarios",
                    str(dataset), "--out", str(report), "--run-id", "case-run"]
            with patch.object(sys, "argv", args), patch(
                "eval_harness.benchmark_runner.build_runtime", return_value=Runtime()
            ), patch(
                "eval_harness.benchmark_runner.prepare_runtime_for_eval", new_callable=AsyncMock
            ), patch(
                "eval_harness.benchmark_runner.wait_for_distillation", new_callable=AsyncMock
            ), patch(
                "eval_harness.benchmark_runner.read_distillation_writes",
                new_callable=AsyncMock, return_value={}
            ):
                with self.assertRaisesRegex(RuntimeError, "turn"):
                    await main()
            self.assertTrue((Path(folder) / "report_full.jsonl").exists())
            row = json.loads((Path(folder) / "report_full.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["run_id"], "case-run-full")
            self.assertFalse(report.exists())


class DistillationWaitTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("EVAL_RESET_TEST_DB") == "1", "requires isolated PostgreSQL")
    async def test_identified_turn_requires_one_completed_job(self):
        from eval_harness.benchmark_runner import wait_for_distillation

        source = make_url(database_url(Settings()))
        admin = await asyncpg.connect(source.set(database="postgres")
                                      .render_as_string(hide_password=False)
                                      .replace("postgresql+asyncpg://", "postgresql://", 1))
        name = "telesale_eval_jobs_" + uuid4().hex[:12]
        try:
            await admin.execute(f'CREATE DATABASE "{name}"')
            dsn = source.set(database=name).render_as_string(hide_password=False)
            db = await asyncpg.connect(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
            try:
                await db.execute("CREATE SCHEMA runtime")
                await db.execute("CREATE TABLE runtime.turns (client_msg_id uuid, customer_id text)")
                await db.execute("CREATE TABLE runtime.langmem_distillation_jobs "
                                 "(source_turn_id uuid, status text)")
                known = uuid4()
                anonymous = uuid4()
                await db.execute("INSERT INTO runtime.turns VALUES ($1, 'C1'), ($2, NULL)",
                                 known, anonymous)
                with self.assertRaisesRegex(RuntimeError, "missing job"):
                    await wait_for_distillation(dsn, str(known), 0.1)
                await db.execute("INSERT INTO runtime.langmem_distillation_jobs "
                                 "VALUES ($1, 'completed')", known)
                await wait_for_distillation(dsn, str(known), 0.1)
                await wait_for_distillation(dsn, str(anonymous), 0.1)
                with self.assertRaisesRegex(RuntimeError, "missing turn"):
                    await wait_for_distillation(dsn, str(uuid4()), 0.1)
            finally:
                await db.close()
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.close()
