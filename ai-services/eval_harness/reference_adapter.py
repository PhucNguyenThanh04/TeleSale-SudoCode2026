"""BTC trace fields derived from observable answers and tool arguments."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii
from eval_harness.extractor import build_trace_row
from app.agent.guardrails.checks import _money_claims


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


def _source_session_id(source: Any) -> str | None:
    if not isinstance(source, str):
        return None
    parts = source.split(":")
    if parts[0] == "langmem":
        return parts[1] if len(parts) == 3 and all(parts) else None
    return parts[0] if len(parts) == 2 and all(parts) else None


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
                   if unicodedata.category(c) != "Mn")


def _spoken_fact(key: str, value: Any, text: str) -> bool:
    folded = _fold(text)
    if type(value) is bool:
        if key == "has_children":
            negative = bool(re.search(r"\b(?:khong|chua)\s+(?:co\s+)?(?:tre nho|con nho|em be|be nho)\b", folded))
            positive = bool(re.search(r"\b(?:co\s+(?:tre nho|con nho|em be|be nho)|be nha minh)\b", folded))
        elif key == "in_stock":
            negative = bool(re.search(r"\b(?:het hang|tam het hang)\b", folded))
            positive = bool(re.search(r"\b(?:con hang|co hang|san hang)\b", folded))
        else:
            return False
        return negative if not value else positive and not negative
    if key.endswith("_vnd"):
        expected_kind = "competitor" if key == "competitor_price_vnd" else "price"
        if key == "budget_vnd" and not re.search(r"ngan sach|tam tien|tam gia", folded):
            return False
        return any(amount == value and kind == expected_kind for amount, kind, _ in _money_claims(text))
    if key == "room_area_m2":
        return bool(re.search(r"(?<!\d)" + re.escape(str(value)) + r"\s*(?:m2|m²|met vuong)(?!\w)", folded))
    return isinstance(value, (str, int)) and bool(re.search(
        r"(?<![\w-])" + re.escape(_fold(str(value))) + r"(?![\w-])", folded))


def facts_used(agent_text: str, tool_calls: list[dict], prior_facts: dict,
               scoped_facts: dict | None = None,
               current_session_id: str | None = None, *, customer_text: str = "") -> list[str]:
    """Only observable use of a sourced fact from before this call counts."""
    candidates = [(key, fact, None) for key, fact in prior_facts.items()]
    for scopes in (scoped_facts or {}).values():
        if isinstance(scopes, dict):
            for scope_id, facts in scopes.items():
                if isinstance(facts, dict):
                    candidates.extend((key, fact, scope_id) for key, fact in facts.items())
    arg_fields = {"product_advised": {"sku"}, "variant_sku": {"sku", "new_variant_sku"},
                  "price_quoted_vnd": {"price_vnd"}, "order_id": {"order_id"},
                  "payment": {"payment"}, "size": {"size"}, "color": {"color"},
                  "preferred_size": {"size"}, "preferred_color": {"color"},
                  "promo_code": {"promo_code"}}
    used = set()
    for key, fact, scope_id in candidates:
        if current_session_id is not None:
            source = _source_session_id(fact.get("source") if isinstance(fact, dict) else None)
            if source is None or source == current_session_id:
                continue
        value = fact.get("value") if isinstance(fact, dict) else fact
        if value is None or customer_text and _spoken_fact(key, value, customer_text):
            continue
        spoken = any(_spoken_fact(key, value, clause) and (
            scope_id is None or str(scope_id).casefold() in clause.casefold())
            for clause in re.split(r"[!?;\n]|\.(?!\d)", agent_text))
        passed = any(
            (scope_id is None or call.get("args", {}).get("sku") == scope_id
             or call.get("args", {}).get("room") == scope_id)
            and any(type(arg) is type(value) and arg == value
                    for field, arg in call.get("args", {}).items() if field in arg_fields.get(key, {key}))
            for call in tool_calls if "error" not in call.get("result", {}))
        if spoken or passed:
            used.add(key)
    return sorted(used)


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
