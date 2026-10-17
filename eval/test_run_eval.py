"""The runner must trace harness output without feeding answer labels to it."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from eval.catalog_search_benchmark import catalog_search_metrics
from eval.run_eval import _claims, run
from app.schemas.agent import TextTurnResponse


class _Memory:
    include_prior = True


class _Runtime:
    def __init__(self):
        self.memory = _Memory()
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return TextTurnResponse(client_msg_id=request.client_msg_id,
                                session_id=request.session_id,
                                agent_text="Dạ, em kiểm tra ạ.")

    def state_for(self, request):
        return {"request": request, "profile": {}, "tool_calls": [],
                "memory_writes": []}


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
                out=output, isolated_db=False), runtime))
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


if __name__ == "__main__":
    unittest.main()
