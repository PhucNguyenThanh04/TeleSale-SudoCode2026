"""BTC trace fields derived from observable answers and tool arguments."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii
from eval_harness.extractor import build_trace_row


_SCORER_ARG_FIELDS = frozenset({
    "sku", "price_vnd", "payment", "order_id", "new_variant_sku", "action", "query"
})


def _safe_value(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, str):
        if path in {("args", "customer_name"), ("result", "customer_name")}:
            return "[TÊN ĐÃ ẨN]"
        if path in {("args", "customer_phone"), ("args", "phone"),
                    ("result", "customer_phone"), ("result", "phone")}:
            return "[SỐ ĐÃ ẨN]"
        if path == ("result", "order_id"):
            return value
        if len(path) == 2 and path[0] == "args" and path[1] in _SCORER_ARG_FIELDS:
            return mask_pii(value) if path[1] == "query" else value
        return mask_pii(value)
    if isinstance(value, list):
        return [_safe_value(item, path) for item in value]
    if isinstance(value, dict):
        return {child_key: _safe_value(item, (*path, child_key))
                for child_key, item in value.items()
                if not (path and path[0] in {"args", "result"} and
                        child_key in {"address", "source_identity", "verified_customer_id"})}
    return value


def _safe_tool_calls(tool_calls: list[dict]) -> list[dict]:
    result = []
    for call in tool_calls:
        tool_name = call.get("name")
        args = _safe_value(call.get("args") or {}, ("args",))
        if isinstance(args, dict) and isinstance(args.get("brief"), dict):
            brief = args["brief"]
            args["brief"] = {key: ("[NỘI DUNG ĐÃ ẨN]" if value else value)
                             for key, value in brief.items()}
        safe_call = {
            "name": tool_name,
            "args": args,
            "result": _safe_value(call.get("result") or {}, ("result",))
        }
        for identifier in ("id", "call_id"):
            if identifier in call:
                safe_call[identifier] = call[identifier]
        result.append(safe_call)
    return result


def facts_used(agent_text: str, tool_calls: list[dict], prior_facts: dict,
               scoped_facts: dict | None = None,
               current_session_id: str | None = None) -> list[str]:
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
        if current_session_id is not None:
            source = fact.get("source") if isinstance(fact, dict) else None
            if not isinstance(source, str) or source.split(":", 1)[0] == current_session_id:
                continue
        value = fact.get("value") if isinstance(fact, dict) else fact
        if value is None:
            continue
        if isinstance(value, bool):
            folded = "".join(char for char in unicodedata.normalize(
                "NFD", agent_text.casefold().replace("đ", "d"))
                if unicodedata.category(char) != "Mn")
            negative = bool(re.search(r"\b(?:khong|chua)\s+(?:co\s+)?"
                                      r"(?:tre nho|con nho|em be|be nho)\b", folded))
            positive = bool(re.search(r"\b(?:co|nha minh co)\s+"
                                      r"(?:tre nho|con nho|em be|be nho)\b", folded))
            stock_negative = bool(re.search(r"\b(?:het hang|tam het hang)\b", folded))
            stock_positive = bool(re.search(r"\b(?:con hang|co hang|san hang)\b", folded))
            spoken = ((negative if not value else positive and not negative)
                      if key == "has_children" else
                      (stock_negative if not value else stock_positive and not stock_negative)
                      if key == "in_stock" else False)
            if spoken:
                used.append(key)
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
    return [{**{key: ("[TÊN ĐÃ ẨN]" if key == "value" and
                        item.get("key") in {"customer_name", "name"} else
                        _safe_value(value, ("memory_writes", key))) for key, value in item.items()
                        if key in {"key", "value", "op", "customer_id",
                                   "evidence_quote", "scope_type", "scope_id"}},
                      "source": f"{call}#turn{turn}"}
                     for item in memory_writes if isinstance(item, dict)]


def trace_line(run_id: str, config: str, scenario_id: str, call: str, turn: int,
               customer_text: str, agent_text: str, tool_calls: list[dict],
               memory_writes: list[dict], used_facts: list[str],
               total_ms: float, call_brief_latency_ms: float | None,
               input_mode: str, customer_name: str | None = None) -> dict[str, Any]:
    names = {customer_name} if customer_name else set()
    names.update(value for tool in tool_calls
                 for key, value in (tool.get("args") or {}).items()
                 if key == "customer_name" and isinstance(value, str))
    names.update(item.get("value") for item in memory_writes
                 if isinstance(item, dict) and item.get("key") in {"customer_name", "name"}
                 and isinstance(item.get("value"), str))
    for name in sorted(names, key=len, reverse=True):
        if name and len(name) > 1:
            pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)
            customer_text = pattern.sub("[TÊN ĐÃ ẨN]", customer_text)
            agent_text = pattern.sub("[TÊN ĐÃ ẨN]", agent_text)
            memory_writes = [{**item, "evidence_quote": pattern.sub(
                "[TÊN ĐÃ ẨN]", item["evidence_quote"])}
                if isinstance(item, dict) and isinstance(item.get("evidence_quote"), str)
                else item for item in memory_writes]
    public_writes = public_memory_writes(call, turn, memory_writes)
    safe_calls = _safe_tool_calls(tool_calls)
    customer_text = mask_pii(customer_text)
    agent_text = mask_pii(agent_text)
    row = build_trace_row(scenario_id, call, turn, customer_text, agent_text,
                          safe_calls, public_writes, used_facts, total_ms,
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
