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
    items = [item for call in calls if call.get("name") == "catalog.search"
             for item in call.get("result", {}).get("items", [])
             if isinstance(item, dict) and isinstance(item.get("name"), str)
             and isinstance(item.get("sku"), str)]
    aliases: dict[str, set[str]] = {}
    for item in items:
        words = item["name"].split()
        for count in range(2, min(len(words), 5) + 1):
            alias = " ".join(words[-count:]).casefold()
            if len(alias) >= 6:
                aliases.setdefault(alias, set()).add(item["sku"])
    return any(owners == {sku} and re.search(
        r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", answer, re.IGNORECASE)
        for alias, owners in aliases.items())


def _reported_promo(promo: dict[str, Any], answer: str,
                    quote: dict[str, Any]) -> bool:
    code = promo.get("promo_code")
    if isinstance(code, str) and code.casefold() in answer.casefold():
        return True
    gift_promos = [item for item in quote.get("applied_promos", [])
                   if isinstance(item, dict) and item.get("type") == "gift"]
    return (promo.get("type") == "gift" and len(gift_promos) == 1
            and promo == gift_promos[0]
            and bool(re.search(r"(?i)\b(?:tặng|biếu)\b[^.!?]{1,100}", answer))
            and not re.search(r"(?i)\b(?:không|chưa)\s+(?:được\s+)?(?:tặng|biếu)\b", answer))


def _product_segments(answer: str, sku: str, calls: list[dict[str, Any]]) -> list[str]:
    """Find local claims naming a product; equal values elsewhere do not count."""
    names: dict[str, set[str]] = {}
    for call in calls:
        item_sku = call.get("args", {}).get("sku")
        if isinstance(item_sku, str):
            names.setdefault(item_sku, set()).add(item_sku)
        if call.get("name") == "catalog.search":
            for item in call.get("result", {}).get("items", []):
                if isinstance(item, dict) and isinstance(item.get("sku"), str):
                    names.setdefault(item["sku"], set()).add(item["sku"])
                    if isinstance(item.get("name"), str):
                        names[item["sku"]].add(item["name"])
    tokens = [(match.start(), match.end(), item_sku)
              for item_sku, labels in names.items() for label in labels
              for match in re.finditer(r"(?i)(?<![\w-])" + re.escape(label) +
                                       r"(?![\w-])", answer)]
    tokens.sort()
    return [answer[start:tokens[index + 1][0] if index + 1 < len(tokens) else len(answer)]
            for index, (start, _end, item_sku) in enumerate(tokens) if item_sku == sku]


def reported_tool_fact(key: str, value: Any, answer: str,
                       calls: list[dict[str, Any]], sku: str | None = None) -> bool:
    """Tool evidence alone does not prove a quote or advice was given."""
    if key == Slot.PRODUCT_ADVISED:
        return isinstance(value, str) and _product_named(answer, value, calls)
    if key == Slot.PRICE_QUOTED_VND:
        quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
                  and call.get("result", {}).get("final_price_vnd") == value
                  and (sku is None or call.get("args", {}).get("sku") == sku)]
        quote_skus = {call.get("args", {}).get("sku") for call in quotes}
        if sku is not None:
            all_skus = {call.get("args", {}).get("sku") for call in calls
                        if call.get("name") == "pricing.get_quote"}
            if all_skus == {sku}:
                return bool(quotes) and _reported_money(answer, value)
            return bool(quotes) and any(_reported_money(segment, value)
                for segment in _product_segments(answer, sku, calls))
        return (type(value) is int and len(quote_skus) == 1
                and bool(quotes) and _reported_money(answer, value))
    if key == Slot.PROMO_CODE:
        quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
                  and (sku is None or call.get("args", {}).get("sku") == sku)]
        quote_skus = {call.get("args", {}).get("sku") for call in quotes}
        text = (" ".join(_product_segments(answer, sku, calls))
                if sku and len(quote_skus) > 1 else answer)
        return any(_reported_promo(promo, text, call["result"])
                   for call in quotes for promo in call.get("result", {}).get("applied_promos", [])
                   if isinstance(promo, dict) and promo.get("promo_code") == value)
    if key == Slot.PROMO_EXPIRY:
        quoted_skus = {call.get("args", {}).get("sku") for call in calls
                       if call.get("name") == "pricing.get_quote"}
        text = (" ".join(_product_segments(answer, sku, calls))
                if sku and len(quoted_skus) > 1 else answer)
        return isinstance(value, str) and any(
            promo.get("valid_until") == value
            and _reported_promo(promo, text, call["result"])
            for call in calls if call.get("name") == "pricing.get_quote"
            and (sku is None or call.get("args", {}).get("sku") == sku)
            for promo in call.get("result", {}).get("applied_promos", []))
    if key == Slot.VARIANT_SKU:
        return isinstance(value, str) and (value.casefold() in answer.casefold()
            or any(call.get("name") == "order.create"
                   and call.get("result", {}).get("status") == "created"
                   and call.get("args", {}).get("sku") == value for call in calls))
    if key == Slot.IN_STOCK:
        stock_skus = {call.get("args", {}).get("sku") for call in calls
                      if call.get("name") == "inventory.check"}
        text = (" ".join(_product_segments(answer, sku, calls))
                if sku and len(stock_skus) > 1 else answer)
        if value is True:
            return bool(re.search(r"(?i)còn hàng|có hàng|sẵn hàng", text))
        if value is False:
            return bool(re.search(r"(?i)hết hàng", text))
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
        sku = None
        if name == "catalog.search":
            pairs.extend((Slot.PRODUCT_ADVISED, item.get("sku"))
                         for item in result.get("items", []) if isinstance(item, dict))
        elif name == "pricing.get_quote":
            sku = result.get("sku") or call.get("args", {}).get("sku")
            pairs.extend([(Slot.PRODUCT_ADVISED, result.get("sku")),
                          (Slot.PRICE_QUOTED_VND, result.get("final_price_vnd"))])
            for promo in result.get("applied_promos", []):
                if isinstance(promo, dict):
                    pairs.append((Slot.PROMO_CODE, promo.get("promo_code")))
                    pairs.append((Slot.PROMO_EXPIRY, promo.get("valid_until")))
        elif name == "inventory.check":
            sku = result.get("sku") or call.get("args", {}).get("sku")
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
            item_sku = value if key == Slot.PRODUCT_ADVISED else sku
            if reported_tool_fact(key, value, answer, calls, item_sku):
                candidate = {"key": key, "value": value, "source": "tool",
                             "origin": "verified_observation"}
                if isinstance(item_sku, str) and key != Slot.ORDER_ID:
                    candidate.update(scope_type="product", scope_id=item_sku, sku=item_sku)
                candidates.append(candidate)
    return candidates
