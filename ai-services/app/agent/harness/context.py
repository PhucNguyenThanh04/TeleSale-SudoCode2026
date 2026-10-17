"""Assemble the small, masked model context for a text turn."""

import time
import logging
from datetime import datetime
from typing import Any, Callable

from app.agent.guardrails.checks import mask_pii, safe_tool_result
from app.agent.memory.store import MemoryStore, memory_error_code
from app.agent.harness.observability import log_event, log_tool_input, log_tool_output
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway
from app.constants import BRIEF_MUST_NOT_ASK_KEYS, TOOL_ONLY_SLOT_KEYS, Slot
from app.schemas.brief import CallBrief


def prompt_context(state: TurnState, history_turns: int) -> dict[str, Any]:
    customer_facts, sales_history = _split_facts(state.get("profile", {}))
    observations = [
        {"name": call["name"], "result": safe_tool_result(call["result"])}
        for call in state.get("tool_calls", []) if call["name"] != "crm.get_customer"
    ]
    return {
        "on": state["request"].on.isoformat(),
        "input_mode": state["request"].input_mode,
        "identity_status": state["identity_status"],
        "customer_facts": customer_facts,
        "sales_history": sales_history,
        "session_history": state.get("history", [])[-history_turns:],
        "previous_episodes": state.get("episodes", []),
        "call_brief": {key: value for key, value in (state.get("call_brief") or {}).items()
                       if key not in {"customer_phone", "customer_name"}},
        "tool_observations": observations,
        "customer_text": state["safe_text"],
    }


def _split_facts(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep customer-stated limits separate from prices and actions by the shop."""
    sales_keys = TOOL_ONLY_SLOT_KEYS | {Slot.PRODUCT_ADVISED}
    customer, sales = {}, {}
    for key, fact in profile.items():
        if not isinstance(fact, dict):
            continue
        if fact.get("source_kind") == "tool" or key in sales_keys:
            sales[key] = fact
        else:
            customer[key] = fact
    return customer, sales


async def load_context(state: TurnState, memory: MemoryStore, tools: ToolGateway,
                       clock: Callable[[], datetime]) -> dict[str, Any]:
    customer_id = state.get("customer_id")
    session_id = str(state["request"].session_id)
    claimed_writes = []

    async def read_memory(operation, callback):
        try:
            result = await callback()
        except Exception as exc:
            log_event(state, "retrieve_context", "memory_unavailable", level=logging.WARNING,
                      operation=operation, error_type=type(exc).__name__)
            return {"error": "memory_exception"}
        if not isinstance(result, dict):
            result = {"error": "invalid_tool_result"}
        if "error" in result:
            log_event(state, "retrieve_context", "memory_unavailable", level=logging.WARNING,
                      operation=operation, reason=memory_error_code(result))
        return result

    def failed(operation):
        return {"history": [], "profile": {}, "episodes": [], "call_brief": None,
                "remembered_order_ids": [], "turn_no": 1, "tool_failed": True,
                "memory_failure": operation, "claimed_memory_writes": claimed_writes}

    if customer_id and hasattr(memory, "claim_pending"):
        claimed = await read_memory("claim_pending", lambda: memory.claim_pending(
            session_id, customer_id, str(state["request"].client_msg_id)))
        if "error" in claimed:
            return failed("claim_pending")
        claimed_writes = claimed.get("memory_writes", [])
    context = await read_memory("memory.read", lambda: memory.read_context(session_id, customer_id))
    if "error" in context:
        return failed("memory.read")
    history = context.get("history", [])
    profile = context.get("profile", {})
    episodes = list(context.get("episodes", []))
    if getattr(memory, "include_prior", True):
        episodes.extend({"session_id": item["session_id"], "channel": item["channel"],
                         "on": item["date"], "summary": mask_pii(item["summary"]),
                         "outcome": item.get("outcome", "khac")}
                        for item in state.get("crm_sessions", [])
                        if isinstance(item, dict) and all(k in item for k in
                            ("session_id", "channel", "date", "summary")))
    # Prefer the memory summary over CRM when both describe the same session.
    unique_episodes = {}
    for item in episodes:
        key = str(item["session_id"])
        if key != session_id:
            unique_episodes.setdefault(key, item)
    episodes = sorted(unique_episodes.values(), key=lambda item: item["on"], reverse=True)
    episodes = episodes[:getattr(memory, "max_episodes", 5)]
    if not getattr(memory, "include_prior", True):
        episodes = []
    fresh_calls = []
    warnings = []
    advised = profile.get(Slot.PRODUCT_ADVISED, {}).get("value")
    if episodes and isinstance(advised, str):
        for name, args in (
            ("inventory.check", {"sku": advised, "on": state["request"].on.isoformat()}),
            ("pricing.get_quote", {"sku": advised, "on": state["request"].on.isoformat(),
                                   **({"customer_phone": state["customer_phone"]}
                                      if state.get("customer_phone") else {})}),
        ):
            log_event(state, "retrieve_context", "refresh_invoking", tool=name)
            log_tool_input("retrieve_context", name, args)
            try:
                if hasattr(tools, "invoke_trusted"):
                    result = await tools.invoke_trusted(name, args, customer_id,
                        state["request"].channel, state["request"].channel_identity)
                else:
                    result = await tools.invoke(name, args)
            except Exception:
                result = {"error": "tool_error"}
            log_event(state, "retrieve_context", "refresh_result", tool=name,
                      success="error" not in result)
            log_tool_output(state, "retrieve_context", name, result)
            fresh_calls.append({"name": name, "args": args, "result": result})
        stock = fresh_calls[0]["result"]
        quote = fresh_calls[1]["result"]
        if stock.get("in_stock") is False:
            warnings.append("Sản phẩm đã hết hàng; cần tư vấn lại.")
        elif "error" in stock:
            warnings.append("Chưa kiểm tra được tồn kho hiện tại.")
        old_price = profile.get(Slot.PRICE_QUOTED_VND, {}).get("value")
        if old_price is not None and quote.get("final_price_vnd") != old_price:
            warnings.append("Giá hiện tại khác báo giá cũ hoặc chưa xác minh được.")
        old_promo = profile.get(Slot.PROMO_CODE, {}).get("value")
        if old_promo and old_promo not in {
            promo.get("promo_code") for promo in quote.get("applied_promos", [])}:
            warnings.append("Khuyến mãi cũ không còn được áp dụng.")
    brief = None
    if episodes and state.get("customer_phone"):
        last = episodes[0]
        brief = CallBrief(
            customer_phone=state["customer_phone"], customer_name=state.get("customer_name"),
            honorific=state.get("honorific"), is_returning=True,
            n_previous_sessions=len(episodes),
            last_session={"session_id": last["session_id"], "date": last["on"],
                          "channel": last["channel"], "summary": last["summary"],
                          "outcome": last["outcome"]},
            products_advised=([{"sku": advised,
                                Slot.PRICE_QUOTED_VND: profile.get(Slot.PRICE_QUOTED_VND, {}).get("value"),
                                Slot.PROMO_CODE: profile.get(Slot.PROMO_CODE, {}).get("value")}] if advised else []),
            open_blockers=([str(profile[Slot.BLOCKER]["value"])] if Slot.BLOCKER in profile else []),
            must_not_ask=[key for key in BRIEF_MUST_NOT_ASK_KEYS
                          if key in profile],
            suggested_opening="Dạ, em thấy mình đã trao đổi lần trước. Mình muốn tiếp tục phần đó ạ?",
            generated_at=clock(),
            latency_ms=int((time.perf_counter() - state["received_at_monotonic"]) * 1000),
            profile_facts={key: value["value"] for key, value in _split_facts(profile)[0].items()},
            stale_warnings=warnings, precomputed_parts=["episode_summary"],
        ).model_dump(mode="json")
    return {"history": history, "profile": context.get("profile", {}),
            "episodes": episodes, "call_brief": brief,
            "claimed_memory_writes": claimed_writes,
            "remembered_order_ids": context.get("owned_order_ids", []),
            "tool_calls": [*state.get("tool_calls", []), *fresh_calls],
        "turn_no": context.get("turn_count", len(history)) + 1}
