"""Pure BTC catalog, inventory, pricing and delivery rules shared by two services."""

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

def _catalog(products: list[dict], args: dict) -> dict:
    items = []
    for p in products:
        if args.get("sku") and p["sku"] != args["sku"] and not any(v["variant_sku"] == args["sku"] for v in p.get("variants", [])):
            continue
        if args.get("category") and not p["category"].startswith(args["category"]):
            continue
        if args.get("max_price_vnd") and p["list_price_vnd"] > args["max_price_vnd"]:
            continue
        if args.get("min_room_area_m2") and p["attributes"].get("room_area_m2", 0) < args["min_room_area_m2"]:
            continue
        if args.get("query") and not all(word in (p["name"] + " " + p["brand"] + " " + p["category"] + " " + p["sku"]).lower() for word in args["query"].lower().split()):
            continue
        if p["attributes"].get("discontinued") and not args.get("include_discontinued") and not args.get("sku"):
            continue
        items.append({"sku": p["sku"], "name": p["name"], "category": p["category"],
                      "list_price_vnd": p["list_price_vnd"], "attributes": p["attributes"],
                      "variants": [{key: v[key] for key in ("variant_sku", "size", "color", "price_delta_vnd")} for v in p.get("variants", [])]})
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
          once_used: set[tuple[str, str]] | None = None) -> dict:
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
        targets = pr["applies_to"]
        if not ("*" in targets or p["sku"] in targets or any(t.startswith("category:") and p["category"].startswith(t.split(":", 1)[1]) for t in targets)):
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
                      for other in others if other[0] and other[0]["category"].startswith("gia-dung/may-loc-khong-khi")]
            discount = int(base * pr["discount_percent"] / 100) if prices and base <= min(prices) else 0
            if discount == 0:
                ineligible.append({"promo_code": pr["promo_code"], "reason": "not_cheapest_item"})
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
