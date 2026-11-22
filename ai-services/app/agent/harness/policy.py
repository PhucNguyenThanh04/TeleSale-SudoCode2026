
from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS, build_commerce_evidence, successful, quote_context_matches
from app.mcp_servers.mcp_shared.pii import private_delivery_context

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal
import unicodedata

from app.agent.harness.handoff_brief import build_handoff_brief
from app.agent.harness.state import TurnState


ALLOWED_TOOLS = {
    "catalog.search", "inventory.check", "pricing.get_quote", "pricing.quote_order", "order.create",
    "order.update", "order.status", "schedule.callback", "handoff.transfer",
    "policy.search", 'catalog.get_details', 'order.preview_update',
}
DATED_TOOLS = {"inventory.check", "pricing.get_quote", "pricing.quote_order", "order.create", "order.update",
               "policy.search", 'order.preview_update'}
PHONE_REQUIRED_TOOLS = {"order.create", "schedule.callback"}
_READ_TOOL_ARGS = {
    'catalog.get_details': {'sku'},
    'order.preview_update': {'order_id', 'action', 'on', 'line_index', 'qty', 'new_variant_sku', 'reason'},
    "catalog.search": {"query", "category", "sku", "max_price_vnd",
                       "min_room_area_m2", "include_discontinued", 'attribute_filters'},
    "inventory.check": {"sku", "on"},
    "pricing.get_quote": {"sku", "on", "qty", "customer_phone", "address", "basket_skus"},
    "pricing.quote_order": {"lines", "on", "customer_phone", "address"},
    "policy.search": {"query", "on", "order_id", "order_date", "customer_reported_order_date", "top_k", 'product_sku'},
}
@dataclass(frozen=True)
class ProductSelection:
    status: Literal["resolved", "catalog_required", "selection_required", "selection_unavailable"]
    sku: str | None = None
    parent_sku: str | None = None
    missing_fields: tuple[str, ...] = ()


def resolve_product_selection(state: TurnState, args: dict[str, Any]) -> ProductSelection:
    sku = args.get("sku")
    items = [item for call in build_commerce_evidence(state)
             if call.get("name") in CATALOG_TOOLS and "error" not in call.get("result", {})
             for item in call.get("result", {}).get("items", []) if isinstance(item, dict)]
    parent = next((item for item in reversed(items) if item.get("sku") == sku or any(
        v.get("variant_sku") == sku for v in item.get("variants", []) if isinstance(v, dict))), None)
    if parent is None or not isinstance(parent.get("variants"), list):
        return ProductSelection("catalog_required")
    parent_sku = parent["sku"]
    if not parent["variants"]:
        return ProductSelection("resolved", sku, parent_sku)
    def folded(value):
        return "".join(char for char in unicodedata.normalize(
            "NFD", str(value).casefold().replace("đ", "d"))
            if unicodedata.category(char) != "Mn")
    selections = {key: args.get(key) for key in ('size', 'color')}
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


def _policy_order(state, order_id):
    for call in reversed(state.get('tool_calls', [])):
        if call.get('name') != 'order.status':
            continue
        if not successful(call):
            if call.get('args', {}).get('order_id') in {None, order_id}:
                return None
            continue
        orders = [order for order in call.get('result', {}).get('orders', [])
                  if isinstance(order, dict) and order.get('order_id') == order_id]
        if orders:
            return orders[0] if len(orders) == 1 else None
        if call.get('args', {}).get('order_id') in {None, order_id}:
            return None
    return None


def verified_policy_product(state, args, order_id=None):
    sku = args.get('product_sku')
    if order_id:
        order = _policy_order(state, order_id)
        if order is None:
            return None, None
        skus = {line.get('sku') for line in order.get('lines', []) if isinstance(line, dict)}
        if not skus and order.get('sku'):
            skus.add(order['sku'])
        skus.discard(None)
        if sku in skus or not sku and len(skus) == 1:
            return sku or next(iter(skus)), 'order.status'
        return None, None
    if sku:
        for call in reversed(build_commerce_evidence(state)):
            if call.get('name') in CATALOG_TOOLS and any(item.get('sku') == sku or any(
                    v.get('variant_sku') == sku for v in item.get('variants', []) if isinstance(v, dict))
                    for item in call.get('result', {}).get('items', []) if isinstance(item, dict)):
                return sku, call['name']
    return None, None


def prepare_tool_call(state: TurnState, clock: Callable[[], datetime]) -> tuple[str, dict[str, Any]] | None:
    state.pop('tool_precondition_error', None)
    request = state["request"]
    decision = state["decision"]
    name = decision.tool_name or ""
    if name not in ALLOWED_TOOLS:
        return None
    args = dict(decision.tool_args)
    if name in {'pricing.get_quote', 'pricing.quote_order', 'order.create', 'order.update'}:
        address = args.get('address')
        if isinstance(address, str) and '[' in address:
            current = private_delivery_context(request.text, str(request.client_msg_id), request.on.isoformat())
            delivery = current if current is not None else state.get('private_delivery')
            actual = delivery.get('address') if isinstance(delivery, dict) else None
            if address.strip() != '[ĐỊA CHỈ ĐÃ ẨN]' or not actual or '[' in actual:
                return None
            args['address'] = actual
    if (name in {"inventory.check", "pricing.get_quote"}
            or name == 'order.create' and args.get('lines') is None):
        selected = catalog_variant(state, args)
        args["sku"] = selected
        args.pop("size", None)
        args.pop("color", None)
        if not args["sku"]:
            return None
    if name in _READ_TOOL_ARGS:
        args = {key: value for key, value in args.items() if key in _READ_TOOL_ARGS[name]}
    if name in {"inventory.check", "pricing.get_quote"} and not isinstance(args.get("sku"), str):
        return None
    if name in DATED_TOOLS:
        args["on"] = request.on.isoformat()
    if name == "policy.search":
        order_id = args.pop("order_id", None)
        args.pop("order_date", None)
        product, _ = verified_policy_product(state, args, order_id)
        if args.get('product_sku') and not product:
            return None
        if product:
            args['product_sku'] = product
        if order_id:
            order = _policy_order(state, order_id)
            if order is None:
                return None
            created = order.get("created_on") or order.get("created_at") or order.get("date")
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
    if name in {"order.status", "order.update", 'order.preview_update'}:
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
        from app.mcp_servers.mcp_order.schemas import CreateInput
        try:
            args = CreateInput.model_validate(args).model_dump(mode='json', exclude_none=True)
        except ValueError:
            return None
        evidence_error = order_evidence_error(state, args)
        if evidence_error is not None:
            state['tool_precondition_error'] = evidence_error
            return None
    if name == 'order.update':
        from app.mcp_servers.mcp_order.schemas import UpdateInput
        try:
            args = UpdateInput.model_validate(args).model_dump(mode='json', exclude_none=True)
        except ValueError:
            return None
    if name == 'order.preview_update':
        from app.mcp_servers.mcp_order.schemas import PreviewUpdateInput
        try:
            args = PreviewUpdateInput.model_validate(args).model_dump(mode='json', exclude_none=True)
        except ValueError:
            return None
    if name == 'schedule.callback':
        from app.mcp_servers.mcp_order.write_authorization import normalized_write
        try:
            args = normalized_write(name, args)
        except ValueError:
            return None
    return name, args


def order_evidence_error(state: TurnState, args: dict[str, Any]) -> str | None:
    if state.get('identity_status') != 'known':
        return 'identity_required'
    lines = args.get('lines') or [{'sku': args['sku'], 'qty': args['qty'],
                                  'price_vnd': args['price_vnd']}]
    quantities = Counter()
    for line in lines:
        quantities[line['sku']] += line.get('qty', 1)
    calls = build_commerce_evidence(state)
    items = [item for call in calls if call.get('name') in CATALOG_TOOLS
             for item in call['result'].get('items', []) if isinstance(item, dict)]
    for sku in quantities:
        parent = next((item for item in items if item.get('sku') == sku or any(
            variant.get('variant_sku') == sku for variant in item.get('variants', []))), None)
        if parent is None:
            return 'catalog_required'
        if sku == parent['sku'] and parent.get('variants'):
            return 'variant_selection_required'
    on = state['request'].on.isoformat()
    for sku, qty in quantities.items():
        stock = [call for call in calls if call.get('name') == 'inventory.check'
                 and call.get('args', {}).get('sku') == sku]
        if (not stock or stock[-1]['args'].get('on') != on
                or stock[-1]['result'].get('in_stock') is not True
                or type(stock[-1]['result'].get('qty')) is not int
                or stock[-1]['result']['qty'] < qty):
            return 'current_stock_required'
    if args.get('lines') is not None:
        quotes = [call for call in calls if call.get('name') == 'pricing.quote_order'
                  and call.get('args', {}).get('on') == on
                  and quote_context_matches(call, {**args, 'customer_phone': state.get('customer_phone')})]
        if not quotes:
            return 'current_quote_required'
        quoted = quotes[-1]['result']
        expected = Counter((unit['sku'], unit['final_price_vnd']) for unit in quoted.get('units', []))
        proposed = Counter((line['sku'], line['price_vnd']) for line in lines
                           for _ in range(line.get('qty', 1)))
        if expected != proposed or sum(price * qty for (_, price), qty in expected.items()) != quoted.get('total_vnd'):
            return 'price_mismatch'
    else:
        quotes = [call for call in calls if call.get('name') == 'pricing.get_quote'
                  and call.get('args', {}).get('sku') == args['sku']
                  and call['args'].get('on') == on
                  and call['args'].get('qty', 1) == args['qty']
                  and quote_context_matches(call, {**args, 'customer_phone': state.get('customer_phone')})]
        if not quotes:
            return 'current_quote_required'
        if quotes[-1]['result'].get('final_price_vnd') != args['price_vnd']:
            return 'price_mismatch'
    return None


def filter_owned_orders(name: str, args: dict[str, Any], result: dict[str, Any],
                        state: TurnState) -> dict[str, Any]:
    if name != "order.status" or not isinstance(result.get("orders"), list):
        return result
    owned = set(state.get("owned_order_ids", [])) | set(state.get("remembered_order_ids", []))
    return {**result, "orders": [order for order in result["orders"]
            if isinstance(order, dict) and order.get("order_id") in owned
            and (not args.get("order_id") or order.get("order_id") == args["order_id"])]}


def transaction_selection_mismatch(state: TurnState) -> bool:
    for call in state.get("tool_calls", []):
        if call.get("name") == "order.create" and call.get("result", {}).get("status") == "created":
            selection = resolve_product_selection(state, call.get("args", {}))
            if selection.status != "catalog_required" and selection.sku != call.get("args", {}).get("sku"):
                return True
    return False
