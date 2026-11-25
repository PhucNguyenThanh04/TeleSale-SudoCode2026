
from app.mcp_servers.mcp_shared.decision_diagnostics import context_checkpoint


import asyncio
import time
import logging
import json
from datetime import date, datetime
from uuid import UUID
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.guardrails.checks import mask_pii, safe_tool_result
from app.agent.memory.store import MemoryStore, memory_error_code
from app.agent.harness.observability import log_event
from app.agent.harness.state import TurnState
from app.agent.harness.session_identity import _empty_identity
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


def _episode_context(episode: dict, duplicate_ids: set[str]) -> dict:
    episode = dict(episode)
    turns = [turn for turn in episode.get('committed_turns', [])
             if turn.get('source_turn_id') not in duplicate_ids]
    covered = duplicate_ids | {turn.get('source_turn_id') for turn in turns}
    if 'committed_turns' in episode:
        episode['committed_turns'] = turns
    if 'customer_statements' in episode:
        episode['customer_statements'] = [turn for turn in episode['customer_statements']
                                         if turn.get('source_turn_id') not in covered]
    return episode


def _bounded_context(context):
    limits = {'customer_facts': 6000, 'sales_history': 4000, 'customer_statements': 10000,
              'session_history': 6000, 'previous_episodes': 6000, 'current_episode': 8000,
              'call_brief': 4000, 'tool_observations': 14000, 'delivery_context': 1000}

    def size(value):
        return len(json.dumps(value, ensure_ascii=False, default=str))

    def fit(value, budget):
        if size(value) <= budget:
            return value
        if isinstance(value, dict):
            selected = {}
            for key, item in value.items():
                available = budget - size(selected) - size(key) - 4
                if available > 8:
                    bounded = fit(item, available)
                    if bounded is not None:
                        selected[key] = bounded
            return selected
        if isinstance(value, list):
            selected = []
            for item in reversed(value):
                available = budget - size(selected) - 2
                if available <= 8:
                    break
                bounded = fit(item, available)
                if bounded is not None:
                    selected.insert(0, bounded)
            return selected
        return None

    omitted = [] if context.pop('source_context_complete', True) else ['source_history']
    references = []

    def collect_refs(value):
        if len(references) >= 16:
            return
        if isinstance(value, dict):
            reference = {key: value[key] for key in ('source_turn_id', 'session_id') if value.get(key)}
            if reference and reference not in references:
                references.append(reference)
            for item in value.values():
                collect_refs(item)
        elif isinstance(value, list):
            for item in reversed(value):
                collect_refs(item)
                if len(references) >= 16:
                    break
    for key, budget in limits.items():
        if size(context.get(key)) > budget:
            collect_refs(context[key])
            context[key] = fit(context[key], budget)
            omitted.append(key)
    context['context_completeness'] = {'complete': not omitted, 'omitted_fields': omitted,
        'omitted_source_refs': references,
        'instruction': 'Thiếu nguồn lịch sử: chỉ tư vấn phần có bằng chứng; chưa thực hiện thao tác ghi.' if omitted else ''}
    while size(context) > 70000:
        key = max(limits, key=lambda field: size(context.get(field)))
        budget = max(2, size(context[key]) - (size(context) - 70000) - 200)
        collect_refs(context[key])
        context[key] = fit(context[key], budget)
        if key not in omitted:
            omitted.append(key)
        context['context_completeness']['complete'] = False
        context['context_completeness']['instruction'] = 'Thiếu nguồn lịch sử; chưa thực hiện thao tác ghi.'
    return context


def prompt_context(state: TurnState, history_turns: int) -> dict[str, Any]:
    if state.get('tool_failed'):
        state = {**state, 'history': [], 'customer_statements': [], 'profile': {}, 'scoped_facts': {'product': {}, 'room': {}},
                 'episodes': [], 'current_episode': None, 'call_brief': None, 'session_tool_calls': []}
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
    history = state.get('history', [])[-history_turns:]
    recent_ids = {turn.get('source_turn_id') for turn in history if turn.get('source_turn_id')}
    current_episode = _episode_context(state.get('current_episode') or {}, recent_ids)
    covered = recent_ids | {turn.get('source_turn_id') for turn in current_episode.get('committed_turns', [])}
    statements = [turn for turn in state.get('customer_statements', [])
                  if turn.get('source_turn_id') not in covered]
    if statements:
        current_episode.pop('customer_statements', None)
    episodes = [_episode_context(episode, set()) for episode in state.get('episodes', [])]
    summary_budget = 4000
    for episode in [current_episode, *episodes]:
        if not (episode.get('committed_turns') or episode.get('customer_statements')):
            continue
        summary = episode.get('summary', '')
        if len(summary) > summary_budget:
            episode['summary'] = summary[:summary_budget]
            episode['summary_truncated'] = True
        summary_budget -= len(episode.get('summary', ''))
    return _bounded_context({
        'source_context_complete': state.get('context_source_complete', True),
        "on": state["request"].on.isoformat(),
        "input_mode": state["request"].input_mode,
        "memory_available": not state.get("tool_failed", False),
        "identity_status": state["identity_status"],
        "honorific": (state.get("honorific") if state["identity_status"] == "known"
                      and state.get("customer_id") else None),
        "customer_facts": _mask_context(customer_facts, ("customer_facts",)),
        "sales_history": _mask_context(sales_history, ("sales_history",)),
        'customer_statements': _mask_context(statements, ('customer_statements',)),
        "session_history": _mask_context(history, ("history",)),
        "previous_episodes": _mask_context(episodes, ("episodes",)),
        "current_episode": _mask_context(current_episode, ("current_episode",)),
        "call_brief": _mask_context({key: value for key, value in
                                     (state.get("call_brief") or {}).items()
                                     if key not in {"customer_phone", "customer_name", 'profile_facts'}}),
        "tool_observations": observations,
        "customer_text": state["safe_text"],
        'delivery_context': ({key: value for key, value in state['private_delivery'].items()
            if key != 'address'} | {'available': bool(state['private_delivery'].get('address'))}
            if state.get('private_delivery') else None),
    })


def prompt_messages(context: dict[str, Any]) -> list[HumanMessage | AIMessage]:
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
                     ('customer_statements', '[]', 'source_turn_id'),
                     ('episodes', '[]', 'session_id'), ('current_episode', 'session_id')}
                or path and path[0] in {'episodes', 'current_episode'}
                and path[-1] == 'source_turn_id'
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
        return {key: _mask_context(item, (*path, key)) for key, item in value.items()
                if key not in {'consultation', 'offer_candidates', 'basket_offers'}}
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


async def _refresh_brief_products(state: TurnState, tools: ToolGateway, skus, address):
    request = state['request']
    existing = build_commerce_evidence(state)
    gate = asyncio.Semaphore(4)

    async def read(name, args):
        if any(call['name'] == name and call['args'] == args for call in existing):
            return None
        async with gate:
            try:
                if hasattr(tools, 'invoke_trusted'):
                    result = await tools.invoke_trusted(name, args, state['customer_id'],
                                                         request.channel, request.channel_identity)
                else:
                    result = await tools.invoke(name, args)
            except Exception:
                result = {'error': 'tool_error'}
        if not isinstance(result, dict):
            result = {'error': 'invalid_tool_result'}
        log_event(state, 'retrieve_context', 'refresh_result', tool=name, success='error' not in result)
        return {'name': name, 'args': args, 'result': result}

    queries = []
    unique_skus = list(dict.fromkeys(skus))
    for sku in unique_skus:
        args = {'sku': sku, 'on': request.on.isoformat()}
        quote = {**args, 'customer_phone': state['customer_phone']}
        if address:
            quote['address'] = address
        queries.extend((read('catalog.get_details', {'sku': sku}),
                        read('inventory.check', args),
                        read('pricing.get_quote', quote)))
    refreshed = [call for call in await asyncio.gather(*queries) if call is not None]
    known = set()
    for call in [*existing, *refreshed]:
        if call.get('name') in {'catalog.search', 'catalog.get_details'} and 'error' not in call.get('result', {}):
            for item in call['result'].get('items') or []:
                if isinstance(item, dict) and item.get('name'):
                    if item.get('sku'):
                        known.add(item['sku'])
                    for variant in item.get('variants') or []:
                        if isinstance(variant, dict) and variant.get('variant_sku'):
                            known.add(variant['variant_sku'])
    gift_skus = list(dict.fromkeys(
        promo['gift_sku'] for call in [*existing, *refreshed]
        if call.get('name') == 'pricing.get_quote' and 'error' not in call.get('result', {})
        for promo in call['result'].get('applied_promos') or []
        if isinstance(promo, dict) and promo.get('type') == 'gift'
        and isinstance(promo.get('gift_sku'), str) and promo['gift_sku']
        and promo['gift_sku'] not in known
        and (not promo.get('valid_until') or promo['valid_until'] >= request.on.isoformat())))
    if gift_skus:
        refreshed.extend(call for call in await asyncio.gather(
            *(read('catalog.get_details', {'sku': sku}) for sku in gift_skus)) if call is not None)
    return refreshed


async def load_context(state: TurnState, memory: MemoryStore, tools: ToolGateway,
                       clock: Callable[[], datetime], *, refresh_brief: bool = False) -> dict[str, Any]:
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
        return {"history": [], 'customer_statements': [], "profile": {}, "scoped_facts": {'product': {}, 'room': {}},
                "episodes": [], "current_episode": None,
                "call_brief": None,
                "remembered_order_ids": [], "turn_no": 1, "tool_failed": True,
                "memory_failure": operation,
                "memory_blocked": reason == "customer_erasure_in_progress"}

    read_kwargs = ({"query": state.get("safe_text", "")} if
                   getattr(memory, "supports_retrieval_query", False) is True else {})
    context = validate_read_response(await read_memory("memory.read", lambda:
        memory.read_context(session_id, customer_id, **read_kwargs)))
    erased = {}
    if context.get('error') == 'customer_erased' and customer_id:
        erased = {**_empty_identity(), 'erased_customer_id': customer_id}
        state.update({**erased, 'session_tool_calls': [], 'tool_calls': [],
                      'prepared_tool_calls': [], 'private_delivery': None})
        customer_id = None
        context = validate_read_response(await read_memory('memory.read.anonymous', lambda:
            memory.read_context(session_id, None, **read_kwargs)))
    if "error" in context:
        return {**failed("memory.read", context.get("error")), **erased}
    delivery = state.get('private_delivery') or context.get('private_delivery')
    prior_address = (context.get('private_delivery') or {}).get('address')
    if delivery:
        try:
            age = (state['request'].on - date.fromisoformat(delivery['source_on'])).days
        except (ValueError, KeyError, TypeError):
            delivery = None
        else:
            if not 0 <= age <= 180:
                delivery = None
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
    unique_episodes = {}
    for item in episodes:
        key = str(item["session_id"])
        if key != session_id:
            unique_episodes.setdefault(key, item)
    latest = context.get('latest_session')
    if isinstance(latest, dict) and latest.get('session_id') != session_id:
        latest_candidates = [latest, *unique_episodes.values()]
    else:
        latest_candidates = list(unique_episodes.values())
    last_session = max(latest_candidates,
                       key=lambda item: str(item.get('on') or ''), default=None)
    episodes = rank_episodes(list(unique_episodes.values()), state.get("safe_text", ""),
                             getattr(memory, "max_episodes", 5))
    episodes = episodes[:getattr(memory, "max_episodes", 5)]
    episodes = _mask_context(episodes, ("episodes",))
    if not getattr(memory, "include_prior", True):
        episodes = []
        prior_ids = set()
    prior_ids.discard(session_id)
    create_brief = (bool(episodes) and bool(state.get("customer_phone"))
                    and state.get("identity_status") == "known")
    warnings = []
    safe_customer, safe_sales = _split_facts(profile, on=state['request'].on)
    profile = {**safe_customer, **safe_sales}
    advised = safe_sales.get(Slot.PRODUCT_ADVISED, {}).get("value")
    scoped_products = scoped_facts["product"]
    tool_calls = list(state.get('tool_calls', []))
    brief = None
    if create_brief:
        last = last_session
        call_date = state["request"].on
        products = dict(scoped_products)
        if advised:
            products.setdefault(advised, safe_sales)
        lookup_skus = {sku: facts.get(Slot.VARIANT_SKU, {}).get('value') or sku
                       for sku, facts in products.items()}
        if refresh_brief and tools is not None and not context.get('turn_count', len(history)) and lookup_skus:
            tool_calls.extend(await _refresh_brief_products(state, tools, lookup_skus.values(),
                                                            (delivery or {}).get('address')))
        evidence = build_commerce_evidence({**state, 'tool_calls': tool_calls})
        quotes_by_sku = {call['args']['sku']: call['result'] for call in evidence
            if call['name'] == 'pricing.get_quote' and isinstance(call.get('args', {}).get('sku'), str)
            and type(call['result'].get('final_price_vnd')) is int
            and isinstance(call['result'].get('applied_promos'), list)}
        stock_by_sku = {call['args']['sku']: call['result'] for call in evidence
            if call['name'] == 'inventory.check' and isinstance(call.get('args', {}).get('sku'), str)
            and type(call['result'].get('in_stock')) is bool}
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
        for sku, facts in products.items():
            old_promo = facts.get(Slot.PROMO_CODE, {}).get("value")
            lookup = lookup_skus[sku]
            quote = quotes_by_sku.get(lookup)
            stock = stock_by_sku.get(lookup)
            product = {"sku": sku, "promo_code": old_promo,
                "promo_still_active": (old_promo in {promo.get("promo_code")
                    for promo in quote.get("applied_promos", []) if isinstance(promo, dict)}
                    if old_promo and quote else None)}
            product.update(_quoted_product_fields(facts))
            advised_products.append(product)
            if not stock or not quote:
                warnings.append(f'{sku}: Chưa xác minh đủ giá, khuyến mãi và tồn kho hiện tại.')
            if stock and stock['in_stock'] is False:
                successor = stock.get('successor_sku')
                replacement = f' Có mẫu thay thế {successor}.' if successor else ''
                warnings.append(f'{sku}: Sản phẩm đã hết hàng.{replacement}')
            if product['promo_still_active'] is False:
                warnings.append(f'{sku}: Khuyến mãi cũ hiện không áp dụng.')
        known_slots = set(safe_customer) | set(safe_sales)
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
        summary = last['summary']
        if prior_address:
            summary = summary.replace(prior_address, '[ĐỊA CHỈ ĐÃ ẨN]')
        brief = CallBrief(
            customer_phone=state["customer_phone"], customer_name=state.get("customer_name"),
            honorific=state.get("honorific"), is_returning=True,
            n_previous_sessions=len(prior_ids),
            last_session={"session_id": last["session_id"], "date": last["on"],
                          "channel": last["channel"], "summary": mask_pii(summary),
                          "outcome": last["outcome"]},
            products_advised=advised_products,

            orders=brief_orders,
            open_blockers=open_blockers,
            open_questions=_open_episode_items(episodes, "question"),
            must_not_ask=sorted(known_slots & PROFILE_SLOT_KEYS),
            suggested_opening="",
            suggested_next_action=None,
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
    return {**erased, "history": history, "profile": profile,
            'context_source_complete': context.get('context_complete', True),
            'private_delivery': delivery,
            'customer_statements': _mask_context(context.get('customer_statements', []), ('customer_statements',)),
            'session_tool_calls': session_calls,
            "scoped_facts": scoped_facts,
            "episodes": episodes, "current_episode": current_episode,
            "call_brief": brief,
            "remembered_order_ids": context.get("owned_order_ids", []),
            "tool_calls": tool_calls,
        "turn_no": context.get("turn_count", len(history)) + 1}
