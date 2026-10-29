"""BTC trace fields derived from observable answers and tool arguments."""

import json
import re
from pathlib import Path
from typing import Any

from eval_harness.extractor import build_trace_row


def facts_used(agent_text: str, tool_calls: list[dict], prior_facts: dict) -> list[str]:
    """Count a prior value only when the answer or a tool argument uses it."""
    used = []
    for key, fact in prior_facts.items():
        value = fact.get("value") if isinstance(fact, dict) else fact
        if value is None or isinstance(value, bool):
            continue
        literal = str(value)
        spoken = bool(re.search(r"(?<!\d)" + re.escape(literal) + r"(?!\d)", agent_text,
                                re.IGNORECASE))
        passed = any(value == arg for call in tool_calls
                     for arg in (call.get("args") or {}).values())
        if spoken or passed:
            used.append(key)
    return sorted(set(used))


def trace_line(run_id: str, config: str, scenario_id: str, call: str, turn: int,
               customer_text: str, agent_text: str, tool_calls: list[dict],
               memory_writes: list[dict], used_facts: list[str],
               total_ms: float, call_brief_latency_ms: float | None,
               input_mode: str) -> dict[str, Any]:
    row = build_trace_row(scenario_id, call, turn, customer_text, agent_text,
                          tool_calls, memory_writes, used_facts, total_ms,
                          call_brief_latency_ms)
    row["run_id"] = run_id
    row["config"] = config
    row["customer_text"] = customer_text
    row["customer_input_mode"] = input_mode
    row["latency"] = {"ttft_ms": int(total_ms), "total_ms": int(total_ms)}
    if call_brief_latency_ms is not None:
        row["call_brief_latency_ms"] = int(call_brief_latency_ms)
    return row


def write_jsonl(trace: dict[tuple[str, str], list[dict]], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for rows in trace.values():
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
