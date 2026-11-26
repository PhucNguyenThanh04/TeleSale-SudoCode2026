from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS

import re
from typing import Any

from app.agent.guardrails.checks import _money_claims
from app.constants import Slot
from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus


def _reported_money(answer: str, value: int) -> bool:
    amounts = {amount for amount, kind, negative in _money_claims(answer)
               if kind == "price" and not negative}
    if value in amounts:
        return True
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
    items = [item for call in calls if call.get("name") in CATALOG_TOOLS
             for item in call.get("result", {}).get("items", [])
             if isinstance(item, dict) and isinstance(item.get("name"), str)
             and isinstance(item.get("sku"), str)]
    aliases: dict[str, set[str]] = {}
    for item in items:
        if "+" in item["name"]:
            full_name = item["name"].strip().casefold()
            if len(full_name) >= 6:
                aliases.setdefault(full_name, set()).add(item["sku"])
            continue
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
    promos = [item for item in quote.get("applied_promos", [])
              if isinstance(item, dict)]
    clauses = re.split(r"(?<=[!?;\n])|(?<!\d)\.(?!\d)", answer)
    for clause in clauses:
        if "?" in clause or re.search(
                r"(?i)\b(?:không|chưa|hết hạn|kiểm tra|xác minh|tra cứu|nếu)\b", clause):
            continue
        codes = [item for item in promos if isinstance(item.get("promo_code"), str)
                 and re.search(r"(?<![\w-])" + re.escape(item["promo_code"]) +
                               r"(?![\w-])", clause, re.IGNORECASE)]
        matches = codes
        if not codes:
            amounts = {amount for amount, kind, negative in _money_claims(clause)
                       if kind == "discount" and not negative}
            percentages = [float(value.replace(",", ".")) for value in re.findall(
                r"(?i)(\d+(?:[.,]\d+)?)\s*(?:%|phần trăm)", clause)]
            base = quote.get("list_price_vnd")
            matches = []
            for item in promos:
                kind, discount = item.get("type"), item.get("discount_vnd")
                monetary = (kind in {"fixed", "percent"}
                            and isinstance(discount, (int, float)) and discount > 0
                            and (discount in amounts or (
                                kind == "percent" and isinstance(base, (int, float))
                                and base > 0 and re.search(r"(?i)giảm|chiết khấu", clause)
                                and any(abs(base * percent / 100 - discount) <= 1
                                        for percent in percentages))))
                gift = kind == "gift" and re.search(r"(?i)\b(?:tặng|biếu)\b", clause)
                shipping = (kind == "freeship" and quote.get("freeship") is True
                            and re.search(r"(?i)miễn phí vận chuyển|\bfreeship\b", clause))
                if monetary or gift or shipping:
                    matches.append(item)
            benefit = promo.get("type")
            kinds = {"fixed", "percent"} if benefit in {"fixed", "percent"} else {benefit}
            matches = [item for item in matches if item.get("type") in kinds]
        if len(matches) != 1 or matches[0] != promo:
            continue
        deadlines = re.findall(
            r"(?i)(?:đến|hạn)(?:\s+ngày)?\s+(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", clause)
        expiry = str(promo.get("valid_until", ""))
        if deadlines and any(
                expiry[5:10] != f"{int(month):02d}-{int(day):02d}"
                or (year and expiry[:4] != year) for day, month, year in deadlines):
            continue
        iso_deadlines = re.findall(
            r"(?i)(?:đến|hạn)(?:\s+ngày)?\s+(\d{4}-\d{2}-\d{2})", clause)
        if any(deadline != expiry for deadline in iso_deadlines):
            continue
        return True
    return False


def _gift_only_skus(calls: list[dict[str, Any]]) -> set[str]:
    gift_skus = {
        promo["gift_sku"]
        for call in calls
        if isinstance(call.get("result"), dict) and "error" not in call["result"]
        and call.get("name") in {"pricing.get_quote", "pricing.quote_order"}
        for quote in [call["result"], *(call["result"].get("units") or [])]
        if isinstance(quote, dict)
        for promo in quote.get("applied_promos") or []
        if isinstance(promo, dict) and promo.get("type") == "gift"
        and isinstance(promo.get("gift_sku"), str) and promo["gift_sku"]
    }
    direct_skus = {
        item.get("sku")
        for call in calls
        if isinstance(call.get("result"), dict) and "error" not in call["result"]
        and call.get("name") == "catalog.search"
        for item in call["result"].get("items") or []
        if isinstance(item, dict) and isinstance(item.get("sku"), str)
    } | {
        call.get("result", {}).get("sku") or call.get("args", {}).get("sku")
        for call in calls
        if isinstance(call.get("result"), dict) and "error" not in call["result"]
        and call.get("name") == "order.create"
        and call['result'].get('status') == 'created'
        and call['result'].get('ok') is not False and call['result'].get('success') is not False
        and isinstance(call['result'].get('order_id'), str) and call['result']['order_id'].strip()
    } | {
        unit.get("sku")
        for call in calls
        if isinstance(call.get("result"), dict) and "error" not in call["result"]
        and call.get("name") == "pricing.quote_order"
        for unit in call["result"].get("units") or []
        if isinstance(unit, dict) and isinstance(unit.get("sku"), str)
    }
    return gift_skus - direct_skus


def _product_segments(answer: str, sku: str, calls: list[dict[str, Any]]) -> list[str]:
    gift_only = _gift_only_skus(calls)
    names: dict[str, set[str]] = {}
    for call in calls:
        item_sku = call.get("args", {}).get("sku")
        if isinstance(item_sku, str) and item_sku not in gift_only:
            names.setdefault(item_sku, set()).add(item_sku)
        if call.get("name") in CATALOG_TOOLS:
            for item in call.get("result", {}).get("items") or []:
                if isinstance(item, dict) and isinstance(item.get("sku"), str) and item["sku"] not in gift_only:
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
    named_skus = set()
    gift_only = _gift_only_skus(calls)
    if sku and key in {Slot.PRICE_QUOTED_VND, Slot.IN_STOCK, Slot.PROMO_CODE, Slot.PROMO_EXPIRY}:
        named_skus = resolve_claim_skus(answer, calls) - gift_only
        named_skus.update(item['sku'] for call in calls if call.get('name') in CATALOG_TOOLS
            and 'error' not in call.get('result', {})
            for item in call['result'].get('items') or [] if isinstance(item, dict) and item.get('sku')
            and item['sku'] not in gift_only
            and _product_named(answer, item['sku'], calls))
        if named_skus and sku not in named_skus:
            return False
    if key == Slot.PRODUCT_ADVISED:
        return isinstance(value, str) and value not in gift_only and _product_named(answer, value, calls)
    if key == Slot.PRICE_QUOTED_VND:
        quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
                  and call.get("result", {}).get("final_price_vnd") == value
                  and (sku is None or call.get("args", {}).get("sku") == sku)]
        quote_skus = {call.get("args", {}).get("sku") for call in quotes}
        if sku is not None:
            all_skus = {call.get("args", {}).get("sku") for call in calls
                        if call.get("name") == "pricing.get_quote"}
            if all_skus == {sku} and len(named_skus) <= 1:
                return bool(quotes) and _reported_money(answer, value)
            return bool(quotes) and any(_reported_money(segment, value)
                for segment in _product_segments(answer, sku, calls))
        return (type(value) is int and len(quote_skus) == 1
                and bool(quotes) and _reported_money(answer, value))
    if key in {Slot.PROMO_CODE, Slot.PROMO_EXPIRY}:
        quotes = [call for call in calls if call.get("name") == "pricing.get_quote"
                  and "error" not in call.get("result", {})]
        quoted_skus = {call.get("args", {}).get("sku") for call in quotes}
        text = (" ".join(_product_segments(answer, sku, calls))
                if sku and (len(quoted_skus) > 1 or len(named_skus) > 1) else answer)
        field = "promo_code" if key == Slot.PROMO_CODE else "valid_until"
        return isinstance(value, str) and any(
            promo.get(field) == value
            and (not call.get("args", {}).get("on") or not promo.get("valid_until")
                 or promo["valid_until"] >= call["args"]["on"])
            and _reported_promo(promo, text, call["result"])
            for call in quotes if (sku is None or call.get("args", {}).get("sku") == sku)
            and call.get("result", {}).get("sku", sku) == call.get("args", {}).get("sku")
            for promo in call.get("result", {}).get("applied_promos", [])
            if isinstance(promo, dict))
    if key == Slot.VARIANT_SKU:
        return isinstance(value, str) and (value.casefold() in answer.casefold()
            or any(call.get("name") == "order.create"
                   and call.get("result", {}).get("status") == "created"
                   and call.get("args", {}).get("sku") == value for call in calls))
    if key == Slot.IN_STOCK:
        stock_skus = {call.get("args", {}).get("sku") for call in calls
                      if call.get("name") == "inventory.check"}
        text = (" ".join(_product_segments(answer, sku, calls))
                if sku and (len(stock_skus) > 1 or len(named_skus) > 1) else answer)
        if value is True:
            return bool(re.search(r"(?i)còn hàng|có hàng|sẵn hàng", text))
        if value is False:
            return bool(re.search(r"(?i)hết hàng", text))
        return False
    if key == Slot.ALT_SUGGESTED:
        return isinstance(value, str) and _product_named(answer, value, calls)
    if key == Slot.CALLBACK_SCHEDULED:
        return value is True and any(
            call.get("name") == "schedule.callback"
            and call.get("result", {}).get("status") in {"scheduled", "ok", "created"}
            for call in calls)
    return True


def reported_tool_candidates(answer: str, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    gift_only_skus = _gift_only_skus(calls)
    for call in calls:
        result = call.get("result", {})
        if not isinstance(result, dict) or "error" in result:
            continue
        name = call.get("name")
        pairs: list[tuple[str, Any]] = []
        sku = None
        if name in CATALOG_TOOLS:
            pairs.extend((Slot.PRODUCT_ADVISED, item.get("sku"))
                         for item in result.get("items", [])
                         if isinstance(item, dict) and item.get("sku") not in gift_only_skus)
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
            if isinstance(result.get("successor_sku"), str) and result.get("successor_sku"):
                pairs.append((Slot.ALT_SUGGESTED, result.get("successor_sku")))
        elif name == "schedule.callback" and result.get("status") in {"scheduled", "ok", "created"}:
            pairs.append((Slot.CALLBACK_SCHEDULED, True))
        elif name == "order.create" and result.get("status") == "created":
            pairs.append((Slot.ORDER_ID, result.get("order_id")))
            ordered_sku = call.get("args", {}).get("sku")
            catalog_variants = {variant.get("variant_sku")
                for observation in calls if observation.get("name") in CATALOG_TOOLS
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
                if isinstance(item_sku, str) and key not in {Slot.ORDER_ID, Slot.CALLBACK_SCHEDULED}:
                    candidate.update(scope_type="product", scope_id=item_sku, sku=item_sku)
                candidates.append(candidate)
    return candidates
