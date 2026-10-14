"""Existing deterministic tool boundaries, separate from graph wiring."""

from datetime import datetime
from typing import Any, Callable

from app.agent.harness.catalog_query import clean_catalog_query
from app.agent.harness.state import TurnState


ALLOWED_TOOLS = {
    "catalog.search", "inventory.check", "pricing.get_quote", "order.create",
    "order.update", "order.status", "schedule.callback", "handoff.transfer",
}
DATED_TOOLS = {"inventory.check", "pricing.get_quote", "order.create", "order.update"}
PHONE_REQUIRED_TOOLS = {"order.create", "schedule.callback"}
_READ_TOOL_ARGS = {
    "catalog.search": {"query", "category", "sku", "max_price_vnd",
                       "min_room_area_m2", "include_discontinued"},
    "inventory.check": {"sku", "on"},
    "pricing.get_quote": {"sku", "on", "qty", "customer_phone", "address", "basket_skus"},
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


def prepare_tool_call(state: TurnState, clock: Callable[[], datetime]) -> tuple[str, dict[str, Any]] | None:
    """Validate a proposed tool call and supply trusted business arguments."""
    request = state["request"]
    decision = state["decision"]
    name = decision.tool_name or ""
    if name not in ALLOWED_TOOLS:
        return None
    args = dict(decision.tool_args)
    if name == "catalog.search" and isinstance(args.get("query"), str):
        args["query"] = clean_catalog_query(args["query"])
    if name in {"inventory.check", "pricing.get_quote"} and not args.get("sku"):
        sku = _single_catalog_sku(state)
        if sku:
            args["sku"] = sku
    if name in _READ_TOOL_ARGS:
        args = {key: value for key, value in args.items() if key in _READ_TOOL_ARGS[name]}
    if name in {"inventory.check", "pricing.get_quote"} and not isinstance(args.get("sku"), str):
        return None
    if name in DATED_TOOLS:
        args["on"] = request.on.isoformat()
    if name == "pricing.get_quote":
        args.pop("customer_phone", None)
        if state.get("customer_phone"):
            args["customer_phone"] = state["customer_phone"]
    if name in PHONE_REQUIRED_TOOLS:
        if not state.get("customer_phone"):
            return None
        args["customer_phone"] = state["customer_phone"]
    if name == "handoff.transfer":
        trusted_phone = state.get("customer_phone") or (
            request.channel_identity if request.channel == "hotline" else None)
        if not trusted_phone:
            return None
        brief = args.get("brief")
        if not isinstance(brief, dict):
            brief = {}
        brief = dict(brief)
        brief["customer_phone"] = trusted_phone
        brief["customer_name"] = state.get("customer_name")
        brief["generated_at"] = clock().isoformat()
        args = {"brief": brief}
    owned_orders = set(state.get("owned_order_ids", [])) | set(state.get("remembered_order_ids", []))
    if name in {"order.status", "order.update"}:
        if state.get("identity_status") != "known" or not state.get("customer_phone"):
            return None
        requested_id = args.get("order_id")
        if requested_id:
            if requested_id not in owned_orders:
                return None
            args.pop("customer_phone", None)
        elif name == "order.status":
            args["customer_phone"] = state["customer_phone"]
        else:
            return None
    if name == "order.create":
        sku = args.get("sku")
        observations = state.get("tool_calls", [])
        stocked = any(call["name"] == "inventory.check" and call["args"].get("sku") == sku
                      and call["result"].get("in_stock") is True for call in observations)
        quoted = any(call["name"] == "pricing.get_quote" and call["args"].get("sku") == sku
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
