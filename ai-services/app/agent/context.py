"""Assemble the small, masked model context for a text turn."""

import time
from datetime import datetime, timezone
from typing import Any

from app.agent.guardrails import mask_pii, safe_tool_result
from app.agent.memory import MemoryStore
from app.agent.observability import log_event, log_tool_input, log_tool_output
from app.agent.state import TurnState
from app.agent.tool_gateway import ToolGateway
from app.constants import BRIEF_MUST_NOT_ASK_KEYS, Slot
from app.schemas.brief import CallBrief


def prompt_context(state: TurnState, history_turns: int) -> dict[str, Any]:
    observations = [
        {"name": call["name"], "result": safe_tool_result(call["result"])}
        for call in state.get("tool_calls", []) if call["name"] != "crm.get_customer"
    ]
    return {
        "on": state["request"].on.isoformat(),
        "input_mode": state["request"].input_mode,
        "identity_status": state["identity_status"],
        "known_facts": state.get("profile", {}),
        "session_history": state.get("history", [])[-history_turns:],
        "previous_episodes": state.get("episodes", []),
        "call_brief": {key: value for key, value in (state.get("call_brief") or {}).items()
                       if key not in {"customer_phone", "customer_name"}},
        "tool_observations": observations,
        "customer_text": state["safe_text"],
    }


async def load_context(state: TurnState, memory: MemoryStore, tools: ToolGateway) -> dict[str, Any]:
    customer_id = state.get("customer_id")
    session_id = str(state["request"].session_id)
    context = await memory.read_context(session_id, customer_id)
    if "error" in context:
        log_event(state, "retrieve_context", "memory_unavailable")
        return {"history": [], "profile": {}, "episodes": [],
                "remembered_order_ids": [], "turn_no": 1, "tool_failed": True}
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
    episodes.sort(key=lambda item: item["on"], reverse=True)
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
            generated_at=datetime.now(timezone.utc),
            latency_ms=int((time.perf_counter() - state["received_at_monotonic"]) * 1000),
            profile_facts={key: value["value"] for key, value in profile.items()},
            stale_warnings=warnings, precomputed_parts=["episode_summary"],
        ).model_dump(mode="json")
    return {"history": history, "profile": context.get("profile", {}),
            "episodes": episodes, "call_brief": brief,
            "remembered_order_ids": context.get("owned_order_ids", []),
            "tool_calls": [*state.get("tool_calls", []), *fresh_calls],
            "turn_no": len(history) + 1}
