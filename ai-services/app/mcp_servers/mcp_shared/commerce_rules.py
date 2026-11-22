
import unicodedata
import re
import json
from datetime import date, timedelta

from app.constants import CATALOG_RESULT_LIMIT
from app.mcp_servers.mcp_shared.business_calendar import load_calendar


HOLIDAYS = {day for day, rule in load_calendar()['dates'].items() if rule.get('delivery_closed')}

def _parent(products: list[dict], sku: str) -> tuple[dict | None, dict | None]:
    for product in products:
        if product["sku"] == sku:
            return product, None
        for variant in product.get("variants", []):
            if variant["variant_sku"] == sku:
                return product, variant
    return None, None


def _promotion_applies(product: dict, variant: dict | None, promo: dict) -> bool:
    return any(target == '*' or target == product['sku']
               or variant is not None and target == variant['variant_sku']
               or target.startswith('category:') and (
                   product['category'] == target.split(':', 1)[1]
                   or product['category'].startswith(target.split(':', 1)[1] + '/'))
               for target in promo['applies_to'])

def _region(address: str | None) -> str:
    value = (address or "").lower()
    if any(x in value for x in ("hcm", "hồ chí minh", "sài gòn", "bình dương", "đồng nai", "cần thơ", "vũng tàu", "long an", "tiền giang", "an giang", "kiên giang")):
        return "nam"
    if any(x in value for x in ("đà nẵng", "huế", "quảng nam", "quảng ngãi", "bình định", "khánh hòa", "nha trang", "đắk lắk", "lâm đồng", "đà lạt", "quảng bình", "quảng trị", "bình thuận", "phú yên")):
        return "trung"
    return "bac"

def _delivery(on: str, address: str | None) -> str:
    days = 2 if any(x in (address or "").lower() for x in ("hà nội", "ha noi", "hcm", "hồ chí minh", "đà nẵng")) else 4
    current = date.fromisoformat(on)
    while days:
        current += timedelta(days=1)
        if current.weekday() != 6 and current.isoformat() not in HOLIDAYS:
            days -= 1
    return current.isoformat()

def _search_text(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    return "".join(char for char in unicodedata.normalize("NFD", value)
                   if unicodedata.category(char) != "Mn")


def _catalog(products: list[dict], args: dict) -> dict:
    ranked = []
    def tokens(value):
        return set(re.findall(r"[^\W\d_]+|\d+(?:[.,]\d+)?", _search_text(value)))
    def matches(actual, expected):
        if type(actual) is bool or type(expected) is bool:
            return type(actual) is type(expected) and actual == expected
        if type(expected) in {int, float}:
            return type(actual) in {int, float} and actual == expected
        return isinstance(actual, str) and _search_text(expected) in _search_text(actual)
    query = _search_text(args.get("query") or "")
    query_terms = tokens(query)
    brands = {p['brand'] for p in products if any(
        len(term) >= 3 and term in query_terms for term in tokens(p.get('brand', '')))}
    prefixes = []
    for p in products:
        name, brand = _search_text(p['name']), _search_text(p.get('brand', ''))
        prefix = name.split(brand, 1)[0].strip() if brand and brand in name else ''
        if prefix and re.search(r'(?<!\w)' + re.escape(prefix) + r'(?!\w)', query):
            prefixes.append((len(prefix), p['category']))
    categories = {category for length, category in prefixes
                  if length == max((n for n, _ in prefixes), default=0)}
    model_terms = {term for term in query_terms if any(char.isdigit() for char in term)
                   or term in {'pro', 'lite', 'mini', 'max', 'plus', 'ultra'}} if len(brands) == 1 else set()
    for p in products:
        if any(key not in p['attributes'] or not matches(p['attributes'][key], value)
               for key, value in (args.get('attribute_filters') or {}).items()):
            continue
        if args.get("sku") and p["sku"] != args["sku"] and not any(v["variant_sku"] == args["sku"] for v in p.get("variants", [])):
            continue
        if args.get("category") and not _search_text(p["category"]).startswith(
                _search_text(args["category"])):
            continue
        if args.get("max_price_vnd") and p["list_price_vnd"] > args["max_price_vnd"]:
            continue
        if args.get("min_room_area_m2") and p["attributes"].get("room_area_m2", 0) < args["min_room_area_m2"]:
            continue
        if brands and p.get('brand') not in brands:
            continue
        if categories and p['category'] not in categories:
            continue
        searchable = tokens(" ".join((p["name"], p["brand"], p["category"], p["sku"],
                                      json.dumps(p['attributes'], ensure_ascii=False))))
        if not model_terms <= searchable:
            continue
        score = len(query_terms & searchable)
        if query_terms and score == 0:
            continue
        if p["attributes"].get("discontinued") and not args.get("include_discontinued") and not args.get("sku"):
            continue
        ranked.append((score, {"sku": p["sku"], "name": p["name"], "category": p["category"],
                      "list_price_vnd": p["list_price_vnd"], "attributes": p["attributes"],
                      "variants": [{key: v[key] for key in ("variant_sku", "size", "color", "price_delta_vnd")} for v in p.get("variants", [])],
                      **{key: p[key] for key in ('attribute_sources', 'attribute_conflicts') if key in p}}))
    ranked.sort(key=lambda entry: -entry[0])
    items = [item for _, item in ranked]
    return {"items": items[:CATALOG_RESULT_LIMIT], "total": len(items)}

def _inventory(products: list[dict], events: list[dict], sku: str, on: str) -> dict:
    p, v = _parent(products, sku)
    if p is None:
        return {"sku": sku, "error": "unknown_sku"}
    if p["attributes"].get("discontinued"):
        return {"sku": sku, "in_stock": False, "qty": 0, "discontinued": True,
                "successor_sku": p["attributes"].get("successor_sku")}
    before = sorted((e for e in events if e["sku"] == sku and e["date"] <= on), key=lambda e: e["date"])
    qty = before[-1]["qty"] if before else (v["stock"] if v else p["stock"])
    result = {"sku": sku, "in_stock": qty > 0, "qty": qty}
    if qty == 0:
        after = sorted((e for e in events if e["sku"] == sku and e["date"] > on and e["qty"] > 0), key=lambda e: e["date"])
        if after:
            result["restock_expected"] = after[0]["date"]
    return result

def quote(products: list[dict], promos: list[dict], args: dict,
          owned_skus: set[str] | None = None,
          once_used: set[tuple[str, str]] | None = None, *, exclude=()) -> dict:
    sku, on = args["sku"], args["on"]
    p, v = _parent(products, sku)
    if p is None:
        return {"error": "unknown_sku"}
    base = p["list_price_vnd"] + (v["price_delta_vnd"] if v else 0)
    phone = args.get("customer_phone")
    owned = owned_skus or set()
    once_used = once_used or set()
    applied, expired, ineligible, candidates = [], [], [], []
    basket = args.get("basket_skus") or []
    qty = args.get("qty", 1)
    for pr in promos:
        if pr['promo_code'] in exclude:
            continue
        if not _promotion_applies(p, v, pr):
            continue
        if not (pr["start"] <= on <= pr["end"]):
            if pr["end"] < on:
                expired.append(pr["promo_code"])
            continue
        cond = pr.get("conditions") or {}
        why = None
        if cond.get("min_qty") and qty + len(basket) < cond["min_qty"]: why = "min_qty"
        if cond.get("exclude_variant_size") and v and v.get("size") in cond["exclude_variant_size"]: why = "exclude_variant_size"
        if cond.get("region") and _region(args.get("address")) not in cond["region"]: why = "region"
        if cond.get("requires_owned_sku") and cond["requires_owned_sku"] not in owned: why = "requires_owned_sku"
        if cond.get("once_per_customer") and (phone, pr["promo_code"]) in once_used: why = "once_per_customer"
        if pr.get("min_order_vnd") and base < pr["min_order_vnd"]: why = "min_order"
        if why:
            ineligible.append({"promo_code": pr["promo_code"], "reason": why})
            continue
        if pr["type"] == "fixed": discount = pr["discount_vnd"]
        elif pr["type"] == "percent": discount = int(base * pr["discount_percent"] / 100)
        elif pr["type"] == "percent_second_item":
            others = [(_parent(products, other)[0], _parent(products, other)[1]) for other in basket]
            prices = [other[0]["list_price_vnd"] + (other[1]["price_delta_vnd"] if other[1] else 0)
                      for other in others if other[0] and _promotion_applies(other[0], other[1], pr)]
            discount = int(base * pr["discount_percent"] / 100) if prices and base < min(prices) else 0
            if discount == 0:
                ineligible.append({"promo_code": pr["promo_code"], "reason": "not_cheapest_item_or_tie_use_quote_order"})
                continue
        else:
            discount = 0
        candidates.append((pr, discount))
    stackables = [(p, d) for p, d in candidates if p.get("stackable")]
    exclusive = [(p, d) for p, d in candidates if not p.get("stackable")]
    best = max(exclusive, key=lambda entry: entry[1], default=None)
    final = max(0, base - (best[1] if best else 0) - sum(d for _, d in stackables))
    for pr, discount in stackables + ([best] if best else []):
        applied.append({"promo_code": pr["promo_code"], "type": pr["type"], "discount_vnd": discount,
                        **({"gift_sku": pr["gift_sku"]} if pr.get("gift_sku") else {})})
    return {"sku": sku, "list_price_vnd": base, "final_price_vnd": final,
            "applied_promos": applied, "expired_promos": expired, "ineligible_promos": ineligible,
            "not_applied_exclusive": [p["promo_code"] for p, _ in exclusive if best and p["promo_code"] != best[0]["promo_code"]],
            "freeship": any(a["type"] == "freeship" for a in applied) or base >= 2_000_000}


def quote_order(products: list[dict], promos: list[dict], args: dict,
                owned_skus: set[str] | None = None,
                once_used: set[tuple[str, str]] | None = None, *,
                used_today: set[str] | None = None, tie_prefer_first: bool = False) -> dict:
    lines = args.get('lines')
    if (not isinstance(lines, list) or not lines or any(
            not isinstance(line, dict) or not isinstance(line.get('sku'), str)
            or type(line.get('qty', 1)) is not int or line.get('qty', 1) < 1 for line in lines)):
        return {'error': 'invalid_lines'}
    units = []
    for index, line in enumerate(lines):
        product, variant = _parent(products, line['sku'])
        if product is None:
            return {'error': 'unknown_sku', 'sku': line['sku']}
        units.extend({'line': index, 'sku': line['sku'],
                      'list_price_vnd': product['list_price_vnd'] + (variant['price_delta_vnd'] if variant else 0)}
                     for _ in range(line.get('qty', 1)))
    seconds = [promo for promo in promos if promo['type'] == 'percent_second_item']
    excluded = tuple(promo['promo_code'] for promo in seconds)
    second_offers = {}
    for promo in seconds:
        if promo['promo_code'] in (used_today or set()):
            continue
        matching = [i for i, unit in enumerate(units)
                    if _promotion_applies(*_parent(products, unit['sku']), promo)]
        eligible = {}
        for i in matching:
            candidate = quote(products, [{**promo, 'type': 'percent'}],
                              {**args, 'sku': units[i]['sku'], 'qty': len(matching), 'basket_skus': []},
                              owned_skus, once_used)
            if candidate['applied_promos']:
                eligible[i] = candidate['applied_promos'][0]
        if len(eligible) < max(2, promo.get('conditions', {}).get('min_qty', 2)):
            continue
        cheapest = min(units[i]['list_price_vnd'] for i in eligible)
        tied = [i for i in eligible if units[i]['list_price_vnd'] == cheapest]
        index = min(tied) if tie_prefer_first else max(tied)
        applied = {**eligible[index], 'type': promo['type']}
        second_offers.setdefault(index, []).append((promo, applied))
    trade_codes = [promo['promo_code'] for promo in promos
                   if promo['type'] != 'percent_second_item'
                   and promo.get('conditions', {}).get('requires_owned_sku')]

    def unit_quote(unit, exclude):
        return quote(products, promos, {**args, 'sku': unit['sku'], 'qty': 1, 'basket_skus': []},
                     owned_skus, once_used, exclude=exclude)

    trade_indices = {}
    for trade_code in trade_codes:
        trade_index, best_gain = None, 0
        for i, unit in enumerate(units):
            if i in second_offers:
                continue
            gain = (unit_quote(unit, excluded + (trade_code,))['final_price_vnd']
                    - unit_quote(unit, excluded)['final_price_vnd'])
            if gain > best_gain:
                trade_index, best_gain = i, gain
        trade_indices[trade_code] = trade_index
    priced, stack = [], {}
    stackable_codes = {promo['promo_code'] for promo in promos if promo.get('stackable')}
    for i, unit in enumerate(units):
        q = unit_quote(unit, excluded + tuple(code for code in trade_codes if trade_indices[code] != i))
        applied = [promo for promo in q['applied_promos'] if promo['type'] not in ('freeship', 'freecod')]
        for promo, benefit in second_offers.get(i, []):
            if promo.get('stackable'):
                applied.append(benefit)
            else:
                exclusive_discount = sum(p['discount_vnd'] for p in applied if p['promo_code'] not in stackable_codes)
                if benefit['discount_vnd'] >= exclusive_discount:
                    applied = [p for p in applied if p['promo_code'] in stackable_codes] + [benefit]
        final = max(0, unit['list_price_vnd'] - sum(p['discount_vnd'] for p in applied))
        for promo in q['applied_promos']:
            if promo['type'] in ('freeship', 'freecod'):
                stack[promo['promo_code']] = promo
        priced.append({'unit': i + 1, 'line': unit['line'], 'sku': unit['sku'],
                       'list_price_vnd': unit['list_price_vnd'], 'final_price_vnd': final,
                       'applied_promos': applied})
    grouped = []
    for i, line in enumerate(lines):
        prices = [unit['final_price_vnd'] for unit in priced if unit['line'] == i]
        grouped.append({'sku': line['sku'], 'qty': len(prices), 'unit_prices_vnd': prices,
                        'line_total_vnd': sum(prices)})
    total = sum(unit['final_price_vnd'] for unit in priced)
    return {'units': priced, 'lines': grouped, 'total_vnd': total,
            'order_promos': list(stack.values()), 'freeship': any(p['type'] == 'freeship' for p in stack.values()) or total >= 2_000_000,
            'note': 'Khi giá trong một dòng khác nhau (VD 2 máy cùng SKU, 1 máy được giảm 50%), tạo đơn bằng mỗi máy một dòng qty=1.'}
