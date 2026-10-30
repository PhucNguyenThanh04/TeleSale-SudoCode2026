"""BTC trace fields derived from observable answers and tool arguments."""

import json
import re
from pathlib import Path
from typing import Any

from eval_harness.extractor import build_trace_row


def facts_used(agent_text: str, tool_calls: list[dict], prior_facts: dict,
               scoped_facts: dict | None = None) -> list[str]:
    """Count a prior value only when the answer or a tool argument uses it."""
    used = []
    candidates = list(prior_facts.items())
    for scopes in (scoped_facts or {}).values():
        if not isinstance(scopes, dict):
            continue
        for facts in scopes.values():
            if isinstance(facts, dict):
                candidates.extend(facts.items())
    for key, fact in candidates:
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


def public_memory_writes(call: str, turn: int, memory_writes: list[dict]) -> list[dict]:
    """Use BTC's call/turn provenance without leaking internal UUIDs into traces."""
    return [{**{key: value for key, value in item.items()
                        if key in {"key", "value", "op", "customer_id",
                                   "evidence_quote", "scope_type", "scope_id"}},
                      "source": f"{call}#turn{turn}"}
                     for item in memory_writes if isinstance(item, dict)]


def trace_line(run_id: str, config: str, scenario_id: str, call: str, turn: int,
               customer_text: str, agent_text: str, tool_calls: list[dict],
               memory_writes: list[dict], used_facts: list[str],
               total_ms: float, call_brief_latency_ms: float | None,
               input_mode: str) -> dict[str, Any]:
    public_writes = public_memory_writes(call, turn, memory_writes)
    row = build_trace_row(scenario_id, call, turn, customer_text, agent_text,
                          tool_calls, public_writes, used_facts, total_ms,
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
