"""Assemble the small, masked model context for a text turn."""

from app.mcp_servers.mcp_shared.decision_diagnostics import context_checkpoint


import asyncio
import time
import logging
import re
import json
from datetime import date, datetime
from uuid import UUID
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.guardrails.checks import mask_pii, safe_tool_result
from app.agent.harness.brief_opening import build_suggested_opening
from app.agent.memory.store import MemoryStore, memory_error_code
from app.agent.harness.observability import log_event, log_tool_input, log_tool_output
from app.agent.harness.state import TurnState
from app.agent.mcp.gateway import ToolGateway
from app.constants import (PROFILE_SLOT_KEYS,
                           SLOT_SPEC_BY_KEY, TOOL_ONLY_SLOT_KEYS, Slot)
from app.schemas.brief import CallBrief
from app.mcp_servers.mcp_memory.schemas import validate_read_response
from app.mcp_servers.mcp_shared.memory_retrieval import rank_episodes
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence


def _build_brief_orders(state: TurnState, remembered_order_ids: list[str] | None = None,
                        profile: dict[str, Any] | None = None,
                        scoped_products: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    orders_by_id: dict[str, dict[str, Any]] = {}
    for item in state.get("crm_orders") or []:
        if not isinstance(item, dict) or not isinstance(item.get("order_id"), str):
            continue
        oid = item["order_id"]
        variant = item.get("variant_sku") or item.get("sku")
        entry: dict[str, Any] = {
            "order_id": oid,
            "status": str(item.get("status") or "unknown"),
        }
        if isinstance(variant, str) and variant:
            entry["variant_sku"] = variant
        orders_by_id[oid] = entry
    for oid in [*(state.get("owned_order_ids") or []), *(remembered_order_ids or [])]:
        if isinstance(oid, str) and oid and oid not in orders_by_id:
            orders_by_id[oid] = {"order_id": oid, "status": "unknown"}
    prof_oid = (profile or {}).get(Slot.ORDER_ID, {}).get("value")
    if isinstance(prof_oid, str) and prof_oid and prof_oid not in orders_by_id:
        orders_by_id[prof_oid] = {"order_id": prof_oid, "status": "unknown"}
    return list(orders_by_id.values())


def prompt_context(state: TurnState, history_turns: int) -> dict[str, Any]:
    on = state['request'].on
    customer_facts, sales_history = _split_facts(state.get("profile", {}), on=on)
    scoped = _safe_scoped_facts(state.get("scoped_facts", {}), on=on)
    rooms = scoped.get("room", {}) if isinstance(scoped, dict) else {}
    products = scoped.get("product", {}) if isinstance(scoped, dict) else {}
    if isinstance(rooms, dict) and rooms:
        customer_facts["rooms"] = [
            {"room": room, **facts} for room, facts in rooms.items()
            if isinstance(room, str) and isinstance(facts, dict)]
    if isinstance(products, dict) and products:
        product_preferences = []
        for sku, facts in products.items():
            if isinstance(sku, str) and isinstance(facts, dict):
                preferences, _ = _split_facts(facts)
                if preferences:
                    product_preferences.append({"sku": sku, **preferences})
        if product_preferences:
            customer_facts["products"] = product_preferences
        sales_history["products"] = [
            {"sku": sku, **facts} for sku, facts in products.items()
            if isinstance(sku, str) and isinstance(facts, dict)]
    orders = _build_brief_orders(state, state.get("remembered_order_ids"),
                                 state.get("profile"), products)
    if orders:
        sales_history["orders"] = orders
    if state.get("remembered_order_ids"):
        sales_history["remembered_order_ids"] = list(state["remembered_order_ids"])
    observations = [
        {'name': call['name'], 'args': safe_tool_result(call.get('args', {})),
         'result': safe_tool_result(call['result']),
         'evidence_scope': ('current_session' if call in state.get('session_tool_calls', [])
                            else 'current_turn')}
        for call in build_commerce_evidence(state) if call['name'] != 'crm.get_customer'
    ]
    return {
        "on": state["request"].on.isoformat(),
        "input_mode": state["request"].input_mode,
        "identity_status": state["identity_status"],
        "honorific": (state.get("honorific") if state["identity_status"] == "known"
                      and state.get("customer_id") else None),
        "customer_facts": _mask_context(customer_facts, ("customer_facts",)),
        "sales_history": _mask_context(sales_history, ("sales_history",)),
        "session_history": _mask_context(state.get("history", [])[-history_turns:], ("history",)),
        "previous_episodes": _mask_context(state.get("episodes", []), ("episodes",)),
        "current_episode": _mask_context(state.get("current_episode") or {}, ("current_episode",)),
        "call_brief": _mask_context({key: value for key, value in
                                     (state.get("call_brief") or {}).items()
                                     if key not in {"customer_phone", "customer_name"}}),
        "tool_observations": observations,
        "customer_text": state["safe_text"],
    }


def prompt_messages(context: dict[str, Any]) -> list[HumanMessage | AIMessage]:
    """Give same-session turns their actual conversation roles."""
    metadata = {key: value for key, value in context.items()
                if key not in {"session_history", "customer_text"}}
    messages: list[HumanMessage | AIMessage] = [HumanMessage(
        content=json.dumps(metadata, ensure_ascii=False, default=str))]
    for turn in context.get("session_history", []):
        if (isinstance(turn, dict) and isinstance(turn.get("customer"), str)
                and isinstance(turn.get("agent"), str)):
            messages.append(HumanMessage(content=turn["customer"]))
            messages.append(AIMessage(content=turn["agent"]))
    messages.append(HumanMessage(content=str(context.get("customer_text", ""))))
    return messages


def _uuid_fact_source(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(':')
    if len(parts) != 3 or parts[0] != 'langmem':
        return False
    try:
        return all(str(UUID(part)) == part for part in parts[1:])
    except (ValueError, TypeError):
        return False


def _split_facts(profile: dict[str, Any], *, on: date | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep customer-stated limits separate from prices and actions by the shop."""
    sales_keys = TOOL_ONLY_SLOT_KEYS | {Slot.PRODUCT_ADVISED}
    customer, sales = {}, {}
    for key, fact in profile.items():
        if key not in PROFILE_SLOT_KEYS or not isinstance(fact, dict):
            continue
        if fact.get('status', 'active') != 'active':
            continue
        if on is not None:
            try:
                if fact.get('valid_until') and date.fromisoformat(fact['valid_until']) < on:
                    continue
                if fact.get('on') and date.fromisoformat(fact['on']) > on:
                    continue
            except (ValueError, TypeError):
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
        for field in ("on", "source_tool", "source", "valid_until", "source_turn_id", "session_id"):
            if field == 'source' and _uuid_fact_source(fact.get(field)):
                public[field] = fact[field]
            elif isinstance(fact.get(field), str) and mask_pii(fact[field]) == fact[field]:
                public[field] = fact[field]
            elif field in {"source_turn_id", "session_id"} and isinstance(fact.get(field), str):
                try:
                    UUID(fact[field])
                except ValueError:
                    continue
                public[field] = fact[field]
        if isinstance(fact.get("evidence_quote"), str):
            public["evidence_quote"] = mask_pii(fact["evidence_quote"])
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


def _mask_context(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, str):
        if (path and path[0] in {'customer_facts', 'sales_history'}
                and path[-1] == 'source' and _uuid_fact_source(value)):
            return value
        if (path in {('history', '[]', 'source_turn_id'),
                     ('episodes', '[]', 'session_id'), ('current_episode', 'session_id')}
                or path and path[0] in {'customer_facts', 'sales_history'}
                and path[-1] in {'source_turn_id', 'session_id'}):
            try:
                UUID(value)
            except (ValueError, TypeError):
                pass
            else:
                return value
        return mask_pii(value)
    if isinstance(value, list):
        return [_mask_context(item, (*path, '[]')) for item in value]
    if isinstance(value, dict):
        from app.schemas.consultation import mask_consultation
        return {key: mask_consultation(item) if key=='consultation' else _mask_context(item, (*path, key)) for key, item in value.items()}
    return value


def _safe_scoped_facts(value: Any, *, on: date | None = None) -> dict[str, dict[str, dict[str, Any]]]:
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
            admitted, sales = _split_facts(facts if isinstance(facts, dict) else {}, on=on)
            values = {**admitted, **sales}
            if values:
                safe[scope_type][scope_id] = values
    return safe


def _quoted_product_fields(facts: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    old_price = facts.get(Slot.PRICE_QUOTED_VND, {}).get("value")
    if type(old_price) is int:
        fields[Slot.PRICE_QUOTED_VND] = old_price
    quoted_on = facts.get(Slot.PRICE_QUOTED_VND, {}).get("on")
    if isinstance(quoted_on, str) and quoted_on:
        fields["quoted_on"] = quoted_on
    return fields


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
        return {"history": [], "profile": {}, "scoped_facts": {'product': {}, 'room': {}},
                "episodes": [], "current_episode": None,
                "call_brief": None,
                "remembered_order_ids": [], "turn_no": 1, "tool_failed": True,
                "memory_failure": operation,
                "memory_blocked": reason == "customer_erasure_in_progress"}

    read_kwargs = ({"query": state.get("safe_text", "")} if
                   getattr(memory, "supports_retrieval_query", False) is True else {})
    context = validate_read_response(await read_memory("memory.read", lambda:
        memory.read_context(session_id, customer_id, **read_kwargs)))
    if "error" in context:
        return failed("memory.read", context.get("error"))
    # Prefer richer in-process observations; recover missing committed reads after a restart.
    session_calls = list(state.get('session_tool_calls', []))
    existing = {str(call['source_turn_id']) for call in session_calls if call.get('source_turn_id')}
    session_calls.extend(call for call in context.get('session_tool_calls', [])
                         if str(call.get('source_turn_id')) not in existing)
    state['session_tool_calls'] = session_calls
    context_checkpoint("context_loaded", state, context)
    history = _mask_context(context.get("history", []), ("history",))
    profile = context.get("profile", {})
    scoped_facts = _safe_scoped_facts(context.get("scoped_facts", {}), on=state['request'].on)
    episodes = list(context.get("episodes", []))
    accepted = context.get("accepted_episodes") or []
    if customer_id and getattr(memory, "include_prior", True) and accepted:
        canonical = {str(item.get("session_id")): item for item in episodes
                     if isinstance(item, dict)}
        accepted = [canonical[str(item["session_id"])] for item in accepted
                    if isinstance(item, dict) and str(item.get("session_id")) in canonical
                    and item.get("summary") == canonical[str(item["session_id"])].get("summary")]
        episodes = rank_episodes(accepted, state.get("safe_text", ""),
                                getattr(memory, "max_episodes", 5)) + [item for item in episodes
                                if item.get("session_id") not in {
                                    accepted_item.get("session_id") for accepted_item in accepted}]
    current_episode = _mask_context(context.get("current_episode") or {}, ("current_episode",))
    context_checkpoint("context_masked", state, {"history": history, "episodes": episodes, "current_episode": current_episode})
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
    episodes = rank_episodes(list(unique_episodes.values()), state.get("safe_text", ""),
                             getattr(memory, "max_episodes", 5))
    episodes = episodes[:getattr(memory, "max_episodes", 5)]
    episodes = _mask_context(episodes, ("episodes",))
    if not getattr(memory, "include_prior", True):
        episodes = []
        prior_ids = set()
    prior_ids.discard(session_id)
    first_turn = (context.get("turn_count", 0) == 0 or
                  ("current_episode" in context and context["current_episode"] is None))
    create_brief = (bool(episodes) and bool(state.get("customer_phone"))
                    and state.get("identity_status") == "known")
    fresh_calls = []
    warnings = []
    safe_customer, safe_sales = _split_facts(profile, on=state['request'].on)
    profile = {**safe_customer, **safe_sales}
    advised = safe_sales.get(Slot.PRODUCT_ADVISED, {}).get("value")
    scoped_products = scoped_facts["product"]
    requested_skus = [sku for sku in scoped_products
                      if sku.casefold() in state.get("safe_text", "").casefold()]
    if requested_skus:
        candidate_skus = list(requested_skus)
    else:
        def _sku_recency(sku: str) -> str:
            facts = scoped_products.get(sku, {})
            dates = [str(f.get("on", "")) for f in facts.values()
                     if isinstance(f, dict) and f.get("on")]
            return max(dates) if dates else ""
        ordered_scoped = sorted(scoped_products.keys(), key=_sku_recency, reverse=True)
        candidate_skus = ordered_scoped + ([advised] if isinstance(advised, str)
                                           and advised not in scoped_products else [])
    candidate_skus = list(dict.fromkeys(candidate_skus))
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    consultation = derive_consultation({**state, 'history': history, 'profile': profile,
        'scoped_facts': scoped_facts, 'episodes': episodes, 'current_episode': current_episode})
    focused = consultation.focus_sku
    # Refresh a sourced focus, or the sole historical candidate. Shortlisting is
    # handled by BusinessTools within its budget, never a memory-list position.
    refresh_skus = [focused] if focused else candidate_skus if len(candidate_skus) == 1 else []
    skipped_skus = [sku for sku in candidate_skus if sku not in refresh_skus]
    quotes_by_sku = {call['args']['sku']: call['result']
        for call in build_commerce_evidence(state)
        if call.get('name') == 'pricing.get_quote' and isinstance(call.get('args', {}).get('sku'), str)
        and type(call['result'].get('final_price_vnd')) is int
        and isinstance(call['result'].get('applied_promos'), list)}
    freshness_request = bool(re.search(
        r"(?i)giá|khuyến mãi|tồn kho|còn hàng|bao nhiêu|giảm giá|ưu đãi",
        state.get("safe_text") or state["request"].text))
    should_refresh = (create_brief and first_turn) or (episodes and freshness_request)

    async def _invoke_refresh(name: str, args: dict[str, Any]) -> dict[str, Any]:
        log_event(state, "retrieve_context", "refresh_invoking", tool=name)
        log_tool_input("retrieve_context", name, args)
        try:
            if hasattr(tools, "invoke_trusted"):
                res = await tools.invoke_trusted(
                    name, args, customer_id,
                    state["request"].channel, state["request"].channel_identity)
            else:
                res = await tools.invoke(name, args)
        except Exception:
            res = {"error": "tool_error"}
        if not isinstance(res, dict):
            res = {"error": "invalid_tool_result"}
        log_event(state, "retrieve_context", "refresh_result", tool=name,
                  success="error" not in res)
        log_tool_output(state, "retrieve_context", name, res)
        return res

    async def _refresh_one_sku(refresh_sku: str):
        inv_args = {"sku": refresh_sku, "on": state["request"].on.isoformat()}
        quote_args = {
            "sku": refresh_sku, "on": state["request"].on.isoformat(),
            **({"customer_phone": state["customer_phone"]}
               if state.get("customer_phone") else {}),
        }
        from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
        valid = build_commerce_evidence(state, args={'sku': refresh_sku, 'qty': 1})
        async def read_needed(name, args):
            existing = next((c for c in reversed(valid) if c['name'] == name), None)
            return (existing['result'], False) if existing else (await _invoke_refresh(name, args), True)
        (stock_res, stock_new), (quote_res, quote_new) = await asyncio.gather(
            read_needed('inventory.check', inv_args), read_needed('pricing.get_quote', quote_args))
        return refresh_sku, inv_args, stock_res, quote_args, quote_res, stock_new, quote_new

    if should_refresh and refresh_skus:
        refresh_results = await asyncio.gather(
            *(_refresh_one_sku(sku) for sku in refresh_skus))
    else:
        refresh_results = []

    for refresh_sku, inv_args, stock, quote_args, quote, stock_new, quote_new in refresh_results:
        if stock_new:fresh_calls.append({'name': 'inventory.check', 'args': inv_args, 'result': stock})
        if quote_new:fresh_calls.append({'name': 'pricing.get_quote', 'args': quote_args, 'result': quote})
        history_facts = scoped_products.get(refresh_sku, safe_sales)
        if (isinstance(quote, dict) and "error" not in quote
                and type(quote.get("final_price_vnd")) is int
                and isinstance(quote.get("applied_promos"), list)
                and quote.get("sku", refresh_sku) == refresh_sku):
            quotes_by_sku[refresh_sku] = quote
        if stock.get("discontinued") is True:
            succ = stock.get("successor_sku")
            if isinstance(succ, str) and succ:
                warnings.append(
                    f"{refresh_sku}: Sản phẩm đã hết hàng và ngừng kinh doanh; gợi ý mẫu thay thế {succ}.")
            else:
                warnings.append(
                    f"{refresh_sku}: Sản phẩm đã hết hàng và ngừng kinh doanh; cần tư vấn lại.")
        elif stock.get("in_stock") is False:
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
    if should_refresh and skipped_skus:
        warnings.append(
            f"Chưa làm mới tự động cho {', '.join(skipped_skus)}; cần kiểm tra lại khi khách hỏi.")
    brief = None
    if create_brief:
        last = episodes[0]
        call_date = state["request"].on
        try:
            last_on = (last["on"] if isinstance(last["on"], date)
                       else date.fromisoformat(str(last["on"])))
            if (call_date - last_on).days > 180:
                warnings.append(
                    "Phiên tư vấn trước cách đây hơn 180 ngày; cần xác nhận lại địa chỉ giao hàng.")
        except (KeyError, TypeError, ValueError):
            pass
        all_fact_entries: list[tuple[str, dict[str, Any]]] = [
            *[(k, v) for k, v in context.get('profile', {}).items() if isinstance(v, dict)],
            *[(f"{sku}:{k}", v) for sku, facts in context.get('scoped_facts', {}).get('product', {}).items()
              if isinstance(facts, dict) for k, v in facts.items() if isinstance(v, dict)],
        ]
        for label, fact_item in all_fact_entries:
            until_raw = fact_item.get("valid_until")
            if isinstance(until_raw, str) and until_raw:
                try:
                    if date.fromisoformat(until_raw) < call_date:
                        msg = f"{label}: Thông tin đã hết hạn hiệu lực ({until_raw})."
                        if msg not in warnings:
                            warnings.append(msg)
                except ValueError:
                    pass
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
            product.update(_quoted_product_fields(facts))
            advised_products.append(product)
        if advised and advised not in scoped_products:
            product = {"sku": advised, "promo_code": safe_sales.get(Slot.PROMO_CODE, {}).get("value")}
            product.update(_quoted_product_fields(safe_sales))
            advised_products.append(product)
        # The canonical snapshot can already reflect later advice while the
        # independent fact projection still contains only an earlier product.
        snapshot = consultation.snapshot
        recommended_ref = snapshot.source_refs.get('recommended_sku')
        selected_ref = snapshot.source_refs.get('selected_sku')
        recommended = (snapshot.recommended_sku if recommended_ref
                       and recommended_ref.source_kind == 'agent' else None)
        selected = (snapshot.selected_sku if selected_ref
                    and selected_ref.source_kind == 'customer' else None)
        discussed = {product['sku'] for product in advised_products}
        for sku in (recommended, selected):
            if sku and sku not in discussed:
                advised_products.append({'sku': sku})
                discussed.add(sku)
        known_slots = set(safe_customer) | set(safe_sales)
        for groups in scoped_facts.values():
            for facts in groups.values():
                known_slots.update(facts)
        if advised_products and not refresh_skus:
            warnings.append("Chưa kiểm tra lại giá, khuyến mãi và tồn kho của các sản phẩm đã tư vấn.")
        next_action = ("Kiểm lại giá hoặc khuyến mãi trước khi tư vấn tiếp." if warnings
                       else "Tiếp tục tư vấn theo nhu cầu đã ghi nhận.")
        structured_blockers = _open_episode_items(episodes, "blocker")
        resolved_any = any(
            isinstance(ep, dict) and bool(ep.get("resolved_prior_items"))
            for ep in episodes
        )
        open_blockers = (structured_blockers if structured_blockers else
                         [str(safe_customer[Slot.BLOCKER]["value"])]
                         if (Slot.BLOCKER in safe_customer and not resolved_any) else [])
        brief_orders = _build_brief_orders(
            state, context.get("owned_order_ids", []), profile, scoped_products)
        opening = build_suggested_opening(
            honorific=state.get("honorific"),
            customer_name=state.get("customer_name"),
            last_session=last,
            requested_skus=requested_skus,
            advised_products=advised_products,
            recommended_sku=recommended,
            selected_sku=selected,
            open_blockers=open_blockers,
        )
        brief = CallBrief(
            customer_phone=state["customer_phone"], customer_name=state.get("customer_name"),
            honorific=state.get("honorific"), is_returning=True,
            n_previous_sessions=len(prior_ids),
            last_session={"session_id": last["session_id"], "date": last["on"],
                          "channel": last["channel"], "summary": last["summary"],
                          "outcome": last["outcome"]},
            products_advised=advised_products,
            recommended_sku=recommended,
            selected_sku=selected,
            orders=brief_orders,
            open_blockers=open_blockers,
            open_questions=_open_episode_items(episodes, "question"),
            must_not_ask=sorted(known_slots & PROFILE_SLOT_KEYS),
            suggested_opening=opening,
            suggested_next_action=next_action,
            generated_at=clock(),
            latency_ms=int((time.perf_counter() - state["received_at_monotonic"]) * 1000),
            profile_facts={**{key: value["value"] for key, value in safe_customer.items()},
                "rooms": scoped_facts["room"], "products": scoped_facts["product"]},
            stale_warnings=warnings, precomputed_parts=[] if last.get('operational_only') else ["episode_summary"],
        ).model_dump(mode="json")
        for product in brief["products_advised"]:
            for optional in ("quoted_on", Slot.PRICE_QUOTED_VND):
                if product.get(optional) is None:
                    product.pop(optional, None)
        for order_entry in brief.get("orders", []):
            if order_entry.get("variant_sku") is None:
                order_entry.pop("variant_sku", None)
    return {"history": history, "profile": profile,
            'session_tool_calls': session_calls,
            "scoped_facts": scoped_facts,
            "episodes": episodes, "current_episode": current_episode,
            "call_brief": brief,
            "remembered_order_ids": context.get("owned_order_ids", []),
            "tool_calls": [*state.get("tool_calls", []), *fresh_calls],
        "turn_no": context.get("turn_count", len(history)) + 1}
