"""Assemble the small, masked model context for a text turn."""

import time
import logging
import re
from datetime import datetime
from typing import Any, Callable

from app.agent.guardrails.checks import mask_pii, safe_tool_result
from app.agent.memory.store import MemoryStore, memory_error_code
from app.agent.harness.observability import log_event, log_tool_input, log_tool_output
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway
from app.constants import (BRIEF_MUST_NOT_ASK_KEYS, PROFILE_SLOT_KEYS,
                           SLOT_SPEC_BY_KEY, TOOL_ONLY_SLOT_KEYS, Slot)
from app.schemas.brief import CallBrief


def prompt_context(state: TurnState, history_turns: int) -> dict[str, Any]:
    customer_facts, sales_history = _split_facts(state.get("profile", {}))
    scoped = state.get("scoped_facts", {})
    rooms = scoped.get("room", {}) if isinstance(scoped, dict) else {}
    products = scoped.get("product", {}) if isinstance(scoped, dict) else {}
    if isinstance(rooms, dict) and rooms:
        customer_facts["rooms"] = [
            {"room": room, **facts} for room, facts in rooms.items()
            if isinstance(room, str) and isinstance(facts, dict)]
    if isinstance(products, dict) and products:
        sales_history["products"] = [
            {"sku": sku, **facts} for sku, facts in products.items()
            if isinstance(sku, str) and isinstance(facts, dict)]
    observations = [
        {"name": call["name"], "result": safe_tool_result(call["result"])}
        for call in state.get("tool_calls", []) if call["name"] != "crm.get_customer"
    ]
    return {
        "on": state["request"].on.isoformat(),
        "input_mode": state["request"].input_mode,
        "identity_status": state["identity_status"],
        "customer_facts": _mask_context(customer_facts),
        "sales_history": _mask_context(sales_history),
        "session_history": _mask_context(state.get("history", [])[-history_turns:]),
        "previous_episodes": _mask_context(state.get("episodes", [])),
        "current_episode": _mask_context(state.get("current_episode") or {}),
        "call_brief": _mask_context({key: value for key, value in
                                     (state.get("call_brief") or {}).items()
                                     if key not in {"customer_phone", "customer_name"}}),
        "tool_observations": observations,
        "customer_text": state["safe_text"],
    }


def _split_facts(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep customer-stated limits separate from prices and actions by the shop."""
    sales_keys = TOOL_ONLY_SLOT_KEYS | {Slot.PRODUCT_ADVISED}
    customer, sales = {}, {}
    for key, fact in profile.items():
        if key not in PROFILE_SLOT_KEYS or not isinstance(fact, dict):
            continue
        value = fact.get("value")
        types = SLOT_SPEC_BY_KEY[key].value_type
        types = types if isinstance(types, tuple) else (types,)
        if not any(type(value) is allowed for allowed in types):
            continue
        if isinstance(value, str) and mask_pii(value) != value:
            continue
        public = {"key": key, "value": value,
                  "status": "active", "source_kind": fact.get("source_kind")}
        for field in ("on", "source_tool", "source"):
            if isinstance(fact.get(field), str) and mask_pii(fact[field]) == fact[field]:
                public[field] = fact[field]
        if fact.get("source_kind") == "tool" or key in sales_keys:
            sales[key] = public
        else:
            customer[key] = public
    return customer, sales


def _open_episode_items(episodes: list[dict], kind: str) -> list[str]:
    scoped_values = []
    resolved_ids = {item.get("item_id") for episode in episodes
                    if isinstance(episode, dict)
                    for item in episode.get("resolved_prior_items", [])
                    if isinstance(item, dict)}
    for episode in episodes:
        for topic in episode.get("topics", []) if isinstance(episode, dict) else []:
            if not isinstance(topic, dict):
                continue
            for item in topic.get("items", []):
                if (isinstance(item, dict) and item.get("kind") == kind
                        and item.get("status") == "open"
                        and item.get("item_id") not in resolved_ids
                        and isinstance(item.get("text"), str)):
                    entry = (topic.get("scope_type"), topic.get("scope_id"), item["text"])
                    if entry not in scoped_values:
                        scoped_values.append(entry)
    counts = {text: sum(other[2] == text for other in scoped_values)
              for _, _, text in scoped_values}
    return [f"{scope_id}: {value}" if counts[value] > 1 and scope_id else value
            for _, scope_id, value in scoped_values]


def _mask_context(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, list):
        return [_mask_context(item) for item in value]
    if isinstance(value, dict):
        return {key: _mask_context(item) for key, item in value.items()}
    return value


def _safe_scoped_facts(value: Any) -> dict[str, dict[str, dict[str, Any]]]:
    safe = {"product": {}, "room": {}}
    if not isinstance(value, dict):
        return safe
    for scope_type in safe:
        groups = value.get(scope_type, {})
        if not isinstance(groups, dict):
            continue
        for scope_id, facts in groups.items():
            if not isinstance(scope_id, str) or mask_pii(scope_id) != scope_id:
                continue
            admitted, sales = _split_facts(facts if isinstance(facts, dict) else {})
            values = {**admitted, **sales}
            if values:
                safe[scope_type][scope_id] = values
    return safe


async def load_context(state: TurnState, memory: MemoryStore, tools: ToolGateway,
                       clock: Callable[[], datetime]) -> dict[str, Any]:
    customer_id = state.get("customer_id")
    session_id = str(state["request"].session_id)
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

    def failed(operation, reason=None):
        return {"history": [], "profile": {}, "episodes": [], "current_episode": None,
                "call_brief": None,
                "remembered_order_ids": [], "turn_no": 1, "tool_failed": True,
                "memory_failure": operation,
                "memory_blocked": reason == "customer_erasure_in_progress"}

    context = await read_memory("memory.read", lambda: memory.read_context(session_id, customer_id))
    if "error" in context:
        return failed("memory.read", context.get("error"))
    history = _mask_context(context.get("history", []))
    profile = context.get("profile", {})
    scoped_facts = _safe_scoped_facts(context.get("scoped_facts", {}))
    episodes = list(context.get("episodes", []))
    current_episode = _mask_context(context.get("current_episode") or {})
    prior_ids = {str(item) for item in context.get("prior_session_ids", []) if item}
    prior_ids.update(str(item.get("session_id")) for item in episodes
                     if isinstance(item, dict) and item.get("session_id"))
    if getattr(memory, "include_prior", True):
        prior_ids.update(str(item.get("session_id")) for item in state.get("crm_sessions", [])
                         if isinstance(item, dict) and item.get("session_id"))
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
    episodes = _mask_context(episodes)
    if not getattr(memory, "include_prior", True):
        episodes = []
        prior_ids = set()
    prior_ids.discard(session_id)
    first_turn = (context.get("turn_count", 0) == 0 or
                  ("current_episode" in context and context["current_episode"] is None))
    create_brief = (first_turn and bool(episodes) and bool(state.get("customer_phone"))
                    and state.get("identity_status") == "known")
    fresh_calls = []
    warnings = []
    safe_customer, safe_sales = _split_facts(profile)
    profile = {**safe_customer, **safe_sales}
    advised = safe_sales.get(Slot.PRODUCT_ADVISED, {}).get("value")
    scoped_products = scoped_facts["product"]
    requested_skus = [sku for sku in scoped_products
                      if sku.casefold() in state.get("safe_text", "").casefold()]
    if not requested_skus and len(scoped_products) == 1:
        requested_skus = list(scoped_products)
    refresh_skus = requested_skus + ([advised] if isinstance(advised, str)
                                     and (not scoped_products or len(scoped_products) == 1) else [])
    refresh_skus = list(dict.fromkeys(refresh_skus))
    quotes_by_sku = {}
    freshness_request = bool(re.search(
        r"(?i)giá|khuyến mãi|tồn kho|còn hàng|bao nhiêu|giảm giá|ưu đãi",
        state.get("safe_text") or state["request"].text))
    for refresh_sku in refresh_skus if create_brief or (episodes and freshness_request) else []:
        history_facts = scoped_products.get(refresh_sku, safe_sales)
        for name, args in (
            ("inventory.check", {"sku": refresh_sku, "on": state["request"].on.isoformat()}),
            ("pricing.get_quote", {"sku": refresh_sku, "on": state["request"].on.isoformat(),
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
        stock = fresh_calls[-2]["result"]
        quote = fresh_calls[-1]["result"]
        if (isinstance(quote, dict) and "error" not in quote
                and type(quote.get("final_price_vnd")) is int
                and isinstance(quote.get("applied_promos"), list)
                and quote.get("sku", refresh_sku) == refresh_sku):
            quotes_by_sku[refresh_sku] = quote
        if stock.get("in_stock") is False:
            warnings.append(f"{refresh_sku}: Sản phẩm đã hết hàng; cần tư vấn lại.")
        elif "error" in stock:
            warnings.append(f"{refresh_sku}: Chưa kiểm tra được tồn kho hiện tại.")
        old_price = history_facts.get(Slot.PRICE_QUOTED_VND, {}).get("value")
        if old_price is not None and quote.get("final_price_vnd") != old_price:
            warnings.append(f"{refresh_sku}: Giá hiện tại khác báo giá cũ hoặc chưa xác minh được.")
        old_promo = history_facts.get(Slot.PROMO_CODE, {}).get("value")
        if old_promo and refresh_sku in quotes_by_sku and old_promo not in {
            promo.get("promo_code") for promo in quote.get("applied_promos", [])}:
            warnings.append(f"{refresh_sku}: Khuyến mãi cũ không còn được áp dụng.")
        elif old_promo and refresh_sku not in quotes_by_sku:
            warnings.append(f"{refresh_sku}: Chưa kiểm tra được khuyến mãi hiện tại.")
    brief = None
    if create_brief:
        last = episodes[0]
        advised_products = []
        for sku, facts in scoped_products.items():
            if not isinstance(sku, str) or not isinstance(facts, dict):
                continue
            old_promo = facts.get(Slot.PROMO_CODE, {}).get("value")
            quote = quotes_by_sku.get(sku)
            product = {"sku": sku, "promo_code": old_promo,
                "promo_still_active": (old_promo in {promo.get("promo_code")
                    for promo in quote.get("applied_promos", []) if isinstance(promo, dict)}
                    if old_promo and quote else None)}
            old_price = facts.get(Slot.PRICE_QUOTED_VND, {}).get("value")
            if type(old_price) is int:
                product[Slot.PRICE_QUOTED_VND] = old_price
            quoted_on = facts.get(Slot.PRICE_QUOTED_VND, {}).get("on")
            if isinstance(quoted_on, str) and quoted_on:
                product["quoted_on"] = quoted_on
            advised_products.append(product)
        if advised and advised not in scoped_products:
            product = {"sku": advised, "promo_code": safe_sales.get(Slot.PROMO_CODE, {}).get("value")}
            old_price = safe_sales.get(Slot.PRICE_QUOTED_VND, {}).get("value")
            if type(old_price) is int:
                product[Slot.PRICE_QUOTED_VND] = old_price
            quoted_on = safe_sales.get(Slot.PRICE_QUOTED_VND, {}).get("on")
            if isinstance(quoted_on, str) and quoted_on:
                product["quoted_on"] = quoted_on
            advised_products.append(product)
        known_slots = set(safe_customer) | set(safe_sales)
        for groups in scoped_facts.values():
            for facts in groups.values():
                known_slots.update(facts)
        if advised_products and not refresh_skus:
            warnings.append("Chưa kiểm tra lại giá, khuyến mãi và tồn kho của các sản phẩm đã tư vấn.")
        prior_point = (f"mẫu {requested_skus[0]}" if len(requested_skus) == 1
                       else f"mẫu {advised_products[0]['sku']}" if len(advised_products) == 1
                       else "các sản phẩm lần trước" if advised_products
                       else str(safe_customer[Slot.BLOCKER]["value"])
                       if Slot.BLOCKER in safe_customer else "nội dung lần trước")
        next_action = ("Kiểm lại giá hoặc khuyến mãi trước khi tư vấn tiếp." if warnings
                       else "Tiếp tục tư vấn theo nhu cầu đã ghi nhận.")
        structured_blockers = _open_episode_items(episodes, "blocker")
        brief = CallBrief(
            customer_phone=state["customer_phone"], customer_name=state.get("customer_name"),
            honorific=state.get("honorific"), is_returning=True,
            n_previous_sessions=len(prior_ids),
            last_session={"session_id": last["session_id"], "date": last["on"],
                          "channel": last["channel"], "summary": last["summary"],
                          "outcome": last["outcome"]},
            products_advised=advised_products,
            open_blockers=(structured_blockers if structured_blockers else
                [str(safe_customer[Slot.BLOCKER]["value"])]
                if Slot.BLOCKER in safe_customer else []),
            open_questions=_open_episode_items(episodes, "question"),
            must_not_ask=[key for key in BRIEF_MUST_NOT_ASK_KEYS if key in known_slots],
            suggested_opening=f"Dạ, lần trước mình đã trao đổi về {prior_point}. Mình muốn tiếp tục phần đó ạ?",
            suggested_next_action=next_action,
            generated_at=clock(),
            latency_ms=int((time.perf_counter() - state["received_at_monotonic"]) * 1000),
            profile_facts={**{key: value["value"] for key, value in safe_customer.items()},
                "rooms": scoped_facts["room"], "products": scoped_facts["product"]},
            stale_warnings=warnings, precomputed_parts=["episode_summary"],
        ).model_dump(mode="json")
        for product in brief["products_advised"]:
            for optional in ("quoted_on", Slot.PRICE_QUOTED_VND):
                if product.get(optional) is None:
                    product.pop(optional, None)
    return {"history": history, "profile": profile,
            "scoped_facts": scoped_facts,
            "episodes": episodes, "current_episode": current_episode,
            "call_brief": brief,
            "remembered_order_ids": context.get("owned_order_ids", []),
            "tool_calls": [*state.get("tool_calls", []), *fresh_calls],
        "turn_no": context.get("turn_count", len(history)) + 1}
