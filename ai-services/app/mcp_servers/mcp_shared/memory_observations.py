"""Allowlisted tool evidence that may cross into long-term memory."""

import json
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii


_FIELDS = {
    "catalog.search": ({"query", "sku"}, {"items", "total"}),
    "inventory.check": ({"sku", "on"}, {"sku", "in_stock", "qty",
                                      "restock_expected", "discontinued", "successor_sku"}),
    "pricing.get_quote": ({"sku", "on", "qty"}, {"sku", "list_price_vnd",
        "final_price_vnd", "applied_promos", "expired_promos"}),
    "order.create": ({"sku", "qty", "price_vnd", "promo_code", "payment", "on"},
                     {"order_id", "status", "total_vnd"}),
    "schedule.callback": ({"window", "reason", "on"}, {"callback_id", "status", "window"}),
    "handoff.transfer": ({"reason"}, {"ticket_id", "status"}),
}
_PRODUCT_FIELDS = {"sku", "name", "category", "attributes", "variants"}
_VARIANT_FIELDS = {"variant_sku", "size", "color", "price_delta_vnd"}
_ATTRIBUTE_FIELDS = {"room_area_m2", "child_safe_lock", "discontinued",
                     "successor_sku"}
_PROMO_FIELDS = {"promo_code", "valid_until", "type", "discount_vnd", "gift_sku"}


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    return value


def _pick(value: Any, fields: set[str]) -> dict:
    return ({key: _clean(item) for key, item in value.items() if key in fields}
            if isinstance(value, dict) else {})


def memory_observations(calls: list[dict]) -> list[dict]:
    """Keep only evidence needed for customer facts; exclude unknown fields and tools."""
    safe = []
    for call in calls[:20]:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        if name not in _FIELDS or not isinstance(call.get("result"), dict):
            continue
        if "error" in call["result"]:
            continue
        args_fields, result_fields = _FIELDS[name]
        args = _pick(call.get("args"), args_fields)
        result = _pick(call["result"], result_fields)
        if name == "catalog.search":
            items = []
            raw_items = call["result"].get("items")
            for item in raw_items[:20] if isinstance(raw_items, list) else []:
                if not isinstance(item, dict):
                    continue
                product = _pick(item, _PRODUCT_FIELDS)
                product["attributes"] = _pick(item.get("attributes"), _ATTRIBUTE_FIELDS)
                variants = item.get("variants")
                product["variants"] = [_pick(variant, _VARIANT_FIELDS)
                    for variant in variants[:20] if isinstance(variant, dict)] \
                    if isinstance(variants, list) else []
                items.append(product)
            result["items"] = items
        elif name == "pricing.get_quote":
            for field in ("applied_promos", "expired_promos"):
                raw_promos = call["result"].get(field)
                result[field] = [_pick(promo, _PROMO_FIELDS)
                    for promo in raw_promos[:10] if isinstance(promo, dict)] \
                    if isinstance(raw_promos, list) else []
        item = {"name": name, "args": args, "result": result}
        if len(json.dumps(item, ensure_ascii=False, default=str)) <= 20000:
            safe.append(item)
    return safe[:8]
