
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS, quote_context_hash


_FIELDS = {
    'catalog.get_details': ({'sku'}, {'items', 'total', 'requested_sku'}),
    "catalog.search": ({"query", "sku", "category", "max_price_vnd", "min_room_area_m2",
                        "include_discontinued", 'attribute_filters'}, {"items", "total"}),
    "inventory.check": ({"sku", "on"}, {"sku", "in_stock", "qty",
                                      "restock_expected", "discontinued", "successor_sku"}),
    "pricing.get_quote": ({"sku", "on", "qty"}, {"sku", "list_price_vnd",
        "final_price_vnd", "applied_promos", "expired_promos", "ineligible_promos",
        "not_applied_exclusive", "estimated_delivery", "freeship"}),
    "pricing.quote_order": ({'lines', 'on'}, {'units', 'lines', 'total_vnd', 'order_promos', 'freeship'}),
    "order.create": ({"sku", "qty", "price_vnd", "promo_code", "payment", "on", 'lines'},
                     {"order_id", "status", "total_vnd"}),
    'order.status': ({'order_id', 'on'}, {'order_id', 'orders', 'status', 'created_on', 'lines'}),
    'order.update': ({'order_id', 'action', 'line_index', 'qty', 'new_variant_sku', 'on'},
                     {'order_id', 'action', 'status', 'update_id', 'eligibility', 'estimate',
                      'requires_policy_check', 'fee_vnd', 'refund_vnd', 'net_payment_vnd',
                      'refund_days', 'line_index', 'qty', 'new_variant_sku'}),
    'order.preview_update': ({'order_id', 'action', 'line_index', 'qty', 'new_variant_sku', 'on'},
                            {'order_id', 'action', 'status', 'eligibility', 'estimate',
                             'requires_policy_check', 'fee_vnd', 'refund_vnd', 'net_payment_vnd',
                             'refund_days', 'line_index', 'qty', 'new_variant_sku'}),
    'policy.search': ({'query', 'on', 'customer_reported_order_date', 'order_date', 'product_sku'},
                      {'retrieval_status', 'context', 'evidence', 'evidence_set'}),
    "schedule.callback": ({"window", "reason", "on", 'callback_at', 'requested_callback_at'},
                          {"callback_id", "status", "window", 'callback_at', 'moved_from'}),
    "handoff.transfer": ({"reason"}, {"ticket_id", "status"}),
}
_PRODUCT_FIELDS = {"sku", "name", "category", "attributes", "variants", 'attribute_sources', 'attribute_conflicts',
                   'specifications', 'technical_evidence', 'technical_data_status', 'selected_variant', 'brand'}
_VARIANT_FIELDS = {"variant_sku", "size", "color", "price_delta_vnd"}
_PROMO_FIELDS = {"promo_code", "valid_until", "type", "discount_vnd", "gift_sku", "gift_qty", "reason"}


def _clean(value: Any, field='') -> Any:
    if isinstance(value, str):
        if field in {'source_hash', 'content_hash'} and len(value) == 64 and all(c in '0123456789abcdef' for c in value):
            return value
        return mask_pii(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item, key) for key, item in value.items()
                if not key.startswith('_') and key not in {'phone', 'customer_phone', 'address', 'candidates'}}
    return value


def _pick(value: Any, fields: set[str]) -> dict:
    return ({key: _clean(item) for key, item in value.items() if key in fields}
            if isinstance(value, dict) else {})


def memory_observations(calls: list[dict]) -> list[dict]:
    safe = []
    for call in calls:
        if len(safe) >= 20:
            break
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        if name not in _FIELDS or not isinstance(call.get("result"), dict):
            continue
        failed = ('error' in call['result'] or call['result'].get('ok') is False
                  or call['result'].get('success') is False)
        if failed and name not in CATALOG_TOOLS | {'inventory.check', 'pricing.get_quote', 'pricing.quote_order',
                                                   'order.status', 'order.preview_update', 'policy.search'}:
            continue
        args_fields, result_fields = _FIELDS[name]
        args = _pick(call.get("args"), args_fields)
        result = {'error': 'read_failed'} if failed else _pick(call["result"], result_fields)
        if (name == 'schedule.callback' and result.get('callback_id')
                and result.get('status') is None):
            result['status'] = 'scheduled'
        if name in {'pricing.quote_order', 'order.create'} and isinstance(args.get('lines'), list):
            args['lines'] = [_pick(line, {'sku', 'qty', 'price_vnd'}) for line in args['lines'] if isinstance(line, dict)]
        if name == 'pricing.quote_order':
            units = []
            for raw in result.get('units', []) or []:
                if not isinstance(raw, dict):
                    continue
                unit = _pick(raw, {'unit', 'line', 'sku', 'list_price_vnd', 'final_price_vnd'})
                unit['applied_promos'] = [_pick(promo, _PROMO_FIELDS) for promo in raw.get('applied_promos', []) or []
                                          if isinstance(promo, dict)]
                units.append(unit)
            result['units'] = units
            result['lines'] = [_pick(line, {'sku', 'qty', 'unit_prices_vnd', 'line_total_vnd'})
                               for line in result.get('lines', []) or [] if isinstance(line, dict)]
            result['order_promos'] = [_pick(promo, _PROMO_FIELDS) for promo in result.get('order_promos', []) or []
                                      if isinstance(promo, dict)]
        if name in CATALOG_TOOLS:
            items = []
            raw_items = call["result"].get("items")
            for item in raw_items[:20] if isinstance(raw_items, list) else []:
                if not isinstance(item, dict):
                    continue
                product = _pick(item, _PRODUCT_FIELDS)
                product["attributes"] = _clean(item.get("attributes") or {})
                variants = item.get("variants")
                product["variants"] = [_pick(variant, _VARIANT_FIELDS)
                    for variant in variants[:20] if isinstance(variant, dict)] \
                    if isinstance(variants, list) else []
                items.append(product)
            result["items"] = items
        elif name == "pricing.get_quote":
            for field in ("applied_promos", "expired_promos", 'ineligible_promos'):
                raw_promos = call["result"].get(field)
                result[field] = [(_pick(promo, _PROMO_FIELDS) if isinstance(promo, dict) else mask_pii(promo))
                    for promo in raw_promos[:10] if isinstance(promo, dict)
                    or field == 'expired_promos' and isinstance(promo, str)] \
                    if isinstance(raw_promos, list) else []
        item = {"name": name, "args": args, "result": result}
        if name in {'pricing.get_quote', 'pricing.quote_order'}:
            item['quote_context_hash'] = call.get('quote_context_hash') or quote_context_hash(call.get('args') or {})
        safe.append(item)
    return safe
