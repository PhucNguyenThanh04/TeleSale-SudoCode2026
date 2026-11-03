"""Benchmark Runner CLI for AI TeleSale SudoCode 2026.

Executes controlled 2x2 experiments (Deep/ReAct x Full/Baseline)
against live PostgreSQL database, 3 MCP servers, and real LLM (gemma4:31b).
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
from typing import Any
from uuid import UUID, uuid4
import asyncpg

# Add ai-services to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agent.factory import build_runtime
from app.configs import Settings
from app.mcp_servers.mcp_shared.config import database_url
from app.schemas.agent import TextTurnRequest

from eval_harness.memory_recall import evaluate_memory_recall
from eval_harness.reference_adapter import (facts_used, public_memory_writes,
                                            trace_line, write_jsonl)
from eval_harness.runtime_reset import reset_runtime_database
from eval_harness.scorer import (
    evaluate_diagnostics_and_latency,
    evaluate_guardrails,
    evaluate_hallucination,
    evaluate_memory_metrics,
    evaluate_task_success,
)

logger = logging.getLogger("eval_runner")
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")


def load_scenarios(path: str) -> dict[str, Any]:
    """Load scenarios from benchmark_dataset.json or a directory of JSON files."""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "scenarios" in data:
                return {s["scenario_id"]: s for s in data["scenarios"]}
            elif isinstance(data, list):
                return {s["scenario_id"]: s for s in data}
            elif isinstance(data, dict) and "scenario_id" in data:
                return {data["scenario_id"]: data}
    elif os.path.isdir(path):
        scenarios = {}
        for fname in sorted(os.listdir(path)):
            if fname.endswith(".json") and not fname.startswith("_"):
                fpath = os.path.join(path, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    sc = json.load(f)
                    scenarios[sc["scenario_id"]] = sc
        return scenarios
    raise ValueError(f"Invalid scenarios path: {path}")


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
) -> list[dict[str, Any]]:
    """Execute all turns of a single call in a scenario."""
    session_id = uuid4()
    days_later = call_spec.get("days_later", 0)
    call_date = call_date or base_date + timedelta(days=days_later)
    channel = call_spec.get("channel", channel)
    channel_identity = call_spec.get("channel_identity", customer_phone)

    customer_turns = call_spec.get("customer_turns_asr") or call_spec.get("customer_turns", [])
    input_mode = call_spec.get("input_mode", "clean")
    trace_rows = rows_out if rows_out is not None else []
    source_ids: list[str] = []
    prior_snapshot = None

    for turn_idx, user_text in enumerate(customer_turns, start=1):
        turn_req = TextTurnRequest(
            client_msg_id=str(uuid4()),
            session_id=session_id,
            channel=channel,
            channel_identity=channel_identity,
            on=call_date,
            text=user_text,
            input_mode=input_mode,
        )

        t_start = time.perf_counter()
        call_brief_latency = None

        try:
            resp = await runtime.run(turn_req)
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            state = runtime.state_for(turn_req) or {}
            agent_text = resp.agent_text or ""
            tool_calls = state.get("tool_calls", [])
            memory_writes = state.get("memory_writes", [])
            if prior_snapshot is None:
                prior_snapshot = deepcopy((state.get("profile", {}), state.get("scoped_facts", {})))
            facts_used_this_turn = facts_used(
                agent_text, tool_calls, *prior_snapshot,
                current_session_id=str(session_id), customer_text=user_text)
            call_brief_latency = (resp.call_brief or {}).get("latency_ms")

        except Exception as exc:
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            agent_text = f"[ERROR: {type(exc).__name__}]"
            tool_calls = []
            memory_writes = []
            facts_used_this_turn = []

        row = trace_line(run_id, config, scenario_id, call_name, turn_idx,
                         user_text, agent_text, tool_calls, memory_writes,
                         facts_used_this_turn, latency_ms, call_brief_latency,
                         input_mode, customer_name=customer_name)
        source_id = str(turn_req.client_msg_id)
        source_ids.append(source_id)
        if wait_for_jobs is not None:
            try:
                await wait_for_jobs(source_id)
            except TimeoutError:
                row["memory_error"] = "timeout"
            except Exception as exc:
                row["memory_error"] = "job_failed"
                logger.warning("Distillation wait failed for %s: %s", source_id,
                               type(exc).__name__)
        if capture_writes is not None and "memory_error" not in row:
            try:
                writes = await capture_writes([source_id])
                row["memory_writes"] = public_memory_writes(
                    call_name, turn_idx, writes.get(source_id, []))
            except Exception as exc:
                row["memory_error"] = "capture_failed"
                row["memory_writes"] = []
                logger.warning("Distillation capture failed for %s: %s", source_id,
                               type(exc).__name__)
        if capture_source_ids:
            row["_client_msg_id"] = source_id
        trace_rows.append(row)
        if on_row is not None:
            on_row(row)

    if capture_writes is not None and source_ids:
        try:
            if wait_for_jobs is not None:
                for sid in source_ids:
                    await wait_for_jobs(sid)
            final_writes = await capture_writes(source_ids)
            for row, source_id in zip(trace_rows, source_ids):
                if "memory_error" not in row:
                    row["memory_writes"] = public_memory_writes(
                        call_name, row["turn"], final_writes.get(source_id, []))
        except Exception as exc:
            logger.warning("Final distillation attribution failed for %s: %s",
                           call_name, type(exc).__name__)

    return trace_rows


def scenario_call_date(calls: dict[str, dict], call_name: str,
                       base_date: date) -> date:
    current = base_date
    for name, spec in calls.items():
        current = (date.fromisoformat(spec["call_date"]) if spec.get("call_date")
                   else current + timedelta(days=spec.get("days_later", 0)))
        if name == call_name:
            return current
    raise KeyError(call_name)


def make_baseline_runtime(runtime: Any) -> Any:
    """Preserve CRM identity while isolating writes and hiding prior memory."""
    runtime.memory.include_prior = False
    runtime.memory.namespace = "baseline"
    return runtime


async def prepare_runtime_for_eval(runtime: Any, settings: Settings) -> dict:
    """Clear mutable rows only after all MCP services identify one database."""
    identities = []
    for service in ("catalog", "order", "memory"):
        identity = await runtime.tools.database_identity(service)
        if not isinstance(identity, dict) or identity.get("error"):
            raise RuntimeError(f"Cannot verify {service} MCP database identity")
        identities.append((identity.get("database"), identity.get("host"),
                           identity.get("port"), identity.get("server_started_at")))
    if len(set(identities)) != 1 or not identities[0][0]:
        raise RuntimeError("MCP services point to different databases")
    await reset_runtime_database(database_url(settings),
                                 expected_database=identities[0][0],
                                 expected_server_started_at=identities[0][3],
                                 app_env=settings.app_env)
    return {"database": identities[0][0], "host": identities[0][1],
            "port": identities[0][2], "server_started_at": identities[0][3]}


async def run_scenario_stream(
    runtime: Any,
    scenarios: dict[str, Any],
    is_baseline: bool = False,
    run_tag: str = "full",
    wait_for_jobs=None,
    capture_writes=None,
    on_row=None,
    trace: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Run all scenarios through the harness runtime."""
    trace = trace if trace is not None else {}
    base_date = date(2026, 10, 15)

    total_sc = len(scenarios)
    for idx, (sid, sc) in enumerate(scenarios.items(), start=1):
        raw_phone = sc.get("customer_phone", "0900000000")
        calls = sc.get("calls", {})

        print(f"  [{idx:02d}/{total_sc:02d}] Scenario {sid} ({sc.get('persona')})...", end="", flush=True)
        t_sc_start = time.perf_counter()

        for call_name, call_spec in calls.items():
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
                rows_out=rows,
            )

        sc_duration = time.perf_counter() - t_sc_start
        print(f" Done ({sc_duration:.1f}s)")

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
                raise TimeoutError("LangMem distillation did not finish before the next turn")
            await asyncio.sleep(0.5)
    finally:
        await conn.close()


async def read_distillation_writes(dsn: str, source_ids: list[str]) -> dict[str, list[dict]]:
    """Read only completed, accepted writes for the exact evaluated turns."""
    if not source_ids:
        return {}
    conn = await asyncpg.connect(dsn.replace("postgresql+asyncpg://",
                                          "postgresql://", 1))
    try:
        rows = await conn.fetch("""SELECT source_turn_id,accepted_writes
            FROM runtime.langmem_distillation_jobs
            WHERE source_turn_id=ANY($1::uuid[]) AND status='completed'""",
            [UUID(item) for item in source_ids])
        return {str(row["source_turn_id"]): (json.loads(row["accepted_writes"])
                if isinstance(row["accepted_writes"], str) else row["accepted_writes"])
                for row in rows}
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="Eval Harness Runner for Deep vs ReAct Agent")
    parser.add_argument("--agent", choices=["deep", "react"], required=True, help="Agent core to evaluate")
    parser.add_argument("--config", choices=["full", "baseline", "both"], default="full", help="Eval config to run")
    parser.add_argument("--variant", choices=["enabled"],
                        default="enabled", help="Deployment memory mode being measured")
    parser.add_argument("--seed", type=int, default=7,
                        help="Identical model seed across ablation runs")
    parser.add_argument("--worker-wait-seconds", type=float, default=180,
                        help="Maximum wait for background memory before the next turn")
    parser.add_argument("--scenarios", default="eval_harness/benchmark_dataset.json", help="Path to scenarios")
    parser.add_argument("--dry-run", type=int, default=0, help="Run only first N scenarios for dry-run")
    parser.add_argument("--out", default=None, help="Output JSON path")
    parser.add_argument("--run-id", default=None, help="Unique ID shared by this paired run")
    args = parser.parse_args()

    out_path = args.out
    if not out_path:
        out_dir = "eval_harness/results"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(
            out_dir, f"benchmark_{args.agent}_{args.variant}_{args.config}.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    scenarios_all = load_scenarios(args.scenarios)
    if args.dry_run > 0:
        limited_keys = list(scenarios_all.keys())[: args.dry_run]
        scenarios = {k: scenarios_all[k] for k in limited_keys}
        print(f"Running DRY-RUN mode on {len(scenarios)} scenario(s)...")
    else:
        scenarios = scenarios_all
        print(f"Loaded {len(scenarios)} scenarios for evaluation.")

    settings = Settings()
    from app.knowledge.context import capture_release
    release = await capture_release(database_url(settings))
    os.environ['KNOWLEDGE_RELEASE_ID'] = release['release_id']
    settings.agent_kind = args.agent
    settings.llm_seed = args.seed
    print(f"\nInitializing Runtime for Agent: '{args.agent.upper()}' (Model: {settings.llm_model})...")
    runtime = build_runtime(settings)

    trace_full: dict[tuple[str, str], list[dict[str, Any]]] = {}
    trace_baseline: dict[tuple[str, str], list[dict[str, Any]]] = {}
    database_identity = None

    def write_runner_report(path: str, config: str, run_id: str) -> None:
        report = {"run_id": run_id, "config": config,
                  "database_identity": database_identity,
                  "knowledge_release_id": os.environ.get("KNOWLEDGE_RELEASE_ID", "btc-only")}
        with open(path.removesuffix(".jsonl") + ".report.json", "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False)

    def trace_writer(path: str):
        stream = open(path, "w", encoding="utf-8")

        def append(row: dict[str, Any]) -> None:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            stream.flush()

        return stream, append

    if args.config in ("full", "both"):
        database_identity = await prepare_runtime_for_eval(runtime, settings)
        print(f"\n--- Running FULL Configuration (With Inter-Session Memory) ---")
        waiter = lambda source_id: wait_for_distillation(
            database_url(settings), source_id, args.worker_wait_seconds)
        path = out_path.removesuffix(".json") + "_full.jsonl"
        stream, append = trace_writer(path)
        try:
            await run_scenario_stream(runtime, scenarios, is_baseline=False,
                run_tag=f"{args.run_id}-full" if args.run_id else args.variant,
                wait_for_jobs=waiter,
                capture_writes=lambda ids: read_distillation_writes(
                    database_url(settings), ids), on_row=append, trace=trace_full)
        except Exception:
            logger.exception("Full evaluation stopped unexpectedly; partial trace retained")
        finally:
            stream.close()
            write_jsonl(trace_full, path)
        assert_trace_ready(scenarios, trace_full)
        write_runner_report(path, "full", f"{args.run_id}-full" if args.run_id else args.variant)

    if args.config in ("baseline", "both"):
        baseline_runtime = make_baseline_runtime(build_runtime(settings))
        database_identity = await prepare_runtime_for_eval(baseline_runtime, settings)
        print(f"\n--- Running BASELINE Configuration (No Inter-Session Memory) ---")
        baseline_waiter = lambda source_id: wait_for_distillation(
            database_url(settings), source_id, args.worker_wait_seconds)
        path = out_path.removesuffix(".json") + "_baseline.jsonl"
        stream, append = trace_writer(path)
        try:
            await run_scenario_stream(baseline_runtime, scenarios,
                is_baseline=True,
                run_tag=f"{args.run_id}-baseline" if args.run_id else "baseline",
                wait_for_jobs=baseline_waiter,
                on_row=append, trace=trace_baseline)
        except Exception:
            logger.exception("Baseline evaluation stopped unexpectedly; partial trace retained")
        finally:
            stream.close()
        assert_trace_ready(scenarios, trace_baseline)
        write_runner_report(path, "baseline_no_memory",
                            f"{args.run_id}-baseline" if args.run_id else "baseline")
    print("\nCalculating internal diagnostic metrics...")
    eval_target_trace = trace_full if trace_full else (trace_baseline or {})

    tsr_results = evaluate_task_success(scenarios, eval_target_trace)
    mem_results = evaluate_memory_metrics(scenarios, eval_target_trace, trace_baseline if args.config == "both" else None)
    recall_results = evaluate_memory_recall(scenarios, eval_target_trace)
    hallu_results = evaluate_hallucination(scenarios, eval_target_trace)
    guard_results = evaluate_guardrails(scenarios, eval_target_trace)
    diag_results = evaluate_diagnostics_and_latency(eval_target_trace, warm_up_turns=0 if args.dry_run else 3)

    output_doc = {
        "meta": {
            "agent_kind": args.agent,
            "model": settings.llm_model,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "seed": settings.llm_seed,
            "variant": args.variant,
            "dataset_hash": hashlib.sha256(json.dumps(scenarios, sort_keys=True,
                ensure_ascii=False).encode()).hexdigest(),
            "scenario_ids": sorted(scenarios),
            "config": args.config,
            "reference_date": "2026-10-15",
            "total_scenarios_evaluated": len(scenarios),
            "scenarios_with_trace": len({sid for sid, _ in eval_target_trace}),
            "memory_job_errors": {"full": memory_failure_counts(trace_full),
                                  "baseline": memory_failure_counts(trace_baseline)},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "full_metrics": {
            "tsr": tsr_results,
            "memory": mem_results,
            "memory_recall": recall_results,
            "hallucination": hallu_results,
            "guardrails": guard_results,
            "diagnostics": diag_results,
        },
        "scenarios_breakdown": tsr_results.get("scenario_details", {}),
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_doc, f, indent=2, ensure_ascii=False)

    print_cli_summary(args.agent, output_doc)
    print(f"Saved complete benchmark results to: {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
