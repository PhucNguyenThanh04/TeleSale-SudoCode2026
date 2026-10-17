"""Check which tool facts were actually communicated in the final answer."""

import re
from typing import Any

from app.agent.guardrails.checks import _money_claims
from app.constants import Slot


def _reported_money(answer: str, value: int) -> bool:
    amounts = {amount for amount, kind, negative in _money_claims(answer)
               if kind == "price" and not negative}
    if value in amounts:
        return True
    # Common spoken price: "năm triệu hai" = 5,200,000.
    words = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5,
             "sáu": 6, "bảy": 7, "tám": 8, "chín": 9}
    for match in re.finditer(r"(?i)\b(" + "|".join(words) +
                             r")\s+triệu(?:\s+(" + "|".join(words) + r"))?\b", answer):
        millions = words[match.group(1).lower()]
        fraction = words[match.group(2).lower()] if match.group(2) else 0
        if value == millions * 1_000_000 + fraction * 100_000:
            return True
    return False


def _product_named(answer: str, sku: str, calls: list[dict[str, Any]]) -> bool:
    if sku.casefold() in answer.casefold():
        return True
    names = [item.get("name") for call in calls if call.get("name") == "catalog.search"
             for item in call.get("result", {}).get("items", [])
             if isinstance(item, dict) and item.get("sku") == sku]
    return any(isinstance(name, str) and name.casefold() in answer.casefold()
               for name in names)


def reported_tool_fact(key: str, value: Any, answer: str,
                       calls: list[dict[str, Any]]) -> bool:
    """Tool evidence alone does not prove a quote or advice was given."""
    if key == Slot.PRODUCT_ADVISED:
        return isinstance(value, str) and _product_named(answer, value, calls)
    if key == Slot.PRICE_QUOTED_VND:
        quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
                  and call.get("result", {}).get("final_price_vnd") == value]
        quote_skus = {call.get("args", {}).get("sku") for call in quotes}
        return (type(value) is int and len(quote_skus) == 1
                and bool(quotes) and _reported_money(answer, value))
    if key == Slot.PROMO_CODE:
        return isinstance(value, str) and value.casefold() in answer.casefold()
    if key == Slot.PROMO_EXPIRY:
        return isinstance(value, str) and any(
            promo.get("valid_until") == value
            and str(promo.get("promo_code", "")).casefold() in answer.casefold()
            for call in calls if call.get("name") == "pricing.get_quote"
            for promo in call.get("result", {}).get("applied_promos", []))
    if key == Slot.VARIANT_SKU:
        return isinstance(value, str) and (value.casefold() in answer.casefold()
            or any(call.get("name") == "order.create"
                   and call.get("result", {}).get("status") == "created"
                   and call.get("args", {}).get("sku") == value for call in calls))
    if key == Slot.IN_STOCK:
        if value is True:
            return bool(re.search(r"(?i)còn hàng|có hàng|sẵn hàng", answer))
        if value is False:
            return bool(re.search(r"(?i)hết hàng", answer))
        return False
    return True


def reported_tool_candidates(answer: str, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive candidates from successful observations when the model omits them."""
    candidates: list[dict[str, Any]] = []
    for call in calls:
        result = call.get("result", {})
        if not isinstance(result, dict) or "error" in result:
            continue
        name = call.get("name")
        pairs: list[tuple[str, Any]] = []
        if name == "catalog.search":
            pairs.extend((Slot.PRODUCT_ADVISED, item.get("sku"))
                         for item in result.get("items", []) if isinstance(item, dict))
        elif name == "pricing.get_quote":
            pairs.extend([(Slot.PRODUCT_ADVISED, result.get("sku")),
                          (Slot.PRICE_QUOTED_VND, result.get("final_price_vnd"))])
            for promo in result.get("applied_promos", []):
                if isinstance(promo, dict):
                    pairs.append((Slot.PROMO_CODE, promo.get("promo_code")))
                    pairs.append((Slot.PROMO_EXPIRY, promo.get("valid_until")))
        elif name == "inventory.check":
            pairs.append((Slot.IN_STOCK, result.get("in_stock")))
        elif name == "order.create" and result.get("status") == "created":
            pairs.append((Slot.ORDER_ID, result.get("order_id")))
            ordered_sku = call.get("args", {}).get("sku")
            catalog_variants = {variant.get("variant_sku")
                for observation in calls if observation.get("name") == "catalog.search"
                for item in observation.get("result", {}).get("items", [])
                if isinstance(item, dict)
                for variant in item.get("variants", []) if isinstance(variant, dict)}
            if ordered_sku in catalog_variants:
                pairs.append((Slot.VARIANT_SKU, ordered_sku))
        for key, value in pairs:
            if type(value) not in {str, int, float, bool}:
                continue
            if reported_tool_fact(key, value, answer, calls):
                candidates.append({"key": key, "value": value, "source": "tool",
                                   "origin": "verified_observation"})
    return candidates
