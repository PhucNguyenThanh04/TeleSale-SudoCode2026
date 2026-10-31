"""Unit tests for Eval Harness Scorer and Extractor."""

import unittest
from datetime import date
from eval_harness.extractor import extract_questions, extract_claims, build_trace_row
from app.schemas.trace import AgentTraceLine
from eval_harness.scorer import (
    pct,
    p95,
    args_match,
    evaluate_task_success,
    evaluate_memory_metrics,
    evaluate_hallucination,
    evaluate_guardrails,
    evaluate_diagnostics_and_latency,
)


class TestEvalHarness(unittest.TestCase):
    def test_runner_rejects_retired_memory_variants_before_loading_scenarios(self):
        import subprocess
        import sys

        result = subprocess.run([sys.executable, "-m", "eval_harness.benchmark_runner",
                                 "--agent", "deep", "--variant", "shadow",
                                 "--scenarios", "/does/not/exist"],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_prior_fact_is_not_used_just_because_it_was_loaded(self):
        from eval_harness.reference_adapter import facts_used
        self.assertEqual(facts_used("Dạ em chào chị.", [],
                                    {"room_area_m2": {"value": 25}}), [])

    def test_prior_fact_used_in_answer(self):
        from eval_harness.reference_adapter import facts_used
        self.assertEqual(facts_used("Phòng 25m² mình dùng AirPure X được ạ.", [],
                                    {"room_area_m2": {"value": 25}}),
                         ["room_area_m2"])

    def test_scoped_fact_used_in_tool_argument_is_counted(self):
        from eval_harness.reference_adapter import facts_used
        self.assertEqual(facts_used("Em kiểm tra mẫu trước đó ạ.", [
            {"name": "catalog.search", "args": {"sku": "SKU-AP-X"}}
        ], {}, {"product": {"SKU-AP-X": {
            "product_advised": {"value": "SKU-AP-X"}}}}), ["product_advised"])

    def test_reference_trace_has_required_fields_and_brief_latency(self):
        from eval_harness.reference_adapter import trace_line
        row = trace_line("run-1", "full", "SAMPLE-01", "call_2", 1,
                         "Chị gọi lại", "Dạ vâng", [], [], [], 12, 340,
                         "clean")
        self.assertEqual(row["customer_text"], "Chị gọi lại")
        self.assertEqual(row["call_brief_latency_ms"], 340)
        AgentTraceLine.model_validate(row)

    def test_trace_memory_source_uses_call_turn_not_internal_uuid(self):
        from eval_harness.reference_adapter import trace_line
        row = trace_line("run-1", "full", "SAMPLE-01", "call_1", 2,
            "Phòng 25 m²", "Dạ", [], [{"key": "room_area_m2", "value": 25,
            "op": "set", "customer_id": "C1",
            "source": "aaaaaaaa-1111-2222-3333-934400000000",
            "fact_id": "aaaaaaaa-1111-2222-3333-934400000000"}], [], 10, None,
            "clean")
        self.assertEqual(row["memory_writes"][0]["source"], "call_1#turn2")
        self.assertNotIn("fact_id", row["memory_writes"][0])

    def test_call_dates_accumulate_from_previous_call(self):
        from eval_harness.benchmark_runner import scenario_call_date
        calls = {"call_1": {"call_date": "2026-09-25"},
                 "call_2": {"days_later": 20}}
        self.assertEqual(scenario_call_date(calls, "call_2", date(2026, 10, 15)),
                         date(2026, 10, 15))

    def test_tool_price_not_reported_as_spoken_claim(self):
        self.assertEqual(extract_claims("Dạ em sẽ kiểm tra giá.", [
            {"name": "order.create", "args": {"sku": "SKU-AP-X", "price_vnd": 4200000}}
        ]), [])

    def test_spoken_price_is_reported_as_claim(self):
        claims = extract_claims("Giá là 4.890.000 đồng ạ.", [])
        self.assertIn({"field": "price_vnd", "value": 4890000,
                       "source": "text"}, claims)

    def test_baseline_runtime_disables_prior_memory_without_changing_identity(self):
        from eval_harness.benchmark_runner import make_baseline_runtime

        class Memory:
            include_prior = True
            namespace = ""

        class Runtime:
            memory = Memory()

        runtime = Runtime()
        result = make_baseline_runtime(runtime)
        self.assertIs(result, runtime)
        self.assertFalse(runtime.memory.include_prior)
        self.assertEqual(runtime.memory.namespace, "baseline")

    def test_trace_writer_outputs_one_json_object_per_line(self):
        import json
        import tempfile
        from pathlib import Path
        from eval_harness.reference_adapter import write_jsonl

        rows = {("SAMPLE-01", "call_2"): [
            {"scenario_id": "SAMPLE-01", "call": "call_2", "turn": 1}]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            write_jsonl(rows, path)
            self.assertEqual(json.loads(path.read_text().strip())["turn"], 1)


class TestScenarioInput(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_error_text_is_not_copied_into_public_trace(self):
        from eval_harness.benchmark_runner import run_scenario_call

        class Runtime:
            async def run(self, request):
                raise RuntimeError("private customer detail")

        rows = await run_scenario_call(Runtime(), "SAMPLE-01", "call_1",
            {"customer_turns": ["Xin chào"]}, date(2026, 10, 15), "0900000000")
        self.assertIn("RuntimeError", rows[0]["agent_text"])
        self.assertNotIn("private customer detail", rows[0]["agent_text"])

    async def test_worker_finishes_before_next_turn_in_same_call(self):
        from types import SimpleNamespace
        from eval_harness.benchmark_runner import run_scenario_stream

        completed = []

        class Runtime:
            async def run(self, request):
                if request.text == "Lượt hai":
                    self_assert.assertEqual(len(completed), 1)
                return SimpleNamespace(agent_text="Dạ.", call_brief=None)

            def state_for(self, request):
                return {"profile": {}, "tool_calls": [], "memory_writes": []}

        self_assert = self

        async def wait(source_id):
            completed.append(source_id)

        await run_scenario_stream(Runtime(), {"SAMPLE-01": {
            "customer_phone": "0900000000", "calls": {"call_1": {
                "customer_turns": ["Lượt một", "Lượt hai"]}}}},
            wait_for_jobs=wait)
        self.assertEqual(len(completed), 2)

    async def test_background_writes_are_attributed_to_source_turn(self):
        from types import SimpleNamespace
        from eval_harness.benchmark_runner import run_scenario_stream
        class Runtime:
            memory = SimpleNamespace(langmem_primary=True)
            async def run(self, request):
                return SimpleNamespace(agent_text="Dạ em ghi nhận.", call_brief=None)
            def state_for(self, request):
                return {"profile": {}, "tool_calls": [], "memory_writes": []}
        async def wait(source_id):
            return None
        async def capture(ids):
            return {ids[0]: [{"key": "preferred_color", "value": "xanh",
                             "op": "set", "customer_id": "C1"}]}
        traces = await run_scenario_stream(Runtime(), {"SAMPLE-01": {
            "customer_phone": "0900000000", "calls": {"call_1": {
                "customer_turns": ["Tôi thích màu xanh"]}}}},
            wait_for_jobs=wait, capture_writes=capture)
        row = traces["SAMPLE-01", "call_1"][0]
        self.assertEqual(row["memory_writes"][0]["source"], "call_1#turn1")
        self.assertNotIn("_client_msg_id", row)

    async def test_asr_turn_uses_declared_channel_and_call_date(self):
        from types import SimpleNamespace
        from eval_harness.benchmark_runner import run_scenario_call

        class Runtime:
            requests = []

            async def run(self, request):
                self.requests.append(request)
                return SimpleNamespace(agent_text="Dạ em nghe.", call_brief={"latency_ms": 350})

            def state_for(self, request):
                return {"profile": {}, "tool_calls": [], "memory_writes": []}

        runtime = Runtime()
        rows = await run_scenario_call(runtime, "SAMPLE-06", "call_2",
            {"channel": "chat_fanpage", "channel_identity": "fb.x",
             "input_mode": "asr_transcript", "customer_turns_asr": ["xiao mi bon po"],
             "customer_turns": ["Xiaomi 4 Pro"]},
            date(2026, 10, 15), "0991234567", call_date=date(2026, 10, 20))
        self.assertEqual(runtime.requests[0].text, "xiao mi bon po")
        self.assertEqual(runtime.requests[0].channel_identity, "fb.x")
        self.assertEqual(runtime.requests[0].on, date(2026, 10, 20))
        self.assertEqual(rows[0]["customer_input_mode"], "asr_transcript")
        self.assertEqual(rows[0]["call_brief_latency_ms"], 350)

    def test_math_helpers(self):
        self.assertEqual(pct(5, 10), 50.0)
        self.assertIsNone(pct(5, 0))
        self.assertEqual(p95([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]), 100)
        self.assertTrue(args_match({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(args_match({"a": 1}, {"a": 2}))

    def test_extractor_questions(self):
        text = "Chào chị, phòng nhà mình rộng bao nhiêu mét vuông ạ? Chị lấy size 40 đúng không ạ?"
        qs = extract_questions(text)
        self.assertTrue(len(qs) >= 2)
        types = {q["slot"]: q["type"] for q in qs}
        self.assertEqual(types.get("room_area_m2"), "open")
        self.assertEqual(types.get("size"), "confirm")

    def test_extractor_claims(self):
        text = "Dạ máy này giá là 4.200.000 đồng, còn hàng và giao trong vòng 2 ngày nhé anh."
        tool_calls = [{"name": "order.create", "args": {"sku": "SKU-AP-X", "price_vnd": 4200000}}]
        claims = extract_claims(text, tool_calls)
        fields = {c["field"]: c["value"] for c in claims}
        self.assertEqual(fields.get("in_stock"), True)
        self.assertEqual(fields.get("delivery_days"), 2)
        self.assertEqual(fields.get("price_vnd"), 4200000)

    def test_scorer_task_success(self):
        scenarios = {
            "SC01": {
                "scenario_id": "SC01",
                "calls": {
                    "call_2": {
                        "success_if": {
                            "tool_called": "order.create",
                            "args_match": {"sku": "SKU-AP-Y", "price_vnd": 5200000},
                        }
                    }
                },
            }
        }
        trace_pass = {
            ("SC01", "call_2"): [
                {"tool_calls": [{"name": "order.create", "args": {"sku": "SKU-AP-Y", "price_vnd": 5200000}}]}
            ]
        }
        res = evaluate_task_success(scenarios, trace_pass)
        self.assertEqual(res["tsr_overall_pct"], 100.0)
        self.assertEqual(res["passed"], 1)

    def test_scorer_guardrails(self):
        scenarios = {"SC01": {"calls": {"call_1": {}}}}
        # Fake PII leak
        trace_leak = {("SC01", "call_1"): [{"agent_text": "Số CCCD của anh là 012345678901 đúng không?"}]}
        res = evaluate_guardrails(scenarios, trace_leak)
        self.assertEqual(res["total_violations"], 1)
        self.assertFalse(res["is_safe"])


if __name__ == "__main__":
    unittest.main()
