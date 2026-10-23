"""Benchmark Runner CLI for AI TeleSale SudoCode 2026.

Executes controlled 2x2 experiments (Deep/ReAct x Full/Baseline)
against live PostgreSQL database, 3 MCP servers, and real LLM (gemma4:31b).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

# Add ai-services to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agent.factory import build_runtime
from app.configs import Settings
from app.schemas.agent import TextTurnRequest

from eval_harness.extractor import build_trace_row
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
) -> list[dict[str, Any]]:
    """Execute all turns of a single call in a scenario."""
    session_id = uuid4()
    days_later = call_spec.get("days_later", 0)
    call_date = base_date + timedelta(days=days_later)

    customer_turns = call_spec.get("customer_turns", [])
    trace_rows = []

    for turn_idx, user_text in enumerate(customer_turns, start=1):
        turn_req = TextTurnRequest(
            client_msg_id=str(uuid4()),
            session_id=session_id,
            channel=channel,
            channel_identity=customer_phone,
            on=call_date,
            text=user_text,
            input_mode="clean",
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
            facts_used = list(state.get("profile", {}).keys()) + [
                k for tc in tool_calls for k in tc.get("args", {}).keys()
            ]

        except Exception as exc:
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            agent_text = f"[ERROR: {type(exc).__name__}: {exc}]"
            tool_calls = []
            memory_writes = []
            facts_used = []

        row = build_trace_row(
            scenario_id=scenario_id,
            call_name=call_name,
            turn_idx=turn_idx,
            user_text=user_text,
            agent_text=agent_text,
            tool_calls=tool_calls,
            memory_writes=memory_writes,
            facts_used=facts_used,
            latency_ms=latency_ms,
            call_brief_latency_ms=call_brief_latency,
        )
        trace_rows.append(row)

    return trace_rows


async def run_scenario_stream(
    runtime: Any,
    scenarios: dict[str, Any],
    is_baseline: bool = False,
    run_tag: str = "full",
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Run all scenarios through the harness runtime."""
    trace: dict[tuple[str, str], list[dict[str, Any]]] = {}
    base_date = date(2026, 10, 15)

    total_sc = len(scenarios)
    for idx, (sid, sc) in enumerate(scenarios.items(), start=1):
        raw_phone = sc.get("customer_phone", "0900000000")
        calls = sc.get("calls", {})

        print(f"  [{idx:02d}/{total_sc:02d}] Scenario {sid} ({sc.get('persona')})...", end="", flush=True)
        t_sc_start = time.perf_counter()

        for call_name, call_spec in calls.items():
            # In baseline mode, phone is randomized per call so NO memory carries over
            if is_baseline:
                call_phone = f"099{raw_phone[3:]}"  # 10 digits dummy phone for baseline
            else:
                call_phone = raw_phone  # True phone matching CRM records

            rows = await run_scenario_call(
                runtime=runtime,
                scenario_id=sid,
                call_name=call_name,
                call_spec=call_spec,
                base_date=base_date,
                customer_phone=call_phone,
            )
            trace[(sid, call_name)] = rows

        sc_duration = time.perf_counter() - t_sc_start
        print(f" Done ({sc_duration:.1f}s)")

    return trace


def print_cli_summary(agent_kind: str, results: dict[str, Any]) -> None:
    """Print clean formatted benchmark table to stdout."""
    sum_full = results["full_metrics"]
    tsr = sum_full["tsr"]
    mem = sum_full["memory"]
    hallu = sum_full["hallucination"]
    guard = sum_full["guardrails"]
    diag = sum_full["diagnostics"]

    print("\n" + "=" * 65)
    print(f"   BENCHMARK EVALUATION RESULTS: AGENT '{agent_kind.upper()}'")
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
    parser.add_argument("--config", choices=["full", "baseline", "both"], default="both", help="Eval config to run")
    parser.add_argument("--scenarios", default="ai-services/eval_harness/benchmark_dataset.json", help="Path to scenarios")
    parser.add_argument("--dry-run", type=int, default=0, help="Run only first N scenarios for dry-run")
    parser.add_argument("--out", default=None, help="Output JSON path")
    args = parser.parse_args()

    # Determine output path
    out_path = args.out
    if not out_path:
        out_dir = "ai-services/eval_harness/results"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"benchmark_{args.agent}_agent.json")

    # Load scenarios
    scenarios_all = load_scenarios(args.scenarios)
    if args.dry_run > 0:
        limited_keys = list(scenarios_all.keys())[: args.dry_run]
        scenarios = {k: scenarios_all[k] for k in limited_keys}
        print(f"Running DRY-RUN mode on {len(scenarios)} scenario(s)...")
    else:
        scenarios = scenarios_all
        print(f"Loaded {len(scenarios)} scenarios for evaluation.")

    # Initialize settings and runtime
    settings = Settings()
    settings.agent_kind = args.agent
    print(f"\nInitializing Runtime for Agent: '{args.agent.upper()}' (Model: {settings.llm_model})...")
    runtime = build_runtime(settings)

    trace_full = {}
    trace_baseline = None

    # Run Full Configuration
    if args.config in ("full", "both"):
        print(f"\n--- Running FULL Configuration (With Inter-Session Memory) ---")
        trace_full = await run_scenario_stream(runtime, scenarios, is_baseline=False, run_tag="full")

    # Run Baseline Configuration
    if args.config in ("baseline", "both"):
        print(f"\n--- Running BASELINE Configuration (No Inter-Session Memory) ---")
        trace_baseline = await run_scenario_stream(runtime, scenarios, is_baseline=True, run_tag="baseline")

    # Score Results
    print("\nCalculating metrics against official BTC benchmarks...")
    eval_target_trace = trace_full if trace_full else (trace_baseline or {})

    tsr_results = evaluate_task_success(scenarios, eval_target_trace)
    mem_results = evaluate_memory_metrics(scenarios, eval_target_trace, trace_baseline if args.config == "both" else None)
    hallu_results = evaluate_hallucination(scenarios, eval_target_trace)
    guard_results = evaluate_guardrails(scenarios, eval_target_trace)
    diag_results = evaluate_diagnostics_and_latency(eval_target_trace, warm_up_turns=0 if args.dry_run else 3)

    output_doc = {
        "meta": {
            "agent_kind": args.agent,
            "model": settings.llm_model,
            "config": args.config,
            "reference_date": "2026-10-15",
            "total_scenarios_evaluated": len(scenarios),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "full_metrics": {
            "tsr": tsr_results,
            "memory": mem_results,
            "hallucination": hallu_results,
            "guardrails": guard_results,
            "diagnostics": diag_results,
        },
        "scenarios_breakdown": tsr_results.get("scenario_details", {}),
    }

    # Save JSON output
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_doc, f, indent=2, ensure_ascii=False)

    print_cli_summary(args.agent, output_doc)
    print(f"Saved complete benchmark results to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
