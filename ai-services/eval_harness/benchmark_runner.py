"""Benchmark Runner CLI for AI TeleSale SudoCode 2026.

Executes controlled 2x2 experiments (Deep/ReAct x Full/Baseline)
against the configured PostgreSQL database, four MCP servers and model.
"""

from __future__ import annotations

from copy import deepcopy
import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
import asyncpg

# Add ai-services to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agent.factory import build_runtime
from app.configs import Settings
from app.mcp_servers.mcp_shared.config import database_url
from app.schemas.agent import PrepareSessionRequest, TextTurnRequest, VoicePlaybackRequest

from eval_harness.memory_recall import evaluate_memory_recall
from eval_harness.reference_adapter import (facts_used, public_memory_writes,
                                            trace_line, write_jsonl)
from eval_harness.runtime_reset import reset_runtime_database, probe_runner_database
from eval_harness.scorer import (
    evaluate_diagnostics_and_latency,
    evaluate_guardrails,
    evaluate_hallucination,
    evaluate_memory_metrics,
    evaluate_task_success,
)

logger = logging.getLogger("eval_runner")
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

# The BTC compatibility schema requires integer ttft_ms, even without token streaming.
CONVERSATION_MEASUREMENT = {
    "lifecycle": "prepare_session -> run(voice) -> record_playback; drain_enrichment_at_call_end",
    "delivery_mode": "voice",
    "playback": "simulated_full_reply",
    "response_scope": "transcript_to_complete_reply",
    "excluded": ["prepare", "memory_finalize", "asr", "tts", "playback_duration", "http_transport"],
    "ttft_is_proxy": True,
}


def conversation_measurement(delivery_mode='voice'):
    if delivery_mode == 'voice':
        return deepcopy(CONVERSATION_MEASUREMENT)
    if delivery_mode != 'text':
        raise ValueError('unsupported_delivery_mode')
    return {
        'lifecycle': 'prepare_session -> run(text, including persistence); drain_enrichment_at_call_end',
        'delivery_mode': 'text', 'playback': 'not_applicable',
        'response_scope': 'chat_to_complete_reply',
        'excluded': ['prepare', 'memory_worker_wait', 'asr', 'tts', 'http_transport'],
        'ttft_is_proxy': False,
        'ttft_basis': 'nonstreaming_total_btc_rule_7',
    }


async def run_scenario_call(
    runtime: Any,
    scenario_id: str,
    call_name: str,
    call_spec: dict[str, Any],
    base_date: date,
    customer_phone: str,
    channel: str = "hotline",
    run_id: str = "benchmark",
    config: str = "full",
    call_date: date | None = None,
    capture_source_ids: bool = False,
    wait_for_jobs=None,
    capture_writes=None,
    on_row=None,
    rows_out: list[dict[str, Any]] | None = None,
    customer_name: str | None = None,
    safety_issues: list | None = None,
    on_turn=None, diagnostics=None, delivery_mode='voice',
) -> list[dict[str, Any]]:
    """Execute all turns of a single call in a scenario."""
    conversation_measurement(delivery_mode)
    session_id = uuid4()
    days_later = call_spec.get("days_later", 0)
    call_date = call_date or base_date + timedelta(days=days_later)
    channel = call_spec.get("channel", channel)
    channel_identity = call_spec.get("channel_identity", customer_phone)

    customer_turns = call_spec["customer_turns_asr"] if "customer_turns_asr" in call_spec else call_spec.get("customer_turns", [])
    input_mode = call_spec.get("input_mode", "asr_transcript" if "customer_turns_asr" in call_spec else "clean")
    trace_rows = rows_out if rows_out is not None else []
    source_ids: list[str] = []
    source_rows: list[dict] = []
    prior_snapshot = None
    pending_decisions = []
    prepare_ms = 0
    prepared = None
    if customer_turns:
        prepare_started = time.perf_counter()
        prepared = await runtime.prepare_session(PrepareSessionRequest(
            session_id=session_id, channel=channel, channel_identity=channel_identity, on=call_date))
        prepare_ms = round((time.perf_counter() - prepare_started) * 1000)

    for turn_idx, user_text in enumerate(customer_turns, start=1):
        turn_req = TextTurnRequest(
            client_msg_id=str(uuid4()),
            session_id=session_id,
            channel=channel,
            channel_identity=channel_identity,
            on=call_date,
            text=user_text,
            input_mode=input_mode,
            delivery_mode=delivery_mode,
        )

        print(f"[eval] {config} {call_name} turn {turn_idx}: model", flush=True)
        t_start = time.perf_counter()
        call_brief_latency = None

        from contextlib import nullcontext
        from app.mcp_servers.mcp_shared.decision_diagnostics import capture_decisions, enabled as decision_enabled, emit as decision_emit, ingest
        from app.agent.harness.observability import capture_diagnostic_events
        state, resp, runtime_error, runtime_events = {}, None, None, []
        decision_capture = None
        latency_ms = None
        memory_finalize_ms = 0
        playback_error = None
        essential_not_ready = False
        try:
            with (capture_decisions(aliases=diagnostics.decision_aliases) if diagnostics is not None and decision_enabled() else nullcontext(None)) as decision_capture, capture_diagnostic_events() as runtime_events:
                decision_emit("provenance", provenance=True)
                resp = await runtime.run(turn_req)
                latency_ms = (time.perf_counter() - t_start) * 1000.0
                # The browser acknowledges delivered characters before the same
                # runtime method commits memory. Transcript eval assumes full delivery.
                memory_started = time.perf_counter()
                commit_update = getattr(resp, 'memory_update', None)
                if delivery_mode == 'voice':
                    try:
                        commit_update = await runtime.record_playback(VoicePlaybackRequest(
                            session_id=session_id, client_msg_id=turn_req.client_msg_id,
                            channel=channel, channel_identity=channel_identity, on=call_date,
                            played_chars=len(resp.agent_text), interrupted=False))
                    except Exception as exc:
                        playback_error = type(exc).__name__
                memory_finalize_ms = (time.perf_counter() - memory_started) * 1000.0
                essential_not_ready = commit_update is not None and not commit_update.turn_saved
            state = runtime.state_for(turn_req)
            if state is None:
                raise RuntimeError("missing_turn_state")
            if delivery_mode == 'text':
                memory_finalize_ms = state.get('memory_commit_ms', 0)
            customer_name = customer_name or state.get("customer_name")
            agent_text = resp.agent_text or ""
            tool_calls = state.get("tool_calls", [])
            memory_writes = state.get("memory_writes", [])
            if prior_snapshot is None:
                prior_snapshot = deepcopy((state.get("profile", {}), state.get("scoped_facts", {})))
            from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
            facts_used_this_turn = facts_used(
                agent_text, tool_calls, *prior_snapshot,
                current_session_id=str(session_id), customer_text=user_text,
                catalog_calls=build_commerce_evidence(state))
            if turn_idx == 1 and call_name in {"call_2", "call_3"}:
                brief = getattr(prepared, "call_brief", None) or resp.call_brief
                call_brief_latency = (brief or {}).get("latency_ms")

        except Exception as exc:
            if latency_ms is None:
                latency_ms = (time.perf_counter() - t_start) * 1000.0
            runtime_error = type(exc).__name__
            agent_text = f"[ERROR: {type(exc).__name__}]"
            tool_calls = []
            memory_writes = []
            facts_used_this_turn = []

        row = trace_line(run_id, config, scenario_id, call_name, turn_idx,
                         user_text, agent_text, tool_calls, memory_writes,
                         facts_used_this_turn, latency_ms, call_brief_latency,
                         input_mode, customer_name=customer_name,
                         safety_issues=safety_issues, call_spec=call_spec)
        row["latency"].update(response_ms=int(latency_ms),
                              prepare_ms=prepare_ms if turn_idx == 1 else 0,
                              ttft_is_proxy=delivery_mode != 'text')
        if playback_error is not None:
            row["memory_error"] = "playback_failed"
        elif essential_not_ready:
            row['memory_error'] = 'essential_state_not_ready'
        if diagnostics is not None:
            diagnostics.observe(turn_req, resp, state or {}, row, runtime_events, runtime_error=runtime_error)
        if on_turn is not None and not agent_text.startswith("[ERROR:"):
            on_turn(turn_req, resp, state, row)
        source_id = str(turn_req.client_msg_id)
        if runtime_error is None and playback_error is None and not essential_not_ready:
            source_ids.append(source_id)
            source_rows.append(row)
        row['latency'].update(essential_commit_ms=round(memory_finalize_ms),
                              background_finalize_ms=0, memory_finalize_ms=round(memory_finalize_ms))
        row['memory_enrichment_status'] = 'pending' if runtime_error is None and not row.get('memory_error') else 'unavailable'
        if diagnostics is not None and decision_enabled():
            pending_decisions.append((row, decision_capture, state, source_id))
            if playback_error is not None or essential_not_ready:
                diagnostics.observe_decisions(row, decision_capture)
        if capture_source_ids:
            row["_client_msg_id"] = source_id
        trace_rows.append(row)
        status = "failed" if row.get("memory_error") or agent_text.startswith("[ERROR:") else "complete"
        print(f"[eval] {config} {call_name} turn {turn_idx}: {status}", flush=True)
        if on_row is not None:
            on_row(row)
        if playback_error is not None:
            # A following turn must never consume unconfirmed assistant history.
            raise RuntimeError("playback_failed")
        if essential_not_ready:
            raise RuntimeError('essential_state_not_ready')

    if (capture_writes is not None or wait_for_jobs is not None) and source_ids:
        ready = []
        for row, source_id in zip(source_rows, source_ids):
            if "memory_error" in row:
                continue
            background_started = time.perf_counter()
            try:
                if wait_for_jobs is not None:
                    await wait_for_jobs(source_id)
                row['memory_enrichment_status'] = 'completed' if wait_for_jobs is not None else 'pending'
                ready.append((row, source_id))
            except TimeoutError:
                row["memory_error"] = "timeout"
            except Exception as exc:
                row["memory_error"] = "job_failed"
                logger.warning("Final distillation wait failed for %s: %s",
                               source_id, type(exc).__name__)
            finally:
                elapsed = round((time.perf_counter() - background_started) * 1000)
                row['latency']['background_finalize_ms'] = elapsed
                row['latency']['memory_finalize_ms'] += elapsed
                if 'memory_error' in row:
                    row['memory_enrichment_status'] = 'failed'
        if ready and capture_writes is not None:
            try:
                final_writes = await capture_writes([sid for _, sid in ready])
                for row, source_id in ready:
                    accepted = final_writes.get(source_id, [])
                    if decision_enabled():
                        from app.mcp_servers.mcp_shared.decision_diagnostics import observe_job
                        captured = next((entry for entry in pending_decisions if entry[3] == source_id), None)
                        if captured is not None:
                            observe_job(captured[1], getattr(final_writes, 'decision_jobs', {}).get(source_id, {}), captured[2])
                    if safety_issues is not None:
                        from eval_harness.trace_evidence import inspect_redaction
                        safety_issues.extend(inspect_redaction(
                            {**row, "memory_writes": accepted},
                            {**row, "memory_writes": public_memory_writes(call_name, row["turn"], accepted, customer_name=customer_name)}, call_spec=call_spec))
                    row["memory_writes"] = public_memory_writes(call_name, row["turn"], accepted, customer_name=customer_name)
            except Exception as exc:
                for row, _ in ready:
                    row["memory_error"] = "capture_failed"
                    row['memory_enrichment_status'] = 'failed'
                logger.warning("Final distillation attribution failed for %s: %s",
                               call_name, type(exc).__name__)
    for row, captured, _, _ in pending_decisions:
        try:
            diagnostics.observe_decisions(row, captured)
        except Exception:
            diagnostics.observe_decisions(row, None)

    return trace_rows


def scenario_call_date(calls: dict[str, dict], call_name: str,
                       base_date: date) -> date:
    current = base_date
    for name, spec in sorted(calls.items()):
        current = (date.fromisoformat(spec["call_date"]) if spec.get("call_date")
                   else current + timedelta(days=spec.get("days_later", 0)))
        if name == call_name:
            return current
    raise KeyError(call_name)


def make_baseline_runtime(runtime: Any) -> Any:
    """Preserve CRM identity while isolating writes and hiding prior memory."""
    runtime.memory.include_prior = False
    return runtime


class PreflightError(RuntimeError):
    """Only fixed diagnostic codes and known service names cross the boundary."""
    def __init__(self, code, message, *, service=None):
        super().__init__(message)
        self.error_code = code
        self.service = service


async def preflight_runtime(runtime: Any, settings: Settings, *,
                            expected_database: str, release: dict) -> dict:
    """Read-only checks; target is supplied by the operator, never inferred."""
    if settings.app_env == "production" or not expected_database:
        raise ValueError("Non-production --expected-database is required")
    identities = []
    for service in ("catalog", "order", "memory", "knowledge"):
        identity = await runtime.tools.database_identity(service)
        if (not isinstance(identity, dict) or identity.get("error") or
                identity.get("database") != expected_database or
                not isinstance(identity.get("host"), str) or not identity["host"] or
                type(identity.get("port")) is not int or not identity.get("server_started_at")):
            raise PreflightError("mcp_database_identity_unavailable",
                f"Cannot verify {service} MCP database identity", service=service)
        identities.append(identity)
        if identity != identities[0]:
            raise PreflightError("mcp_database_identity_mismatch", "MCP services point to different databases", service=service)
    runner_identity = await probe_runner_database(database_url(settings))
    if runner_identity != identities[0]:
        raise PreflightError("runner_database_identity_mismatch", "runner_database_identity_mismatch")
    try:
        served = await runtime.tools.knowledge_release()
    except Exception:
        raise PreflightError("knowledge_release_unavailable", "Knowledge release is unavailable", service="knowledge") from None
    if any(not release.get(key) or served.get(key) != release[key]
           for key in ("release_id", "manifest_hash")):
        raise PreflightError("knowledge_release_mismatch", "Knowledge release is unavailable or changed", service="knowledge")
    return identities[0]


async def prepare_runtime_for_eval(runtime: Any, settings: Settings, *,
                                   expected_database: str, release: dict) -> dict:
    identity = await preflight_runtime(runtime, settings,
        expected_database=expected_database, release=release)
    await reset_runtime_database(database_url(settings),
        expected_database=expected_database,
        expected_server_started_at=identity["server_started_at"],
        expected_server_host=identity["host"], expected_server_port=identity["port"],
        app_env=settings.app_env)
    return identity


async def run_scenario_stream(
    runtime: Any,
    scenarios: dict[str, Any],
    is_baseline: bool = False,
    run_tag: str = "full",
    wait_for_jobs=None,
    capture_writes=None,
    on_row=None,
    trace: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
    safety_issues: list | None = None, on_turn=None, diagnostics=None, delivery_mode='voice',
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Run all scenarios through the harness runtime."""
    trace = trace if trace is not None else {}
    base_date = date(2026, 10, 15)

    total_sc = len(scenarios)
    for idx, (sid, sc) in enumerate(scenarios.items(), start=1):
        raw_phone = sc.get("customer_phone", "0900000000")
        calls = sc.get("calls", {})

        print(f"[eval] scenario {idx}/{total_sc}: starting", flush=True)
        t_sc_start = time.perf_counter()

        for call_name, call_spec in sorted(calls.items()):
            from eval_harness.seed_history import SeedHistoryGateway, parse_seed_history
            if isinstance(getattr(runtime, "tools", None), SeedHistoryGateway):
                identities = {c.get("channel", "hotline"): c.get("channel_identity", raw_phone)
                              for c in calls.values()}
                runtime.tools.select(sid, identities, parse_seed_history(
                    call_spec.get("seed_history", []), call_date=scenario_call_date(calls, call_name, base_date)))
            call_phone = raw_phone
            rows: list[dict[str, Any]] = []
            trace[(sid, call_name)] = rows

            await run_scenario_call(
                runtime=runtime,
                scenario_id=sid,
                call_name=call_name,
                call_spec=call_spec,
                base_date=base_date,
                customer_phone=call_phone,
                customer_name=sc.get("customer_name"),
                run_id=run_tag,
                config="baseline_no_memory" if is_baseline else "full",
                call_date=scenario_call_date(calls, call_name, base_date),
                wait_for_jobs=wait_for_jobs,
                capture_writes=capture_writes,
                on_row=on_row,
                rows_out=rows, safety_issues=safety_issues, on_turn=on_turn, diagnostics=diagnostics,
                delivery_mode=delivery_mode,
            )

        sc_duration = time.perf_counter() - t_sc_start
        print(f"[eval] scenario {idx}/{total_sc}: finished ({sc_duration:.1f}s)", flush=True)

    return trace


def memory_failure_counts(trace: dict[tuple[str, str], list[dict[str, Any]]]) -> dict[str, int]:
    counts = {"timeout": 0, "job_failed": 0, "capture_failed": 0}
    for rows in trace.values():
        for row in rows:
            code = row.get("memory_error")
            if code in counts:
                counts[code] += 1
    return counts


def assert_trace_ready(scenarios: dict[str, Any],
                       trace: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
    """Refuse to score a run with missing turns or operational errors."""
    expected = []
    for scenario_id, scenario in scenarios.items():
        for call_name, call in scenario.get("calls", {}).items():
            turns = call.get("customer_turns_asr") or call.get("customer_turns", [])
            expected.extend((scenario_id, call_name, index)
                            for index in range(1, len(turns) + 1))
    actual = [(row.get("scenario_id"), row.get("call"), row.get("turn"))
              for rows in trace.values() for row in rows]
    if actual != expected:
        raise RuntimeError("trace coverage does not match the scenario turns")
    for rows in trace.values():
        for row in rows:
            if row.get("memory_error"):
                reason = row["memory_error"] if row["memory_error"] in {
                    "timeout", "job_failed", "capture_failed"} else "unknown"
                raise RuntimeError(
                    "memory job failed during evaluation "
                    f"(scenario={row.get('scenario_id')}, call={row.get('call')}, "
                    f"turn={row.get('turn')}, reason={reason}); "
                    "inspect the saved trace and LangMem worker job error; no score was published")
            if str(row.get("agent_text", "")).startswith("[ERROR:"):
                raise RuntimeError("turn failed during evaluation")


class WarmupGateway:
    """Warm up the same graph/model without any mutable service access."""
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def invoke(self, name, args):
        if name == "crm.get_customer":
            return {"found": False}
        if name == "memory.read":
            return {"history": [], "profile": {}, "episodes": [], "turn_no": 1}
        if name == "memory.write":
            # Each warm-up uses a new session with exactly one synthetic turn.
            # Persist validates the normal memory.write response contract.
            return {"turn_no": 1, "memory_writes": []}
        if name in {"order.create", "order.update", "schedule.callback", "handoff.transfer"}:
            return {"error": "warmup_write_blocked"}
        return await self.inner.invoke(name, args)

    async def invoke_trusted(self, name, args, *pos, **kwargs):
        # All mutation calls, including trusted agent calls, pass the same gate.
        return await self.invoke(name, args)


async def warm_up_configuration(runtime, *, turns: int = 3) -> dict:
    from app.agent.harness.observability import capture_diagnostic_events
    from app.agent.harness.execution_diagnostics import execution_health, safe_execution_error
    for index in range(turns):
        print(f"[eval] warmup {index + 1}/{turns}", flush=True)
        with capture_diagnostic_events() as events:
            try:
                await runtime.run(TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
                    channel="hotline", channel_identity=None, input_mode="clean", on=date(2026, 10, 15), text="Xin chào, bạn có thể hỗ trợ gì?"))
            except Exception as exc:
                error = safe_execution_error(exc, phase='preparation')
                failure = RuntimeError('warmup_execution_unhealthy')
                failure.error_code = 'warmup_execution_unhealthy'
                failure.execution_error = next((e for e in events if e.get('status') == 'failed'), error)
                raise failure from None
        invoked = any(e.get('phase') == 'model_invocation' and e.get('status') == 'succeeded' for e in events)
        if not invoked or execution_health([{'runtime_events': events}]) != 'healthy':
            failure = RuntimeError('warmup_execution_unhealthy')
            failure.error_code = 'warmup_execution_unhealthy'
            failure.execution_error = next((e for e in events if e.get('status') == 'failed'),
                {'version': 1, 'phase': 'model_invocation', 'status': 'unknown'})
            raise failure
    return {"turns": turns, "scored": False, "execution_health": "healthy"}


async def run_configuration(*, scenarios: dict[str, dict], config: str, runtime,
                            run_id: str, out: Path, wait_for_jobs, capture_writes,
                            on_row=None, on_turn=None, btc_root: Path | None = None, safety_issues: list | None = None,
                            delivery_mode='voice') -> dict:
    conversation_measurement(delivery_mode)
    from eval_harness.scenario_contract import dataset_coverage
    if config == "baseline":
        config = "baseline_no_memory"
    if config not in {"full", "baseline_no_memory"}:
        raise ValueError("unsupported_config")
    runtime.memory.include_prior = config == "full"
    trace = {}
    if safety_issues is None:
        safety_issues = []
    original_on_turn = on_turn
    if btc_root is not None:
        from jsonschema import Draft202012Validator
        handoff_validator = Draft202012Validator(json.loads((Path(btc_root) / "schemas/handoff_brief.schema.json").read_text()))
        def on_turn(request, response, state, row):
            for tool in state.get("tool_calls", []):
                if tool.get("name") == "handoff.transfer":
                    if next(handoff_validator.iter_errors(tool.get("args", {}).get("brief")), None):
                        raise RuntimeError("handoff_schema_invalid")
            if original_on_turn:
                original_on_turn(request,response,state,row)
    from eval_harness.turn_diagnostics import TurnDiagnostics
    diagnostics = TurnDiagnostics()
    out = Path(out)
    if any(p.exists() for p in (out, out.with_suffix('.stages.json'), out.with_suffix('.events.json'))):
        raise FileExistsError('output_exists_choose_new_path')
    out.parent.mkdir(parents=True, exist_ok=True)
    decision_refs = None
    with out.open("w", encoding="utf-8") as stream:
        def append(row):
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            if on_row:
                on_row(row)
        try:
            await run_scenario_stream(runtime, scenarios,
                is_baseline=config == "baseline_no_memory", run_tag=run_id,
                wait_for_jobs=wait_for_jobs, capture_writes=capture_writes,
                on_row=append, trace=trace, safety_issues=safety_issues, on_turn=on_turn, diagnostics=diagnostics,
                delivery_mode=delivery_mode)
        finally:
            # Publish final attribution, including late identity backfill.
            write_jsonl(trace, out)
            diagnostic_refs = diagnostics.write(out)
            from app.mcp_servers.mcp_shared.decision_diagnostics import enabled as decision_enabled
            if decision_enabled():
                try:
                    decision_refs = diagnostics.write_decisions(out)
                except Exception:
                    decision_refs = {'error': 'diagnostics_write_failed'}
    assert_trace_ready(scenarios, trace)
    if btc_root is not None:
        validator = Draft202012Validator(json.loads((Path(btc_root) / "schemas/trace_log.schema.json").read_text()))
        if any(next(validator.iter_errors(row), None) for rows in trace.values() for row in rows):
            raise RuntimeError("trace_schema_invalid")
    from eval_harness.extraction_report import write_extraction_sidecar
    sidecar_name = "full.extraction.jsonl" if config == "full" else "baseline.extraction.jsonl"
    write_extraction_sidecar(out, out.parent / sidecar_name)
    return {"coverage": dataset_coverage(scenarios), "trace": trace, "safety_issues": safety_issues, "turn_diagnostics":diagnostic_refs, **({"decision_diagnostics": decision_refs} if decision_refs is not None else {})}


async def wait_for_distillation(dsn: str, source_turn_id: str,
                                timeout_seconds: float = 180) -> None:
    """Wait for this turn's job without including unrelated database jobs."""
    conn = await asyncpg.connect(dsn.replace("postgresql+asyncpg://",
                                            "postgresql://", 1))
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            turn = await conn.fetchrow("""SELECT customer_id FROM runtime.turns
                WHERE client_msg_id=$1""", UUID(source_turn_id))
            if turn is None:
                raise RuntimeError("missing turn for LangMem job")
            row = await conn.fetchrow("""SELECT
                count(*) AS total,
                count(*) FILTER (WHERE status IN ('pending','leased')) AS waiting,
                count(*) FILTER (WHERE status='failed') AS failed
                FROM runtime.langmem_distillation_jobs
                WHERE source_turn_id=$1""", UUID(source_turn_id))
            if (turn["customer_id"] and row["total"] != 1) or row["total"] > 1:
                raise RuntimeError("missing job or duplicate LangMem job for identified turn")
            if row["failed"]:
                raise RuntimeError("LangMem distillation job failed during evaluation")
            if not row["waiting"]:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("LangMem distillation did not finish before call finalization")
            await asyncio.sleep(0.5)
    finally:
        await conn.close()


class DistillationWrites(dict):
    def __init__(self, values, decision_jobs):
        super().__init__(values)
        self.decision_jobs = decision_jobs


async def read_distillation_writes(dsn: str, source_ids: list[str]) -> dict[str, list[dict]]:
    """Read only completed, accepted writes for the exact evaluated turns."""
    if not source_ids:
        return {}
    conn = await asyncpg.connect(dsn.replace("postgresql+asyncpg://",
                                          "postgresql://", 1))
    try:
        from app.mcp_servers.mcp_shared.decision_diagnostics import enabled as decision_enabled
        columns = ',job_id,status,accepted_proposals' if decision_enabled() else ''
        rows = await conn.fetch(f"""SELECT source_turn_id,accepted_writes{columns}
            FROM runtime.langmem_distillation_jobs
            WHERE source_turn_id=ANY($1::uuid[]) AND status='completed'""",
            [UUID(item) for item in source_ids])
        values = {str(row["source_turn_id"]): (json.loads(row["accepted_writes"])
                if isinstance(row["accepted_writes"], str) else row["accepted_writes"])
                for row in rows}
        if not decision_enabled():
            return values
        jobs = {}
        for row in rows:
            proposals = row['accepted_proposals'] or {}
            if isinstance(proposals, str):
                proposals = json.loads(proposals)
            jobs[str(row['source_turn_id'])] = {'revision': row['job_id'], 'status': row['status'],
                'envelope': proposals.get('_decision_diagnostics')}
        return DistillationWrites(values, jobs)
    finally:
        await conn.close()


def print_cli_summary(agent_kind: str, results: dict[str, Any]) -> None:
    """Print clean formatted benchmark table to stdout."""
    sum_full = results["full_metrics"]
    tsr = sum_full["tsr"]
    mem = sum_full["memory"]
    hallu = sum_full["hallucination"]
    guard = sum_full["guardrails"]
    diag = sum_full["diagnostics"]

    print("\n" + "=" * 65)
    print(f"   INTERNAL DIAGNOSTICS: AGENT '{agent_kind.upper()}'")
    print("=" * 65)
    print(f"Scenarios: {tsr['total']} | Total Turns Evaluated: {diag['total_turns_measured']}")
    print("-" * 65)
    print(f"  TSR (Task Success Rate) Overall : {tsr['tsr_overall_pct']}% ({tsr['passed']}/{tsr['total']}) [Target: ≥70%]")
    hard = tsr.get("hard_cases", {})
    print(f"  TSR Ca Khó (Hard Cases TSR)     : {hard.get('tsr_hard_cases_pct')}% ({hard.get('passed')}/{hard.get('total')})")
    print(f"  RQR Full (Repeat Question Rate) : {mem['rqr_full_pct']}%")
    if mem.get("rqr_baseline_pct") is not None:
        print(f"  RQR Baseline                    : {mem['rqr_baseline_pct']}%")
        print(f"  Δ RQR Giảm Tương Đối            : {mem.get('delta_rqr_relative_pct')}% [Target: ≥40%]")
    print(f"  CCR (Context Carryover Rate)    : {mem['ccr_pct']}% ({mem['facts_carried']}/{mem['facts_required']})")
    recall = sum_full.get("memory_recall") or {}
    if recall.get("overall_recall_pct") is not None:
        print(f"  Memory Recall / Precision       : {recall.get('overall_recall_pct')}% ({recall.get('matched')}/{recall.get('expected')}) / {recall.get('overall_precision_pct')}%")
    print(f"  HR Giá & Khuyến Mãi             : {hallu['price_promo_hr_pct']}% [Target: ≤5%]")
    print(f"  HR Tổng Quát                    : {hallu['hallucination_rate_pct']}%")
    print(f"  Guardrail Violations (An toàn)  : {guard['total_violations']} [Target: 0]")
    lat = diag.get("latency_ms", {})
    print(f"  Độ trễ TB / p50 / p95 (ms)      : {lat.get('avg_ms')} / {lat.get('p50_ms')} / {lat.get('p95_ms')} ms [Target p95 ≤8s]")
    print(f"  Số Tool Calls TB / Turn         : {diag.get('avg_tool_calls_per_turn')} (Thrashing: {diag.get('tool_thrashing_count')})")
    print("=" * 65 + "\n")


async def execute_configuration(*, settings, scenarios, config, run_id, out,
                                btc_root, expected_database, release, runtime=None,
                                worker_wait_seconds=180, on_turn=None, delivery_mode='voice'):
    """One authorized live lifecycle, shared by both single-trace CLIs."""
    measurement = conversation_measurement(delivery_mode)
    if any(path.exists() for path in (Path(out), Path(out).with_suffix('.report.json'),
            Path(out).with_suffix('.stages.json'), Path(out).with_suffix('.events.json'))):
        raise FileExistsError("output_exists_choose_new_path")
    settings = settings.model_copy(update={"langfuse_capture_content": False})
    from app.knowledge.context import release_context
    from eval_harness.seed_history import SeedHistoryGateway
    from eval_harness.official_pipeline import atomic_json
    if runtime is None:
        runtime = build_runtime(settings)
        runtime = build_runtime(settings, gateway=SeedHistoryGateway(runtime.tools))
    runtime.memory.include_prior = config == "full"
    issues = []
    from app.agent.harness.execution_diagnostics import safe_failure_details
    phase = "preflight"
    try:
        with release_context(release["release_id"]):
            print(f"[eval] {config}: preflight", flush=True)
            await preflight_runtime(runtime, settings, expected_database=expected_database, release=release)
            phase = "warmup"
            warm = build_runtime(settings, gateway=WarmupGateway(runtime.tools))
            warm.memory.include_prior = config == "full"
            await warm_up_configuration(warm)
            phase = "reset"
            print(f"[eval] {config}: resetting approved runtime", flush=True)
            identity = await prepare_runtime_for_eval(runtime, settings,
                expected_database=expected_database, release=release)
            phase = "conversation"
            print(f"[eval] {config}: conversations", flush=True)
            result = await run_configuration(scenarios=scenarios, config=config, runtime=runtime,
                run_id=run_id, out=out, btc_root=btc_root,
                wait_for_jobs=lambda source: wait_for_distillation(database_url(settings), source, worker_wait_seconds),
                capture_writes=lambda ids: read_distillation_writes(database_url(settings), ids), on_turn=on_turn,
                safety_issues=issues, delivery_mode=delivery_mode)
    except Exception as exc:
        from eval_harness.turn_diagnostics import verify_turn_diagnostics
        diagnostic_refs = {}
        try:
            diagnostic_refs = verify_turn_diagnostics(Path(out))
        except ValueError:
            pass
        atomic_json(Path(out).with_suffix(".report.json"), {"status":"failed", "run_id":run_id,
            **({'turn_diagnostics':diagnostic_refs} if diagnostic_refs else {}),
            "config":config,"error_type":type(exc).__name__,
            "error_code":getattr(exc,"error_code",phase + "_failed"),
            "phase":phase,"service":getattr(exc,"service",None),"safety_issues":issues,
            **safe_failure_details(exc)})
        raise RuntimeError("configuration_failed; inspect safe runner report") from None
    from eval_harness.turn_diagnostics import trace_execution_health
    result["execution_health"] = trace_execution_health(Path(out))
    result["database_identity"] = identity
    result["status"] = "invalid" if result["safety_issues"] else "completed"
    report = {k:v for k,v in result.items() if k != "trace"}
    history = [{"scenario_id":sid,"call":call,"session_id":h["session_id"],
                "sha256":hashlib.sha256(json.dumps(h,sort_keys=True).encode()).hexdigest()}
               for sid,sc in scenarios.items() for call,spec in sc['calls'].items()
               for h in spec.get('seed_history',[])]
    report.update(run_id=run_id, config=config, knowledge_release_id=release["release_id"], seed_history=history,
                  knowledge_release=release, warmup_turns=3, streaming=False,
                  conversation_measurement=measurement)
    from eval_harness.btc_release import release_metadata
    report['btc_contract'] = release_metadata(btc_root)
    atomic_json(Path(out).with_suffix(".report.json"), report)
    return result


async def main() -> None:
    from eval_harness.scenario_contract import load_scenarios as checked_load
    from app.knowledge.context import capture_release
    parser = argparse.ArgumentParser(description="BTC text runner; live model and runtime reset")
    parser.add_argument("--agent", choices=["deep", "react"], required=True)
    parser.add_argument("--config", choices=["full", "baseline", "baseline_no_memory", "both"], default="full")
    parser.add_argument("--variant", choices=["enabled"], default="enabled")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument('--delivery-mode', choices=('text', 'voice'), default='voice')
    parser.add_argument("--worker-wait-seconds", type=float, default=180)
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--btc-root", required=True, type=Path)
    parser.add_argument("--expected-database", default=os.getenv("EVAL_EXPECTED_DATABASE"))
    parser.add_argument("--dry-run", type=int, help="Retired: use preflight --offline-check or --limit-scenarios for LIVE smoke")
    parser.add_argument("--limit-scenarios", type=int, help="LIVE smoke subset (calls model and resets runtime)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    if args.dry_run is not None:
        parser.error("--dry-run retired; use preflight --offline-check or --limit-scenarios for LIVE smoke")
    if not args.expected_database:
        parser.error("--expected-database or EVAL_EXPECTED_DATABASE is required")
    from eval_harness.btc_release import prepare_btc_release
    args.btc_root = prepare_btc_release(args.btc_root, args.out.with_suffix('.btc-release'))
    scenarios = checked_load(args.scenarios, btc_root=args.btc_root)
    if args.limit_scenarios is not None:
        if args.limit_scenarios < 1:
            parser.error("--limit-scenarios must be positive")
        scenarios = dict(list(scenarios.items())[:args.limit_scenarios])
    settings = Settings()
    settings.agent_kind, settings.llm_seed = args.agent, args.seed
    release = (json.loads(os.environ["_EVAL_PINNED_RELEASE"]) if os.getenv("_EVAL_PINNED_RELEASE")
               else await capture_release(database_url(settings)))
    configurations = ["full", "baseline_no_memory"] if args.config == "both" else [
        "baseline_no_memory" if args.config == "baseline" else args.config]
    from eval_harness.official_pipeline import atomic_json
    for config in configurations:
        suffix = "baseline" if config == "baseline_no_memory" else config
        trace = args.out.with_name(args.out.stem + f"_{suffix}.jsonl")
        try:
            result = await execute_configuration(settings=settings, scenarios=scenarios, config=config,
                run_id=(args.run_id or str(uuid4())) + "-" + suffix, out=trace,
                btc_root=args.btc_root, expected_database=args.expected_database, release=release,
                worker_wait_seconds=args.worker_wait_seconds, delivery_mode=args.delivery_mode)
            if result["status"] != "completed":
                raise RuntimeError("redaction_affects_scoring")
        except Exception as exc:
            if not trace.with_suffix(".report.json").exists():
                atomic_json(trace.with_suffix(".report.json"), {"status":"failed", "error_type":type(exc).__name__})
            raise RuntimeError("configuration_failed; inspect safe runner report") from None
    atomic_json(args.out, {"status":"completed", "label":"internal_diagnostic_only", "configurations":configurations})


if __name__ == "__main__":
    asyncio.run(main())
