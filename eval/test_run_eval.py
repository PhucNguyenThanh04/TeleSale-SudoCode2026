"""The runner must trace harness output without feeding answer labels to it."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from eval.catalog_search_benchmark import catalog_search_metrics
from eval.run_eval import _claims, run
from app.agent.guardrails.diagnostics import rejected_draft
from app.schemas.agent import TextTurnResponse


class _Memory:
    include_prior = True


class _Runtime:
    def __init__(self, database="telesale_eval"):
        self.memory = _Memory()
        self.tools = self
        self.database = database
        self.requests = []

    async def database_identity(self, service):
        return {"database": self.database, "host": "eval-postgres", "port": 5432,
                "server_address": "172.30.0.2", "server_port": 5432}

    async def run(self, request):
        self.requests.append(request)
        return TextTurnResponse(client_msg_id=request.client_msg_id,
                                session_id=request.session_id,
                                agent_text="Dạ, em kiểm tra ạ.")

    def state_for(self, request):
        return {"request": request, "profile": {}, "tool_calls": [],
                "memory_writes": []}


class _BlockedRuntime(_Runtime):
    def state_for(self, request):
        state = super().state_for(request)
        state.update({"agent_draft": "Giá 4.890.000đ. Gọi 0912345678.",
                      "safe_text": request.text})
        state["verifier_events"] = [rejected_draft(state, "price_without_quote")]
        return state


class EvalRunnerTest(unittest.TestCase):
    def test_price_claim_keeps_thousands_separators(self):
        claims = _claims("Giá hôm nay là 4.890.000đ. Em kiểm tra tiếp ạ.", [])
        self.assertIn({"field": "price_vnd", "value": 4890000,
                       "text": "Giá hôm nay là 4.890.000đ"}, claims)
        self.assertIn({"field": "promo_active", "value": False,
                       "text": "Đã hết chương trình giảm giá"},
                      _claims("Đã hết chương trình giảm giá", []))
        claims = _claims("Giá 5.490.000đ, miễn phí ship đến Quận 7", [])
        self.assertEqual([item["value"] for item in claims if item["field"] == "price_vnd"],
                         [5490000])

    def test_real_turns_use_business_date_and_exclude_labels(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "trace.jsonl"
            runtime = _Runtime()
            count = asyncio.run(run(SimpleNamespace(
                scenarios=scenario_dir, config="baseline_no_memory",
                out=output, isolated_db=True), runtime))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            report = json.loads(output.with_suffix(".report.json").read_text(
                encoding="utf-8"))
        self.assertEqual(count, len(rows))
        self.assertEqual(report["catalog_search"]["turns"], count)
        self.assertEqual(report["catalog_search"]["total_calls"], 0)
        self.assertFalse(runtime.memory.include_prior)
        self.assertTrue(all(row["agent_text"] == "Dạ, em kiểm tra ạ." for row in rows))
        self.assertTrue(all("facts_established" not in request.model_dump()
                            and "expected_outcome" not in request.model_dump()
                            for request in runtime.requests))
        sample = next(row for row in rows if row["scenario_id"] == "SAMPLE-01"
                      and row["call"] == "call_2")
        request = next(item for item in runtime.requests
                       if str(item.session_id) == str(runtime.requests[4].session_id))
        self.assertEqual(request.on.isoformat(), "2026-10-17")
        self.assertEqual(sample["latency"]["ttft_ms"], sample["latency"]["total_ms"])

    def test_catalog_search_metric_counts_each_turn(self):
        rows = [{"tool_calls": [{"name": "catalog.search"}]},
                {"tool_calls": [{"name": "catalog.search"},
                                {"name": "catalog.search"}]},
                {"tool_calls": [{"name": "inventory.check"}]}]
        metric = catalog_search_metrics(rows)
        self.assertEqual(metric["calls_per_turn"], [1, 2, 0])
        self.assertEqual(metric["one_search_turns"], 1)
        self.assertEqual(metric["one_search_rate_among_search_turns"], 0.5)

    def test_rejected_drafts_go_to_redacted_events_sidecar(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "trace.jsonl"
            asyncio.run(run(SimpleNamespace(
                scenarios=scenario_dir, config="full", out=output,
                isolated_db=True), _BlockedRuntime()))
            events_path = output.with_suffix(".events.json")
            raw = events_path.read_text(encoding="utf-8")
            events = json.loads(raw)
        self.assertTrue(events)
        self.assertEqual(events[0]["checks"][0]["reason"], "price_without_quote")
        self.assertIn("claims", events[0]["checks"][0])
        self.assertIn("source_evidence", events[0]["checks"][0])
        self.assertNotIn("0912345678", raw)

    def test_live_database_name_is_checked_before_any_turn(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "trace.jsonl"
            runtime = _Runtime(database="telesale")
            with self.assertRaisesRegex(RuntimeError, "not in the eval allowlist"):
                asyncio.run(run(SimpleNamespace(
                    scenarios=scenario_dir, config="full", out=output,
                    isolated_db=True), runtime))
            self.assertEqual(runtime.requests, [])
            self.assertFalse(output.exists())

    def test_missing_isolated_flag_is_rejected_even_for_eval_database(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            runtime = _Runtime(database="telesale_eval")
            with self.assertRaisesRegex(ValueError, "--isolated-db"):
                asyncio.run(run(SimpleNamespace(
                    scenarios=scenario_dir, config="full",
                    out=Path(folder) / "trace.jsonl", isolated_db=False), runtime))
            self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
