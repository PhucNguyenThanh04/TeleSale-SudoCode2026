#!/usr/bin/env python3
"""
Mock tool THAM CHIẾU của BTC — thuần Python, không phụ thuộc thư viện ngoài.
Nhóm có thể (a) bọc trực tiếp thành MCP server / function-calling, hoặc (b) tự viết nhưng phải cho
KẾT QUẢ GIỐNG file này trên cùng đầu vào (BTC chấm chéo dựa vào logic ở đây: giá sau KM, tồn kho theo ngày,
điều kiện KM, giới hạn COD). Chạy `python mock_tools.py --selftest` để xem ví dụ.

Mọi hàm nhận `on` (YYYY-MM-DD) = "ngày hôm nay" của cuộc gọi (lấy từ kịch bản: call_date hoặc reference_date + days_later).

Bản cập nhật 11/2026 (giải đáp thắc mắc về AIR-2ND-50):
  * Đơn nhiều máy dùng pricing.quote_order(lines) để lấy giá TỪNG MÁY, rồi order.create(lines=...) để tạo một đơn.
  * AIR-2ND-50: mỗi đơn chỉ MỘT máy lọc không khí được giảm 50% — máy có giá niêm yết thấp nhất (bằng giá thì chỉ một máy).
  * Mỗi máy nhận tối đa một chương trình không cộng dồn; máy được AIR-2ND-50 thì không nhận AIR-OCT, máy còn lại vẫn nhận
    chương trình có lợi nhất của riêng nó (KM-03/KM-04). TRADE-IN-AP áp tối đa 1 máy mỗi đơn (1 máy cũ đổi 1 máy mới).
"""
import json, os, re, sys, argparse
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(HERE, "..", "catalog")

def _load(name): return json.load(open(os.path.join(CAT, name), encoding="utf-8"))
PRODUCTS = _load("products.json")["products"]
PROMOS = _load("promotions.json")["promotions"]
CRM = _load("crm_seed.json")["customers"]
INV = _load("inventory_timeline.json")["events"]
REF = _load("products.json")["reference_date"]
HOLIDAYS = {"2026-10-26", "2027-01-01"}          # thong-bao-lich-nghi.md LN-02
AIR_CAT = "gia-dung/may-loc-khong-khi"

_BY_SKU = {p["sku"]: p for p in PRODUCTS}
_VAR = {v["variant_sku"]: (p, v) for p in PRODUCTS for v in p["variants"]}
_ORDERS = {}   # order_id -> order (runtime)
_CALLBACKS, _TICKETS, _ONCE_USED = [], [], set()

def _parent(sku):
    if sku in _BY_SKU: return _BY_SKU[sku], None
    if sku in _VAR: return _VAR[sku]
    return None, None

def _region_of(address):
    a = (address or "").lower()
    if any(k in a for k in ("hcm", "hồ chí minh", "sài gòn", "bình dương", "đồng nai", "cần thơ", "vũng tàu", "long an", "tiền giang", "an giang", "kiên giang")): return "nam"
    if any(k in a for k in ("đà nẵng", "huế", "quảng nam", "quảng ngãi", "bình định", "khánh hòa", "nha trang", "đắk lắk", "lâm đồng", "đà lạt", "quảng bình", "quảng trị", "bình thuận", "phú yên")): return "trung"
    return "bac"

def _owned_skus(phone):
    c = crm_get_customer(phone=phone)
    return {o["sku"] for o in c.get("orders", []) if o.get("status") == "delivered"} if c["found"] and not c.get("ambiguous") else set()

# ------------------------------------------------------------------ crm.get_customer
def crm_get_customer(phone=None, zalo_id=None, fb_id=None):
    hits = [c for c in CRM if (phone and c["phone"] == phone) or (zalo_id and c.get("zalo_id") == zalo_id) or (fb_id and c.get("fb_id") == fb_id)]
    if not hits: return {"found": False}
    if len(hits) > 1:   # SĐT dùng chung → trả cả hai, agent phải xác nhận danh tính
        return {"found": True, "ambiguous": True, "candidates": [{"customer_id": c["customer_id"], "name": c["name"], "honorific": c["honorific"], "sessions": c.get("sessions", []), "orders": c.get("orders", [])} for c in hits]}
    c = hits[0]
    return {"found": True, "ambiguous": False, "customer_id": c["customer_id"], "name": c["name"], "honorific": c["honorific"], "phone": c["phone"],
            "identities": {"zalo_id": c.get("zalo_id"), "fb_id": c.get("fb_id")}, "orders": c.get("orders", []) + [o for o in _ORDERS.values() if o["customer_phone"] == c["phone"]],
            "sessions": c.get("sessions", [])}

# ------------------------------------------------------------------ catalog.search
def catalog_search(query=None, category=None, sku=None, max_price_vnd=None, min_room_area_m2=None, include_discontinued=False):
    items = []
    for p in PRODUCTS:
        if sku and p["sku"] != sku and not any(v["variant_sku"] == sku for v in p["variants"]): continue
        if category and not p["category"].startswith(category): continue
        if max_price_vnd and p["list_price_vnd"] > max_price_vnd: continue
        if min_room_area_m2 and p["attributes"].get("room_area_m2", 0) < min_room_area_m2: continue
        if query:
            ql = query.lower()
            if not all(t in (p["name"] + " " + p["brand"] + " " + p["category"] + " " + p["sku"]).lower() for t in ql.split()): continue
        if p["attributes"].get("discontinued") and not include_discontinued and not sku: continue
        items.append({"sku": p["sku"], "name": p["name"], "category": p["category"], "list_price_vnd": p["list_price_vnd"], "attributes": p["attributes"],
                      "variants": [{k: v[k] for k in ("variant_sku", "size", "color", "price_delta_vnd")} for v in p["variants"]]})
    return {"items": items[:20], "total": len(items)}

# ------------------------------------------------------------------ inventory.check
def inventory_check(sku, on=REF):
    ev = sorted([e for e in INV if e["sku"] == sku and e["date"] <= on], key=lambda e: e["date"])
    p, v = _parent(sku)
    if p is None: return {"sku": sku, "error": "unknown_sku"}
    if p["attributes"].get("discontinued"): return {"sku": sku, "in_stock": False, "qty": 0, "discontinued": True, "successor_sku": p["attributes"].get("successor_sku")}
    qty = ev[-1]["qty"] if ev else (v["stock"] if v else p["stock"])
    out = {"sku": sku, "in_stock": qty > 0, "qty": qty}
    if qty == 0:
        nxt = sorted([e for e in INV if e["sku"] == sku and e["date"] > on and e["qty"] > 0], key=lambda e: e["date"])
        if nxt: out["restock_expected"] = nxt[0]["date"]
    return out

# ------------------------------------------------------------------ pricing.get_quote
def pricing_get_quote(sku, on=REF, qty=1, customer_phone=None, address=None, basket_skus=None, exclude=()):
    """Giá cuối cho 1 đơn vị `sku` theo dieu-khoan-khuyen-mai.md.
    basket_skus: các máy KHÁC trong cùng đơn — chỉ dùng cho trường hợp đơn giản (máy này rẻ hơn hẳn các máy kia).
    Đơn từ 2 máy trở lên (nhất là 2 máy cùng giá) → dùng pricing_quote_order(lines) để có giá từng máy chính xác.
    exclude: mã KM không xét (dùng nội bộ cho quote_order)."""
    p, v = _parent(sku)
    if p is None: return {"error": "unknown_sku"}
    base = p["list_price_vnd"] + (v["price_delta_vnd"] if v else 0)
    region = _region_of(address); owned = _owned_skus(customer_phone) if customer_phone else set()
    applied, expired, ineligible, candidates = [], [], [], []
    for pr in PROMOS:
        if pr["promo_code"] in exclude: continue
        targets = pr["applies_to"]
        hit = "*" in targets or p["sku"] in targets or any(t.startswith("category:") and p["category"].startswith(t.split(":", 1)[1]) for t in targets)
        if not hit: continue
        if not (pr["start"] <= on <= pr["end"]):
            if pr["end"] < on: expired.append(pr["promo_code"])
            continue   # chưa bắt đầu → không lộ
        cond = pr.get("conditions", {})
        why = None
        if cond.get("min_qty") and (qty + len(basket_skus or [])) < cond["min_qty"]: why = "min_qty"
        if cond.get("exclude_variant_size") and v and v.get("size") in cond["exclude_variant_size"]: why = "exclude_variant_size"
        if cond.get("region") and region not in cond["region"]: why = "region"
        if cond.get("requires_owned_sku") and cond["requires_owned_sku"] not in owned: why = "requires_owned_sku"
        if cond.get("once_per_customer") and (customer_phone, pr["promo_code"]) in _ONCE_USED: why = "once_per_customer"
        if pr.get("min_order_vnd") and base < pr["min_order_vnd"]: why = "min_order"
        if why: ineligible.append({"promo_code": pr["promo_code"], "reason": why}); continue
        if pr["type"] == "fixed": disc = pr["discount_vnd"]
        elif pr["type"] == "percent": disc = int(base * pr["discount_percent"] / 100)
        elif pr["type"] == "percent_second_item":
            others = [pricing_get_quote(s, on, 1, customer_phone, address)["list_price_vnd"] for s in (basket_skus or []) if _parent(s)[0] and _parent(s)[0]["category"].startswith(AIR_CAT)]
            # SỬA 11/2026: chỉ máy RẺ HƠN HẲN mới được giảm; hai máy bằng giá phải dùng pricing_quote_order để phân định
            disc = int(base * pr["discount_percent"] / 100) if others and base < min(others) else 0
            if disc == 0: ineligible.append({"promo_code": pr["promo_code"], "reason": "not_cheapest_item_or_tie_use_quote_order"}); continue
        else: disc = 0   # gift / freeship / freecod
        candidates.append((pr, disc))
    stackables = [(pr, dsc) for pr, dsc in candidates if pr.get("stackable")]
    exclusive = [(pr, dsc) for pr, dsc in candidates if not pr.get("stackable")]
    best = max(exclusive, key=lambda x: x[1], default=None)          # KM-04: có lợi nhất
    final = base - (best[1] if best else 0)
    for pr, dsc in stackables + ([best] if best else []):
        applied.append({"promo_code": pr["promo_code"], "type": pr["type"], "discount_vnd": dsc, **({"gift_sku": pr["gift_sku"]} if pr.get("gift_sku") else {})})
    floor_pct = {"gia-dung": 0.90, "thoi-trang": 0.80, "me-be": 0.92}
    return {"sku": sku, "list_price_vnd": base, "final_price_vnd": final, "applied_promos": applied, "expired_promos": expired, "ineligible_promos": ineligible,
            "not_applied_exclusive": [pr["promo_code"] for pr, _ in exclusive if best and pr["promo_code"] != best[0]["promo_code"]],
            "freeship": any(a["type"] == "freeship" for a in applied) or base >= 2000000,
            "_internal_price_floor_vnd": int(p["list_price_vnd"] * floor_pct.get(p["category"].split("/")[0], 0.9))}   # KHÔNG được lộ cho khách

# ------------------------------------------------------------------ pricing.quote_order (MỚI 11/2026)
def _second_item_promo(on):
    return next((pr for pr in PROMOS if pr["type"] == "percent_second_item" and pr["start"] <= on <= pr["end"]), None)

def pricing_quote_order(lines, on=REF, customer_phone=None, address=None, _second_item_used=False, _tie_prefer_first=False):
    """Giá TỪNG MÁY cho một đơn nhiều dòng. lines = [{"sku": ..., "qty": 1}, ...].
    Trả units (mỗi đơn vị một dòng, theo thứ tự trong đơn), lines (gộp theo dòng) và total_vnd.
      1) AIR-2ND-50: đơn có ≥ 2 máy lọc không khí (đếm theo số máy, kể cả cùng SKU) → đúng MỘT máy được giảm 50%:
         máy có giá niêm yết thấp nhất; bằng giá thì máy đứng sau cùng trong đơn. Máy thứ 3, 4… không được giảm thêm.
      2) Mỗi máy nhận tối đa một chương trình không cộng dồn (KM-03 "trên cùng một sản phẩm" = trên cùng một máy).
         Máy được AIR-2ND-50 không nhận AIR-OCT; các máy còn lại nhận chương trình có lợi nhất của riêng nó (KM-04).
      3) TRADE-IN-AP: tối đa 1 máy mỗi đơn (1 máy cũ đổi 1 máy mới), áp cho máy có lợi nhất.
      4) Chương trình cộng dồn (freeship, COD-0) xét theo đơn."""
    units = []
    for li, line in enumerate(lines):
        p, v = _parent(line["sku"])
        if p is None: return {"error": "unknown_sku", "sku": line["sku"]}
        for _ in range(int(line.get("qty", 1))):
            units.append({"line": li, "sku": line["sku"], "list_price_vnd": p["list_price_vnd"] + (v["price_delta_vnd"] if v else 0),
                          "is_air": p["category"].startswith(AIR_CAT)})
    sec = _second_item_promo(on)
    air_idx = [i for i, u in enumerate(units) if u["is_air"]]
    second_idx = None
    if sec and len(air_idx) >= 2 and not _second_item_used:
        low = min(units[i]["list_price_vnd"] for i in air_idx)
        ties = [i for i in air_idx if units[i]["list_price_vnd"] == low]
        second_idx = min(ties) if _tie_prefer_first else max(ties)      # bằng giá → máy đứng sau (tách đơn: đơn tạo sau)
    # chọn máy nhận TRADE-IN (nếu đủ điều kiện) = máy lợi nhất ngoài máy đã nhận AIR-2ND-50
    trade = next((pr for pr in PROMOS if pr.get("conditions", {}).get("requires_owned_sku")), None)
    trade_code = trade["promo_code"] if trade else None
    excl_base = (sec["promo_code"],) if sec else ()
    best_trade_i, best_gain = None, 0
    if trade_code:
        for i, u in enumerate(units):
            if i == second_idx: continue
            with_t = pricing_get_quote(u["sku"], on, 1, customer_phone, address, exclude=excl_base)
            without_t = pricing_get_quote(u["sku"], on, 1, customer_phone, address, exclude=excl_base + (trade_code,))
            gain = without_t["final_price_vnd"] - with_t["final_price_vnd"]
            if gain > best_gain: best_trade_i, best_gain = i, gain
    out_units, stack = [], {}
    for i, u in enumerate(units):
        ex = excl_base + ((trade_code,) if trade_code and i != best_trade_i else ())
        q = pricing_get_quote(u["sku"], on, 1, customer_phone, address, exclude=ex)
        final, applied = q["final_price_vnd"], [a for a in q["applied_promos"] if a["type"] not in ("freeship", "freecod")]
        if i == second_idx:
            disc = int(u["list_price_vnd"] * sec["discount_percent"] / 100)
            own_best = u["list_price_vnd"] - final
            if disc >= own_best:                                         # KM-04: lấy chương trình lợi hơn cho máy này
                final, applied = u["list_price_vnd"] - disc, [{"promo_code": sec["promo_code"], "type": sec["type"], "discount_vnd": disc}]
        for a in q["applied_promos"]:
            if a["type"] in ("freeship", "freecod"): stack[a["promo_code"]] = a
        out_units.append({"unit": i + 1, "line": u["line"], "sku": u["sku"], "list_price_vnd": u["list_price_vnd"], "final_price_vnd": final, "applied_promos": applied})
    out_lines = []
    for li, line in enumerate(lines):
        us = [x for x in out_units if x["line"] == li]
        out_lines.append({"sku": line["sku"], "qty": len(us), "unit_prices_vnd": [x["final_price_vnd"] for x in us], "line_total_vnd": sum(x["final_price_vnd"] for x in us)})
    total = sum(x["final_price_vnd"] for x in out_units)
    return {"units": out_units, "lines": out_lines, "total_vnd": total, "order_promos": list(stack.values()),
            "freeship": bool(stack.get("NAM-SHIP0")) or total >= 2000000,
            "note": "Khi giá trong một dòng khác nhau (VD 2 máy cùng SKU, 1 máy được giảm 50%), tạo đơn bằng mỗi máy một dòng qty=1."}

# ------------------------------------------------------------------ order.create
def order_create(customer_phone, sku=None, qty=1, price_vnd=None, promo_code=None, payment="COD", address=None, on=REF,
                 basket_skus=None, lines=None):
    """Tạo MỘT đơn.
    - Đơn 1 sản phẩm: sku + qty + price_vnd (như cũ).
    - Đơn nhiều dòng (MỚI): lines=[{"sku","qty","price_vnd"}...]; price_vnd = giá MỘT máy sau KM, lấy từ pricing.quote_order.
    - basket_skus: chỉ dùng khi TÁCH ĐƠN (QT-01) — liệt kê các máy lọc không khí đã/ sẽ đặt ở đơn khác cùng ngày, cùng SĐT.
      AIR-2ND-50 chỉ áp một lần cho tất cả các đơn tách cùng ngày cùng SĐT; máy bằng giá thì đơn tạo sau nhận giảm 50%."""
    if lines is None:
        if not sku: return {"error": "missing_sku_or_lines"}
        lines = [{"sku": sku, "qty": qty, "price_vnd": price_vnd}]
        extra = [{"sku": s, "qty": 1} for s in (basket_skus or [])]
    else:
        extra = []
    for ln in lines:
        inv = inventory_check(ln["sku"], on)
        if not inv.get("in_stock") or inv.get("qty", 0) < int(ln.get("qty", 1)): return {"error": "out_of_stock", **inv}
    same_day = [o for o in _ORDERS.values() if o["customer_phone"] == customer_phone and o["created_on"] == on]
    used_today = any("AIR-2ND-50" in o["promos"] for o in same_day)
    # tách đơn: máy bằng giá → đơn tạo SAU nhận AIR-2ND-50 (đơn trước đã tạo không có KM này)
    q = pricing_quote_order([{"sku": l["sku"], "qty": l.get("qty", 1)} for l in lines] + extra, on, customer_phone, address,
                            _second_item_used=used_today, _tie_prefer_first=bool(extra) and bool(same_day))
    if "error" in q: return q
    mine = [u for u in q["units"] if u["line"] < len(lines)]                    # bỏ các máy thuộc đơn tách khác
    # đối chiếu giá: mỗi đơn vị trong yêu cầu phải khớp đúng một đơn vị trong báo giá (cùng sku, cùng giá)
    want = sorted((l["sku"], l["price_vnd"]) for l in lines for _ in range(int(l.get("qty", 1))) if l.get("price_vnd") is not None)
    have = sorted((u["sku"], u["final_price_vnd"]) for u in mine)
    if want and want != have:
        return {"error": "price_mismatch", "expected_units": [{"sku": u["sku"], "price_vnd": u["final_price_vnd"]} for u in mine], "given": [{"sku": s, "price_vnd": p} for s, p in want]}
    total = sum(u["final_price_vnd"] for u in mine)
    if payment == "COD" and total > 10000000: return {"error": "cod_limit_exceeded", "limit_vnd": 10000000, "total_vnd": total}
    oid = f"OD{600000 + len(_ORDERS) + 1}"
    promos = sorted({a["promo_code"] for u in mine for a in u["applied_promos"]} | {a["promo_code"] for a in q["order_promos"]})
    for code in promos:
        _ONCE_USED.add((customer_phone, code))
    _ORDERS[oid] = {"order_id": oid, "customer_phone": customer_phone, "sku": lines[0]["sku"], "lines": [{"sku": u["sku"], "price_vnd": u["final_price_vnd"]} for u in mine],
                    "qty": len(mine), "price_vnd": mine[0]["final_price_vnd"], "total_vnd": total, "promos": promos, "payment": payment, "address": address,
                    "created_on": on, "status": "created"}
    return {"order_id": oid, "status": "created", "total_vnd": total, "needs_confirmation_call": payment == "COD" and total > 2000000,
            "estimated_delivery": _eta(on, address)}

def _eta(on, address):
    region_days = 2 if any(k in (address or "").lower() for k in ("hà nội", "ha noi", "hcm", "hồ chí minh", "đà nẵng")) else 4
    dt = datetime.strptime(on, "%Y-%m-%d").date(); n = 0
    while n < region_days:
        dt += timedelta(days=1)
        if dt.weekday() != 6 and dt.isoformat() not in HOLIDAYS: n += 1
    return dt.isoformat()

# ------------------------------------------------------------------ order.status / order.update
def order_status(order_id=None, customer_phone=None):
    found = [o for o in _ORDERS.values() if (order_id and o["order_id"] == order_id) or (customer_phone and o["customer_phone"] == customer_phone)]
    for c in CRM:
        for o in c.get("orders", []):
            if (order_id and o["order_id"] == order_id) or (customer_phone and c["phone"] == customer_phone): found.append(o)
    return {"orders": found}

def order_update(order_id, action, new_variant_sku=None, reason=None, on=REF):
    o = order_status(order_id=order_id)["orders"]
    if not o: return {"error": "order_not_found"}
    o = o[0]
    if action == "exchange_size" or action == "exchange_product":
        if not new_variant_sku: return {"error": "missing_new_variant_sku"}
        inv = inventory_check(new_variant_sku, on)
        if not inv.get("in_stock"): return {"error": "new_variant_out_of_stock", **inv}
        old_price = o.get("price_vnd"); new_price = pricing_get_quote(new_variant_sku, on, 1, o.get("customer_phone"))["final_price_vnd"]
        n_prev = sum(1 for t in _TICKETS if t["order_id"] == order_id and t["action"].startswith("exchange"))
        fee = 0 if n_prev == 0 else 60000                      # DT-03: lần 1 miễn phí, lần 2+: 30k/chiều ×2
        diff = new_price - old_price
        t = {"order_id": order_id, "action": action, "new_variant_sku": new_variant_sku, "fee_vnd": fee, "price_diff_vnd": diff,
             "refund_vnd": -diff if diff < 0 else 0, "extra_payment_vnd": diff if diff > 0 else 0, "refund_days": "3-5 ngày làm việc", "status": "pickup_scheduled"}
    elif action == "return":
        t = {"order_id": order_id, "action": "return", "reason": reason, "refund_vnd": o.get("price_vnd"), "refund_days": "3-5 ngày làm việc", "status": "pickup_scheduled"}
    elif action == "update_address":
        t = {"order_id": order_id, "action": "update_address", "status": "updated"}
    else: return {"error": "unknown_action"}
    _TICKETS.append(t); return t

# ------------------------------------------------------------------ schedule.callback / handoff.transfer
def schedule_callback(customer_phone, callback_at, note=None):
    dt = datetime.fromisoformat(callback_at)
    moved = None
    while dt.date().isoformat() in HOLIDAYS or dt.weekday() == 6 and not (9 <= dt.hour < 18):
        dt += timedelta(days=1); dt = dt.replace(hour=max(dt.hour, 8)); moved = dt.isoformat(timespec="minutes")
    if not (8 <= dt.hour < 21): dt = dt.replace(hour=8, minute=0); moved = dt.isoformat(timespec="minutes")
    cb = {"callback_id": f"CB{len(_CALLBACKS)+1:04d}", "customer_phone": customer_phone, "callback_at": dt.isoformat(timespec="minutes"), "moved_from": callback_at if moved else None, "note": note}
    _CALLBACKS.append(cb); return cb

REQUIRED_BRIEF = ["customer_phone", "customer_name", "escalation_reason", "conversation_summary", "product_advised", "price_quoted_vnd", "open_questions", "next_action", "generated_at"]
def handoff_transfer(brief):
    missing = [k for k in REQUIRED_BRIEF if k not in brief]
    if missing: return {"error": "brief_invalid", "missing": missing}
    t = {"ticket_id": f"HT{len(_TICKETS)+1:04d}", "status": "queued", "brief_ok": True}; _TICKETS.append({"order_id": None, "action": "handoff", **t}); return t

# ------------------------------------------------------------------ PII helper (gợi ý cho nhóm)
PII_PATTERNS = {"cccd": re.compile(r"\b0\d{11}\b"), "bank": re.compile(r"\b\d{9,14}\b"), "phone": re.compile(r"\b0\d{9}\b")}
def mask_pii(text):
    text = PII_PATTERNS["cccd"].sub(lambda m: m.group()[:4] + "****" + m.group()[-4:], text)
    text = PII_PATTERNS["bank"].sub(lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], text)
    return text

TOOLS = {"crm.get_customer": crm_get_customer, "catalog.search": catalog_search, "inventory.check": inventory_check, "pricing.get_quote": pricing_get_quote,
         "pricing.quote_order": pricing_quote_order, "order.create": order_create, "order.status": order_status, "order.update": order_update,
         "schedule.callback": schedule_callback, "handoff.transfer": handoff_transfer}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); a = ap.parse_args()
    if a.selftest:
        old = next((c for c in CRM if c.get("orders") and c["orders"][0]["sku"] == "SKU-AP-X-2024"), None)
        ex = [("2 máy AirPure Pro cùng đơn (AIR-OCT máy 1 + AIR-2ND-50 máy 2)", pricing_quote_order([{"sku": "SKU-AP-PRO", "qty": 2}])),
              ("Samsung AX40 + AirPure X (AP-X rẻ hơn được giảm 50%)", pricing_quote_order([{"sku": "SKU-SS-AX40"}, {"sku": "SKU-AP-X"}])),
              ("3 máy AirPure Pro (chỉ 1 máy được giảm 50%)", pricing_quote_order([{"sku": "SKU-AP-PRO", "qty": 3}]))]
        if old:
            ex.append(("Khách có AirPure X 2024 mua 2 Pro (TRADE-IN 1 máy, AIR-2ND-50 1 máy)", pricing_quote_order([{"sku": "SKU-AP-PRO", "qty": 2}], customer_phone=old["phone"])))
        for name, r in ex:
            print(f"\n## {name}\n  total={r['total_vnd']:,}  units=" + json.dumps([(u["sku"], u["final_price_vnd"], [p["promo_code"] for p in u["applied_promos"]]) for u in r["units"]], ensure_ascii=False))
