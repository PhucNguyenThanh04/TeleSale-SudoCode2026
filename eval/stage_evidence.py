"""Small, value-free evidence sidecar for diagnosing evaluation turns."""

import re
from typing import Any


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SKU = re.compile(r"^SKU-[A-Z0-9-]{1,80}$")
_TOOL = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _safe_keys(value: Any) -> list[str]:
    return sorted(key for key in value if isinstance(key, str) and _KEY.fullmatch(key)) \
        if isinstance(value, dict) else []


def _scope_keys(value: Any) -> dict[str, dict[str, list[str]]]:
    out = {"product": {}, "room": {}}
    if not isinstance(value, dict):
        return out
    for scope_type in out:
        scopes = value.get(scope_type)
        if not isinstance(scopes, dict):
            continue
        for scope_id, facts in scopes.items():
            # Product SKUs are public catalog identifiers. Room labels can carry
            # free-form customer text, so never copy them into this sidecar.
            label = scope_id if scope_type == "product" and isinstance(scope_id, str) \
                and _SKU.fullmatch(scope_id) else "[redacted_scope]"
            keys = _safe_keys(facts)
            out[scope_type].setdefault(label, [])
            out[scope_type][label] = sorted(set(out[scope_type][label]) | set(keys))
    return out


def _tool_status(name: str, result: Any) -> str:
    if not isinstance(result, dict):
        return "unknown"
    if result.get("ok") is False or result.get("error"):
        return "failed"
    if result.get("ok") is True or result.get("success") is True:
        return "success"
    if result.get("success") is False:
        return "failed"
    if (name == "order.create" and result.get("status") == "created"
            and isinstance(result.get("order_id"), str)):
        return "success"
    if (name == "order.update" and result.get("status") in
            {"pickup_scheduled", "updated"} and isinstance(result.get("order_id"), str)):
        return "success"
    if (name == "schedule.callback" and isinstance(result.get("callback_id"), str)
            and isinstance(result.get("callback_at"), str)):
        return "success"
    if (name == "handoff.transfer" and result.get("status") == "queued"
            and isinstance(result.get("ticket_id"), str)):
        return "success"
    return "unknown"


def stage_evidence(state: dict, response: object, *, scenario_id: str,
                   call: str, turn: int, run_id: str, config: str) -> dict:
    profile = state.get("profile") if isinstance(state.get("profile"), dict) else {}
    current_id = str(getattr(state.get("request"), "session_id", ""))
    prior = {key: fact for key, fact in profile.items()
             if isinstance(fact, dict) and isinstance(fact.get("source"), str)
             and fact["source"].split(":", 1)[0] != current_id}
    failure = state.get("memory_failure")
    identity = state.get("identity_status")
    identity = identity if identity in {"known", "unknown", "ambiguous"} else "unknown"
    read_status = ("failed" if failure == "memory.read" else
                   "ok" if identity == "known" and not failure else "unknown")
    brief = getattr(response, "call_brief", None) or state.get("call_brief")
    brief = brief if isinstance(brief, dict) else {}
    tools = []
    for item in state.get("tool_calls", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and _TOOL.fullmatch(name) and name != "crm.get_customer":
            tools.append({"name": name, "status": _tool_status(name, item.get("result"))})
    return {
        "scenario_id": scenario_id, "call": call, "turn": turn,
        "run_id": run_id, "config": config,
        "identity_status": identity, "memory_read_status": read_status,
        "profile_keys": _safe_keys(profile), "prior_fact_keys": _safe_keys(prior),
        "scoped_fact_keys": _scope_keys(state.get("scoped_facts")),
        "prior_episode_count": len(state.get("episodes", []))
            if isinstance(state.get("episodes"), list) else 0,
        "call_brief_present": bool(brief),
        "call_brief_fields": _safe_keys(brief),
        "call_brief_counts": {key: len(brief[key]) for key in
                              ("must_not_ask", "open_blockers", "open_questions",
                               "stale_warnings") if isinstance(brief.get(key), list)},
        "memory_write_count": len(state.get("memory_writes", []))
            if isinstance(state.get("memory_writes"), list) else 0,
        "memory_write_status": "failed" if failure == "commit_turn" else
            "unknown" if "memory_writes" not in state else "ok",
        "business_tools": tools,
    }
