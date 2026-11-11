"""Pure BTC catalog, inventory, pricing and delivery rules shared by two services."""

import unicodedata
from datetime import date, timedelta

from app.constants import CATALOG_RESULT_LIMIT


HOLIDAYS = {"2026-10-26", "2027-01-01"}

def _parent(products: list[dict], sku: str) -> tuple[dict | None, dict | None]:
    for product in products:
        if product["sku"] == sku:
            return product, None
        for variant in product.get("variants", []):
            if variant["variant_sku"] == sku:
                return product, variant
    return None, None

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
    """Fold Vietnamese accents while retaining separators in category paths and SKUs."""
    value = value.casefold().replace("đ", "d")
    return "".join(char for char in unicodedata.normalize("NFD", value)
                   if unicodedata.category(char) != "Mn")


def _catalog(products: list[dict], args: dict) -> dict:
    ranked = []
    query_terms = _search_text(args.get("query") or "").split()
    for p in products:
        if args.get("sku") and p["sku"] != args["sku"] and not any(v["variant_sku"] == args["sku"] for v in p.get("variants", [])):
            continue
        if args.get("category") and not _search_text(p["category"]).startswith(
                _search_text(args["category"])):
            continue
        if args.get("max_price_vnd") and p["list_price_vnd"] > args["max_price_vnd"]:
            continue
        if args.get("min_room_area_m2") and p["attributes"].get("room_area_m2", 0) < args["min_room_area_m2"]:
            continue
        searchable = _search_text(" ".join((p["name"], p["brand"], p["category"], p["sku"])))
        score = sum(term in searchable for term in query_terms)
        if query_terms and score == 0:
            continue
        if p["attributes"].get("discontinued") and not args.get("include_discontinued") and not args.get("sku"):
            continue
        ranked.append((score, {"sku": p["sku"], "name": p["name"], "category": p["category"],
                      "list_price_vnd": p["list_price_vnd"], "attributes": p["attributes"],
                      "variants": [{key: v[key] for key in ("variant_sku", "size", "color", "price_delta_vnd")} for v in p.get("variants", [])]}))
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
        targets = pr["applies_to"]
        applicable_skus = {item["sku"] for item in products
                           if "*" in targets or item["sku"] in targets or any(
                               t.startswith("category:") and item["category"].startswith(t.split(":", 1)[1])
                               for t in targets)}
        if p["sku"] not in applicable_skus:
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
                      for other in others if other[0] and other[0]["sku"] in applicable_skus]
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
    final = base - (best[1] if best else 0)
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
                second_item_used: bool = False, tie_prefer_first: bool = False) -> dict:
    """BTC November prices per physical unit; never multiply one discounted price by qty."""
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
                      'list_price_vnd': product['list_price_vnd'] + (variant['price_delta_vnd'] if variant else 0),
                      'is_air': product['category'].startswith('gia-dung/may-loc-khong-khi')}
                     for _ in range(line.get('qty', 1)))
    second = next((promo for promo in promos if promo['type'] == 'percent_second_item'
                   and promo['start'] <= args['on'] <= promo['end']), None)
    air = [i for i, unit in enumerate(units) if unit['is_air']]
    second_index = None
    if second and len(air) >= 2 and not second_item_used:
        cheapest = min(units[i]['list_price_vnd'] for i in air)
        tied = [i for i in air if units[i]['list_price_vnd'] == cheapest]
        second_index = min(tied) if tie_prefer_first else max(tied)
    trade = next((promo for promo in promos if promo.get('conditions', {}).get('requires_owned_sku')), None)
    trade_code = trade['promo_code'] if trade else None
    excluded = (second['promo_code'],) if second else ()

    def unit_quote(unit, exclude):
        return quote(products, promos, {**args, 'sku': unit['sku'], 'qty': 1, 'basket_skus': []},
                     owned_skus, once_used, exclude=exclude)

    trade_index, best_gain = None, 0
    if trade_code:
        for i, unit in enumerate(units):
            if i == second_index:
                continue
            gain = (unit_quote(unit, excluded + (trade_code,))['final_price_vnd']
                    - unit_quote(unit, excluded)['final_price_vnd'])
            if gain > best_gain:
                trade_index, best_gain = i, gain
    priced, stack = [], {}
    for i, unit in enumerate(units):
        q = unit_quote(unit, excluded + ((trade_code,) if trade_code and i != trade_index else ()))
        final = q['final_price_vnd']
        applied = [promo for promo in q['applied_promos'] if promo['type'] not in ('freeship', 'freecod')]
        if i == second_index:
            discount = int(unit['list_price_vnd'] * second['discount_percent'] / 100)
            if discount >= unit['list_price_vnd'] - final:
                final = unit['list_price_vnd'] - discount
                applied = [{'promo_code': second['promo_code'], 'type': second['type'], 'discount_vnd': discount}]
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
            'order_promos': list(stack.values()), 'freeship': bool(stack.get('NAM-SHIP0')) or total >= 2_000_000}
