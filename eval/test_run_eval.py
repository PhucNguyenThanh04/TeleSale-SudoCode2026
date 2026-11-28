
from eval_harness.test_support import VoiceLifecycleStub
import asyncio
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from eval.catalog_search_benchmark import catalog_search_metrics
from eval.run_eval import _claims, _facts_used, _require_eval_database, _trace_args, run
from app.agent.guardrails.diagnostics import rejected_draft
from app.configs import Settings
from app.schemas.agent import TextTurnResponse, MemoryUpdate


class _Memory:
    include_prior = True


class _Runtime(VoiceLifecycleStub):
    def __init__(self, database="telesale_eval"):
        self.memory = _Memory()
        self.tools = self
        self.database = database
        self.requests = []

    async def database_identity(self, service):
        return {"database": self.database, "host": "eval-postgres", "port": 5432, "server_started_at":"start"}

    async def knowledge_release(self):
        return {"release_id":"btc-only","manifest_hash":"btc-only"}

    async def run(self, request):
        self.requests.append(request)
        return TextTurnResponse(client_msg_id=request.client_msg_id,
                                session_id=request.session_id,
                                agent_text="Dạ, em kiểm tra ạ.",
                                memory_update=MemoryUpdate(turn_saved=True, status='completed'))

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
    def test_btc_cli_uses_submission_stream_without_mode_selectors(self):
        from eval.run_eval import main
        for extra in ([],):
            with patch('eval.run_eval.run', new_callable=AsyncMock, return_value=0) as execute, \
                 patch('sys.argv', ['run_eval.py', '--scenarios', 'unused', '--btc-root', 'unused',
                                    '--config', 'full', '--out', 'unused.jsonl', *extra]):
                main()
                self.assertFalse(hasattr(execute.call_args.args[0], 'delivery_mode'))

    def test_unexpected_exit_is_not_success_for_single_configuration(self):
        from eval.run_eval import main

        with patch('eval.run_eval.capture_release', AsyncMock(side_effect=SystemExit(0))), \
             patch('eval_harness.btc_release.prepare_btc_release', return_value=Path('unused')), \
             patch('eval.run_eval.load_scenarios', return_value={}), \
             patch('sys.argv', ['run_eval.py', '--scenarios', 'unused', '--btc-root', 'unused',
                                '--config', 'full', '--out', 'unused.jsonl', '--isolated-db']):
            with self.assertRaises(SystemExit) as stopped:
                main()
        self.assertEqual(stopped.exception.code, 1)

    def setUp(self):
        settings = Settings(_env_file=None, app_env='test', llm_api_key='offline', llm_model='offline',
                            database_url='postgresql://offline@127.0.0.1/telesale_eval')
        for target, kwargs in (
            ("eval.run_eval.get_settings", dict(return_value=settings)),
            ("eval.run_eval.capture_release", dict(new_callable=AsyncMock,return_value={"release_id":"btc-only","manifest_hash":"btc-only"})),
            ("eval_harness.benchmark_runner.warm_up_configuration",dict(new_callable=AsyncMock)),
            ("eval_harness.benchmark_runner.build_runtime",dict(return_value=_Runtime())),
            ("eval_harness.benchmark_runner.probe_runner_database",dict(new_callable=AsyncMock,return_value={"database":"telesale_eval","host":"eval-postgres","port":5432,"server_started_at":"start"})),
            ("eval_harness.benchmark_runner.reset_runtime_database",dict(new_callable=AsyncMock)),
            ("eval_harness.benchmark_runner.wait_for_distillation",dict(new_callable=AsyncMock)),
            ("eval_harness.benchmark_runner.read_distillation_writes",dict(new_callable=AsyncMock,return_value={})),
        ):
            patcher=patch(target,**kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        env=patch.dict("os.environ",{"EVAL_EXPECTED_DATABASE":"telesale_eval"})
        env.start()
        self.addCleanup(env.stop)

    def test_prior_scoped_fact_used_is_counted_without_customer_identifier(self):
        state = {"request": SimpleNamespace(session_id="current-session"),
                 "profile": {}, "tool_calls": [], "scoped_facts": {"product": {
                     "SKU-ALPHA": {"preferred_color": {"value": "xanh",
                         "source": "old-session:turn-1"}}}}}
        self.assertEqual(_facts_used("SKU-ALPHA màu xanh vẫn phù hợp", state),
                         ["preferred_color"])

    def test_btc_cli_can_repeat_a_configuration_under_a_new_output_name(self):
        root = Path(__file__).resolve().parents[2] / 'BTC-Data-Vong1-TEAMS'
        with tempfile.TemporaryDirectory() as folder:
            for name in ('first', 'retry'):
                out = Path(folder) / f'{name}.jsonl'
                turns = asyncio.run(run(SimpleNamespace(btc_root=root, config='full', out=out,
                    scenarios=root / 'test_set' / 'public_sample', isolated_db=True), _Runtime()))
                self.assertGreater(turns, 0)
            self.assertEqual(len(list(Path(folder).glob('*.extraction.jsonl'))), 2)

    def test_full_exports_unanswered_questions_for_knowledge_review(self):
        class Runtime(_Runtime):
            async def run(self, request):
                response = await super().run(request)
                return response.model_copy(update={'agent_text': 'Hiện em chưa có thông tin về sản phẩm này.'})

        root = Path(__file__).resolve().parents[2] / 'BTC-Data-Vong1-TEAMS'
        with tempfile.TemporaryDirectory() as folder:
            for config in ('full', 'baseline_no_memory'):
                out = Path(folder) / f'{config}.jsonl'
                count = asyncio.run(run(SimpleNamespace(btc_root=root, config=config, out=out,
                    scenarios=root / 'test_set' / 'public_sample', isolated_db=True), Runtime()))
                gaps = out.with_suffix('.knowledge-gaps.json')
                if config == 'full':
                    result = json.loads(gaps.read_text())
                    self.assertEqual(len(result['candidates']), count)
                    self.assertEqual(result['candidates'][0]['event']['signal'], 'fallback')
                    self.assertTrue(result['candidates'][0]['event']['question'])
                else:
                    self.assertFalse(gaps.exists())

    def test_interrupted_knowledge_review_resumes_from_saved_full(self):
        from app.agent.harness.observability import log_event
        from eval_harness import knowledge_followup as followup

        class Runtime(_Runtime):
            async def run(self, request):
                result = await super().run(request)
                log_event(request, 'execution', 'phase_result', phase='model_invocation',
                          invocation='initial', status='succeeded', version=1)
                log_event(request, 'execution', 'phase_result', phase='postprocess', status='succeeded', version=1)
                return result.model_copy(update={'agent_text': 'Hiện em chưa có thông tin.'})

        class Transaction:
            async def __aenter__(self):
                return SimpleNamespace(get=AsyncMock(return_value={'release_id': 'btc-only'}))

            async def __aexit__(self, *args):
                return None

        settings = Settings(_env_file=None, app_env='test', llm_api_key='offline', llm_model='offline',
                            knowledge_enabled=True, database_url='postgresql://offline@127.0.0.1/telesale_eval')
        database = {'database': 'telesale_eval', 'host': 'eval-postgres', 'port': 5432,
                    'server_started_at': 'start'}
        repo = SimpleNamespace(database_identity=AsyncMock(return_value=database),
                               transaction=Transaction, close=AsyncMock())
        proposal = AsyncMock(side_effect=[RuntimeError('worker interrupted'), {'proposed': ['existing-job']}])
        root = Path(__file__).resolve().parents[2] / 'BTC-Data-Vong1-TEAMS'
        with tempfile.TemporaryDirectory() as folder, \
             patch('eval.run_eval.get_settings', return_value=settings), \
             patch.object(followup, 'configured_url', return_value='configured'), \
             patch.object(followup, 'KnowledgeRepo', return_value=repo), \
             patch.object(followup, 'propose', proposal):
            out = Path(folder) / 'full.jsonl'
            args = SimpleNamespace(btc_root=root, config='full', out=out,
                scenarios=root / 'test_set' / 'public_sample', isolated_db=True)
            with self.assertRaisesRegex(RuntimeError, 'worker interrupted'):
                asyncio.run(run(args, Runtime()))
            before = out.read_bytes()
            gaps = out.with_suffix('.knowledge-gaps.json')
            self.assertEqual(json.loads(gaps.read_text())['status'], 'proposal_failed')
            self.assertEqual(asyncio.run(followup.detect_after_full(out, settings)), (gaps, 'proposals_ready'))
            self.assertEqual(json.loads(gaps.read_text())['proposals'], {'proposed': ['existing-job']})
            self.assertEqual(asyncio.run(followup.detect_after_full(out, settings)), (gaps, 'proposals_ready'))
            self.assertEqual(proposal.await_count, 2)
            self.assertEqual(out.read_bytes(), before)

    def test_price_claim_keeps_thousands_separators(self):
        claims = [{k:v for k,v in c.items() if k != "source"} for c in _claims("Giá hôm nay là 4.890.000đ. Em kiểm tra tiếp ạ.", [])]
        self.assertIn({"field": "price_vnd", "value": 4890000,
                       "text": "Giá hôm nay là 4.890.000đ"}, claims)
        self.assertIn({"field": "promo_active", "value": False,
                       "text": "Đã hết chương trình giảm giá"},
                      [{k:v for k,v in c.items() if k != "source"} for c in _claims("Đã hết chương trình giảm giá", [])])
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
                btc_root=scenario_dir.parents[1], scenarios=scenario_dir, config="baseline_no_memory",
                out=output, isolated_db=True), runtime))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            report = json.loads(output.with_suffix(".report.json").read_text(
                encoding="utf-8"))
        self.assertEqual(count, len(rows))
        self.assertEqual(report["catalog_search"]["turns"], count)
        self.assertEqual(report['btc_contract']['version'], 'explicit_btc_root')
        self.assertEqual(report['conversation_measurement']['delivery_mode'], 'text')
        self.assertFalse(report['conversation_measurement']['ttft_is_proxy'])
        self.assertTrue(all(request.delivery_mode == 'text' for request in runtime.requests))
        self.assertEqual(report["catalog_search"]["total_calls"], 0)
        self.assertEqual(report["database_identity"], {
            "database": "telesale_eval", "host": "eval-postgres", "port": 5432, "server_started_at":"start"})
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

    def test_stage_sidecar_has_one_safe_item_per_turn(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "trace.jsonl"
            asyncio.run(run(SimpleNamespace(btc_root=scenario_dir.parents[1], scenarios=scenario_dir, config="full",
                                          out=output, isolated_db=True), _Runtime()))
            stages = json.loads(output.with_suffix(".stages.json").read_text(
                encoding="utf-8"))
            rows = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(stages), len(rows))
        self.assertEqual((stages[0]["scenario_id"], stages[0]["call"], stages[0]["turn"]),
                         ("SAMPLE-01", "call_1", 1))
        self.assertEqual(stages[0]["config"], "full")
        self.assertTrue(stages[0]["run_id"])
        self.assertNotIn("facts_established", json.dumps(stages))

    def test_handoff_trace_preserves_brief_presence_without_personal_text(self):
        args = {"brief": {"customer_phone": "0912345678", "customer_name": "Lan",
                          "escalation_reason": "khac",
                          "conversation_summary": "Chị Lan ở 12 đường X cần gặp nhân viên",
                          "product_advised": "SKU-OTHER", "price_quoted_vnd": 4900000,
                          "open_questions": ["Chị Lan muốn biết địa chỉ: 12 đường X"],
                          "next_action": "Gọi chị Lan theo 0912345678",
                          "generated_at": "2026-10-22T00:00:00Z"}}
        traced = _trace_args(args)
        self.assertTrue(all(traced["brief"].get(key) not in (None, "", [])
                            for key in ("conversation_summary", "open_questions",
                                        "next_action", "escalation_reason")))
        self.assertEqual(traced["brief"]["product_advised"], "SKU-OTHER")
        serialized = json.dumps(traced, ensure_ascii=False)
        for private in ("0912345678", "Lan", "12 đường X"):
            self.assertNotIn(private, serialized)
        scorer = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                    "BTC-Data-Vong1-TEAMS" / "eval" / "reference_eval.py"))
        passed, reasons = scorer["check_call"](
            {"success_if": {"tool_called": "handoff.transfer",
                            "brief_must_contain": ["escalation_reason", "conversation_summary",
                                                   "open_questions", "next_action"]}},
            [{"agent_text": "Đã bàn giao", "tool_calls": [{"name": "handoff.transfer",
                                                   "args": traced}]}])
        self.assertTrue(passed, reasons)

    def test_sidecar_write_failure_marks_single_run_failed(self):
        from eval_harness.official_pipeline import atomic_json as real_atomic
        btc=Path(__file__).resolve().parents[2]/"BTC-Data-Vong1-TEAMS"
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/"trace.jsonl"
            def write(path,value):
                if str(path).endswith(".events.json"):
                    raise OSError("synthetic disk error")
                real_atomic(path,value)
            with patch("eval_harness.turn_diagnostics.atomic_json",side_effect=write):
                with self.assertRaises(RuntimeError):
                    asyncio.run(run(SimpleNamespace(scenarios=btc/"test_set/public_sample",btc_root=btc,
                        config="full",out=output,isolated_db=True),_Runtime()))
            self.assertEqual(json.loads(output.with_suffix(".report.json").read_text())["status"],"failed")

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
                btc_root=scenario_dir.parents[1], scenarios=scenario_dir, config="full", out=output,
                isolated_db=True), _BlockedRuntime()))
            events_path = output.with_suffix(".events.json")
            raw = events_path.read_text(encoding="utf-8")
            events = json.loads(raw)
        self.assertTrue(events)
        self.assertEqual(events[0]["checks"][0]["reason"], "price_without_quote")
        self.assertEqual(set(events[0]["checks"][0]), {"reason"})
        self.assertNotIn("agent_draft", raw)
        self.assertNotIn("source_evidence", raw)
        self.assertNotIn("0912345678", raw)

    def test_failed_stream_report_keeps_safe_model_error_and_verification_reason(self):
        from app.agent.harness.observability import log_event

        class Runtime(_Runtime):
            async def run(self, request):
                log_event(request, 'execution', 'phase_result', phase='model_invocation',
                          status='failed', invocation='repair', error_type='BadRequestError',
                          error_code='unsupported_parameter', error_param='private provider detail')
                log_event(request, 'verify', 'grounding_checked', accepted=False, reason='price_without_quote')
                raise RuntimeError('private model draft')

        root = Path(__file__).resolve().parents[2] / 'BTC-Data-Vong1-TEAMS'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'trace.jsonl'
            with self.assertRaisesRegex(RuntimeError, 'configuration_failed'):
                asyncio.run(run(SimpleNamespace(btc_root=root, config='full', out=output,
                    scenarios=root / 'test_set' / 'public_sample', isolated_db=True), Runtime()))
            raw = output.with_suffix('.report.json').read_text()
        details = json.loads(raw)
        self.assertEqual(details['verification_rejections'], ['price_without_quote'])
        self.assertEqual(details['execution_error'], {
            'version': 1, 'phase': 'model_invocation', 'status': 'failed', 'invocation': 'repair',
            'error_type': 'BadRequestError', 'error_code': 'unsupported_parameter', 'error_param': 'unknown',
        })
        self.assertNotIn('private model draft', raw)
        self.assertNotIn('private provider detail', raw)

    def test_live_database_name_is_checked_before_any_turn(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "trace.jsonl"
            runtime = _Runtime(database="telesale")
            with self.assertRaisesRegex(RuntimeError, "configuration_failed"):
                asyncio.run(run(SimpleNamespace(
                    btc_root=scenario_dir.parents[1], scenarios=scenario_dir, config="full", out=output,
                    isolated_db=True), runtime))
            self.assertEqual(runtime.requests, [])
            self.assertFalse(output.exists())

    def test_explicit_target_replaces_name_suffix_allowlist(self):
        for name in ("telesale_evaluation", "medieval", "telesale"):
            with self.assertRaisesRegex(RuntimeError, "Cannot verify catalog"):
                asyncio.run(_require_eval_database(_Runtime(database=name),True))
        with patch("eval_harness.benchmark_runner.probe_runner_database",new_callable=AsyncMock,return_value={"database":"telesale","host":"eval-postgres","port":5432,"server_started_at":"start"}):
            result=asyncio.run(_require_eval_database(_Runtime(database="telesale"),True,
            expected_database="telesale",release={"release_id":"btc-only","manifest_hash":"btc-only"}))
        self.assertEqual(result["database"],"telesale")
        with patch.dict("os.environ",{"EVAL_EXPECTED_DATABASE":""}):
            with self.assertRaisesRegex(ValueError,"expected-database"):
                asyncio.run(_require_eval_database(_Runtime(),True))

    def test_unavailable_database_probe_fails_closed(self):
        runtime = _Runtime()

        async def unavailable(_service):
            return {"error": "mcp_tool_error"}

        runtime.database_identity = unavailable
        with self.assertRaisesRegex(RuntimeError, "Cannot verify catalog"):
            asyncio.run(_require_eval_database(runtime, True))
        self.assertEqual(runtime.requests, [])

    def test_missing_isolated_flag_is_rejected_even_for_eval_database(self):
        scenario_dir = Path(__file__).resolve().parents[2] / "BTC-Data-Vong1-TEAMS" / \
            "test_set" / "public_sample"
        with tempfile.TemporaryDirectory() as folder:
            runtime = _Runtime(database="telesale_eval")
            with self.assertRaisesRegex(ValueError, "--isolated-db"):
                asyncio.run(run(SimpleNamespace(
                    btc_root=scenario_dir.parents[1], scenarios=scenario_dir, config="full",
                    out=Path(folder) / "trace.jsonl", isolated_db=False), runtime))
            self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
