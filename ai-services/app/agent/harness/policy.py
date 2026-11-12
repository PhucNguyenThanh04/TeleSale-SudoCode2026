"""Existing deterministic tool boundaries, separate from graph wiring."""

from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal
import unicodedata
import re

from app.agent.harness.catalog_query import clean_catalog_query, canonical_catalog_category
from app.agent.harness.handoff_brief import build_handoff_brief
from app.agent.harness.state import TurnState


ALLOWED_TOOLS = {
    "catalog.search", "inventory.check", "pricing.get_quote", "pricing.quote_order", "order.create",
    "order.update", "order.status", "schedule.callback", "handoff.transfer",
    "policy.search",
}
DATED_TOOLS = {"inventory.check", "pricing.get_quote", "pricing.quote_order", "order.create", "order.update",
               "policy.search"}
PHONE_REQUIRED_TOOLS = {"order.create", "schedule.callback"}
_READ_TOOL_ARGS = {
    "catalog.search": {"query", "category", "sku", "max_price_vnd",
                       "min_room_area_m2", "include_discontinued"},
    "inventory.check": {"sku", "on"},
    "pricing.get_quote": {"sku", "on", "qty", "customer_phone", "address", "basket_skus"},
    "pricing.quote_order": {"lines", "on", "customer_phone", "address"},
    "policy.search": {"query", "on", "order_id", "order_date", "customer_reported_order_date", "top_k"},
}
def _single_catalog_sku(state: TurnState) -> str | None:
    searches = [call for call in state.get("tool_calls", [])
                if call.get("name") == "catalog.search" and
                "error" not in call.get("result", {})]
    if not searches:
        return None
    items = searches[-1]["result"].get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    sku = items[0].get("sku")
    return sku if isinstance(sku, str) and sku else None


@dataclass(frozen=True)
class ProductSelection:
    status: Literal["resolved", "catalog_required", "selection_required", "selection_unavailable"]
    sku: str | None = None
    parent_sku: str | None = None
    missing_fields: tuple[str, ...] = ()


def resolve_product_selection(state: TurnState, args: dict[str, Any]) -> ProductSelection:
    """Resolve only from successful catalog metadata, preserving unknown state."""
    sku = args.get("sku")
    items = [item for call in build_commerce_evidence(state)
             if call.get("name") == "catalog.search" and "error" not in call.get("result", {})
             for item in call.get("result", {}).get("items", []) if isinstance(item, dict)]
    parent = next((item for item in reversed(items) if item.get("sku") == sku or any(
        v.get("variant_sku") == sku for v in item.get("variants", []) if isinstance(v, dict))), None)
    if parent is None or not isinstance(parent.get("variants"), list):
        return ProductSelection("catalog_required")
    parent_sku = parent["sku"]
    if not parent["variants"]:
        return ProductSelection("resolved", sku, parent_sku)
    facts = state.get("scoped_facts", {}).get("product", {}).get(parent_sku, {})
    def folded(value):
        return "".join(char for char in unicodedata.normalize(
            "NFD", str(value).casefold().replace("đ", "d"))
            if unicodedata.category(char) != "Mn")
    selections = {}
    from app.mcp_servers.mcp_shared.consultation import _mentions
    metadata = {item['sku']: item for item in items}
    customer_texts = []
    historical_focus = None
    for turn in state.get('history', []):
        if not isinstance(turn, dict):
            continue
        customer = turn.get('customer', turn.get('customer_text', ''))
        named = _mentions(customer, metadata)
        if named:
            historical_focus = next(iter(named)) if len(named) == 1 else None
        if historical_focus == parent_sku:
            customer_texts.append(folded(customer))
        agent_named = _mentions(turn.get('agent', turn.get('agent_text', '')), metadata)
        if agent_named:
            historical_focus = next(iter(agent_named)) if len(agent_named) == 1 else None
    customer_texts.append(folded(state.get('safe_text', '')))
    for key, cue in (("size", r"(?:size|co|kich co)"), ("color", "mau")):
        current = {}
        for customer_text in customer_texts:
            mentioned = {str(v.get(key)): v.get(key) for v in parent["variants"] if isinstance(v, dict)
                         and v.get(key) is not None and re.search(
                             r"\b" + cue + r"\s+" + re.escape(folded(v[key])) + r"(?!\w)", customer_text)}
            if mentioned:
                current = mentioned
        if len(current) > 1:
            return ProductSelection("selection_required", parent_sku=parent_sku, missing_fields=(key,))
        selections[key] = next(iter(current.values())) if current else args.get(key)
        if selections[key] is None and sku == parent_sku:
            selections[key] = facts.get(key, facts.get("preferred_" + key, {})).get("value")
    variants = [v for v in parent["variants"] if isinstance(v, dict)
                and (sku == parent_sku or v.get("variant_sku") == sku)
                and all(value is None or folded(v.get(key)) == folded(value)
                        for key, value in selections.items())]
    if len(variants) == 1:
        return ProductSelection("resolved", variants[0]["variant_sku"], parent_sku)
    if not variants:
        return ProductSelection("selection_unavailable", parent_sku=parent_sku)
    missing = tuple(key for key, value in selections.items() if value is None
                    and len({str(v.get(key)) for v in variants}) > 1)
    return ProductSelection("selection_required", parent_sku=parent_sku, missing_fields=missing)


def catalog_variant(state: TurnState, args: dict[str, Any]) -> str | None:
    return resolve_product_selection(state, args).sku


def prepare_tool_call(state: TurnState, clock: Callable[[], datetime]) -> tuple[str, dict[str, Any]] | None:
    """Validate a proposed tool call and supply trusted business arguments."""
    request = state["request"]
    decision = state["decision"]
    name = decision.tool_name or ""
    if name not in ALLOWED_TOOLS:
        return None
    args = dict(decision.tool_args)
    if name == "catalog.search" and isinstance(args.get("category"), str):
        args["category"] = canonical_catalog_category(args["category"])
    if name == "catalog.search" and isinstance(args.get("query"), str):
        args["query"] = clean_catalog_query(args["query"])
        # A wider second search should not silently drop the customer's filters.
        for call in reversed(state.get("tool_calls", [])):
            if call.get("name") != "catalog.search":
                continue
            previous = call.get("args", {})
            prior_query = previous.get("query")
            new_query = args["query"].casefold()
            old_query = prior_query.casefold() if isinstance(prior_query, str) else ""
            if (new_query and (old_query == new_query or old_query.startswith(new_query + " "))
                    and call.get("result", {}).get("items") == []):
                for key in ("min_room_area_m2", "max_price_vnd", "category"):
                    if args.get(key) is None and previous.get(key) is not None:
                        args[key] = previous[key]
            break
    if name in {"inventory.check", "pricing.get_quote"} and not args.get("sku"):
        sku = _single_catalog_sku(state)
        if sku:
            args["sku"] = sku
    basket_order = name == 'order.create' and args.get('lines') is not None
    if name in {"inventory.check", "pricing.get_quote", "order.create"} and not basket_order:
        selected = catalog_variant(state, args)
        if selected is None and name != "order.create" and args.get("size") is None and args.get("color") is None:
            selected = args.get("sku")
        args["sku"] = selected
        args.pop("size", None)
        args.pop("color", None)
        if not args["sku"]:
            return None
    if name in _READ_TOOL_ARGS:
        args = {key: value for key, value in args.items() if key in _READ_TOOL_ARGS[name]}
    if name in {"inventory.check", "pricing.get_quote"} and not isinstance(args.get("sku"), str):
        return None
    if name == "pricing.get_quote" and not args["sku"].startswith("SKU-"):
        return None
    if name in DATED_TOOLS:
        args["on"] = request.on.isoformat()
    if name == "policy.search":
        order_id = args.pop("order_id", None)
        args.pop("order_date", None)
        if order_id:
            orders = [order for call in state.get("tool_calls", [])
                      if call.get("name") == "order.status"
                      and "error" not in call.get("result", {})
                      for order in call["result"].get("orders", [])
                      if isinstance(order, dict) and order.get("order_id") == order_id]
            if len(orders) != 1:
                return None
            created = orders[0].get("created_on") or orders[0].get("created_at")
            if not created:
                return None
            args["order_date"] = str(created)[:10]
    if name in {"pricing.get_quote", "pricing.quote_order"}:
        args.pop("customer_phone", None)
        if state.get("customer_phone"):
            args["customer_phone"] = state["customer_phone"]
    if name in PHONE_REQUIRED_TOOLS:
        if not state.get("customer_phone"):
            return None
        args["customer_phone"] = state["customer_phone"]
    if name == "handoff.transfer":
        brief = build_handoff_brief(state, args.get("brief") if isinstance(args.get("brief"), dict)
                                   else {}, clock)
        if brief is None:
            return None
        payload = brief.model_dump(mode="json", exclude_none=True)
        for nullable in ("customer_name", "product_advised", "price_quoted_vnd"):
            payload.setdefault(nullable, None)
        args = {"brief": payload}
    owned_orders = set(state.get("owned_order_ids", [])) | set(state.get("remembered_order_ids", []))
    if name in {"order.status", "order.update"}:
        if state.get("identity_status") != "known" or not state.get("customer_phone"):
            return None
        requested_id = args.get("order_id")
        if name == 'order.status' and not requested_id and len(owned_orders) == 1:
            requested_id = args['order_id'] = next(iter(owned_orders))
        if requested_id:
            if requested_id not in owned_orders:
                return None
            args.pop("customer_phone", None)
        elif name == "order.status":
            args["customer_phone"] = state["customer_phone"]
        else:
            return None
    if name == "order.create":
        if state.get("identity_status") != "known":
            return None
        if isinstance(args.get('payment'), str):
            payment = ' '.join(args['payment'].casefold().replace('_', ' ').split())
            aliases = {'cod': 'COD', 'bank': 'bank', 'bank transfer': 'bank',
                       'momo': 'momo', 'zalopay': 'zalopay'}
            args['payment'] = aliases.get(payment, args['payment'])
        if basket_order:
            from app.mcp_servers.mcp_order.schemas import CreateInput
            from app.mcp_servers.mcp_shared.basket import basket_block_reason
            try:
                args = CreateInput.model_validate(args).model_dump(mode='json', exclude_none=True)
            except ValueError:
                return None
            return (name, args) if basket_block_reason(state, args) is None else None
        sku = args.get("sku")
        observations = build_commerce_evidence(state, args=args)
        on = request.on.isoformat()
        qty = args.get("qty", 1)
        latest = {}
        for call in observations:
            if call.get("args", {}).get("sku") == sku:
                latest[call.get("name")] = call
        observations = list(latest.values())
        stocked = any(
            call.get("name") == "inventory.check"
            and call.get("args", {}).get("sku") == sku
            and call.get("args", {}).get("on") == on
            and "error" not in call.get("result", {})
            and call["result"].get("in_stock") is True
            and call["result"].get("qty", 1) >= qty
            for call in observations)
        quoted = any(
            call.get("name") == "pricing.get_quote"
            and call.get("args", {}).get("sku") == sku
            and call.get("args", {}).get("on") == on
            and call.get("args", {}).get("qty", 1) == qty
            and all(call.get("args", {}).get(key) == args.get(key)
                    for key in ("address", "basket_skus"))
            and "error" not in call.get("result", {})
            and call["result"].get("final_price_vnd") == args.get("price_vnd")
            for call in observations)
        if not stocked or not quoted:
            return None
    return name, args


def filter_owned_orders(name: str, args: dict[str, Any], result: dict[str, Any],
                        state: TurnState) -> dict[str, Any]:
    if name != "order.status" or not isinstance(result.get("orders"), list):
        return result
    owned = set(state.get("owned_order_ids", [])) | set(state.get("remembered_order_ids", []))
    return {**result, "orders": [order for order in result["orders"]
            if isinstance(order, dict) and order.get("order_id") in owned
            and (not args.get("order_id") or order.get("order_id") == args["order_id"])]}
