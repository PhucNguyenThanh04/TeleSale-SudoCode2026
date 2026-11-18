"""Order, callback and handoff decisions independent of MCP and SQL transport."""

import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.mcp_servers.mcp_shared.commerce_rules import HOLIDAYS, _delivery, _inventory, _parent, quote, quote_order


async def _identity(repo, session, args: dict) -> tuple[str | None, str | None]:
    matches = await repo.identity_matches(session, args.get("source_channel"), args.get("source_identity"))
    return (matches[0]["customer_id"], matches[0]["phone"]) if len(matches) == 1 else (None, None)


async def _quote(repo, session, args: dict, customer_id: str | None) -> dict:
    products = await repo.rows(session, "products")
    promos = await repo.rows(session, "promotions")
    owned = set()
    if customer_id and args.get("customer_phone"):
        customers = await repo.rows(session, "customers")
        customer = next((c for c in customers if c["customer_id"] == customer_id), None)
        if customer:
            owned = {o["sku"] for o in customer.get("orders", []) if o.get("status") == "delivered"}
    return quote(products, promos, args, owned, await repo.used_promos(session))


async def status(repo, session, args: dict, customer_id: str) -> dict:
    order_id = args.get("order_id")
    if order_id and not await repo.order_owned(session, order_id, customer_id):
        return {"error": "order_not_owned"}
    if args.get("customer_phone") and not await repo.phone_owned(session, args["customer_phone"], customer_id):
        return {"error": "customer_not_owned"}
    if not order_id and not args.get("customer_phone"):
        return {"error": "missing_order_lookup"}
    customers = await repo.rows(session, "customers")
    historical = [order for customer in customers if customer["customer_id"] == customer_id
                  for order in customer.get("orders", []) if not order_id or order["order_id"] == order_id]
    return {"orders": historical + await repo.runtime_orders(session, customer_id, order_id)}


async def create(repo, session, args: dict, customer_id: str, phone: str) -> dict:
    if args.get("customer_phone") != phone:
        return {"error": "identity_required"}
    if args.get("payment") not in {"COD", "bank", "momo", "zalopay"}:
        return {"error": "invalid_payment"}
    lines = args.get('lines') or [{'sku': args['sku'], 'qty': args['qty'], 'price_vnd': args.get('price_vnd')}]
    products = await repo.rows(session, "products")
    events = await repo.rows(session, 'inventory_events')
    quantities = {}
    for line in lines:
        quantity = line.get('qty', 1)
        if type(quantity) is not int or quantity < 1:
            return {'error': 'invalid_qty'}
        quantities[line['sku']] = quantities.get(line['sku'], 0) + quantity
    for sku, quantity in quantities.items():
        product, variant = _parent(products, sku)
        if product is not None and product.get('variants') and variant is None:
            return {'error': 'variant_selection_required'}
        inv = _inventory(products, events, sku, args['on'])
        if not inv.get('in_stock') or inv.get('qty', 0) < quantity:
            return {'error': 'out_of_stock', **inv}
    same_day = await repo.same_day_orders(session, phone, args['on'])
    used_today = {code for order in same_day for code in order['promos']}
    extra = [{'sku': sku, 'qty': 1} for sku in args.get('basket_skus') or []] if not args.get('lines') else []
    customers = await repo.rows(session, 'customers')
    customer = next((c for c in customers if c['customer_id'] == customer_id), None)
    owned = {o['sku'] for o in customer.get('orders', []) if o.get('status') == 'delivered'} if customer else set()
    quoted = quote_order(products, await repo.rows(session, 'promotions'),
                         {**args, 'lines': lines + extra}, owned, await repo.used_promos(session),
                         used_today=used_today, tie_prefer_first=bool(extra) and bool(same_day))
    if 'error' in quoted:
        return quoted
    mine = [unit for unit in quoted['units'] if unit['line'] < len(lines)]
    want = sorted((line['sku'], line['price_vnd']) for line in lines for _ in range(line.get('qty', 1)))
    have = sorted((unit['sku'], unit['final_price_vnd']) for unit in mine)
    if want != have:
        error = {'error': 'price_mismatch',
                 'expected_units': [{'sku': unit['sku'], 'price_vnd': unit['final_price_vnd']} for unit in mine],
                 'given': [{'sku': sku, 'price_vnd': price} for sku, price in want]}
        if not args.get('lines') and len(mine) == 1:
            error.update(expected_price_vnd=mine[0]['final_price_vnd'], given=args['price_vnd'])
        return error
    total = sum(unit['final_price_vnd'] for unit in mine)
    if args['payment'] == 'COD' and total > 10_000_000:
        return {'error': 'cod_limit_exceeded', 'limit_vnd': 10_000_000, 'total_vnd': total}
    order_id = await repo.next_order_id(session)
    codes = sorted({promo['promo_code'] for unit in mine for promo in unit['applied_promos']}
                   | {promo['promo_code'] for promo in quoted['order_promos']})
    stored_args = {**args, 'sku': lines[0]['sku'], 'qty': len(mine), 'lines': lines}
    await repo.insert_order(session, order_id, customer_id, stored_args, mine[0]['final_price_vnd'], total, codes)
    for code in codes:
        await repo.use_promo(session, phone, code)
    return {"order_id": order_id, "status": "created", "total_vnd": total,
            "needs_confirmation_call": args["payment"] == "COD" and total > 2_000_000,
            "estimated_delivery": _delivery(args["on"], args.get("address"))}


async def update(repo, session, args: dict, customer_id: str) -> dict:
    order_id = args["order_id"]
    if not await repo.order_owned(session, order_id, customer_id):
        return {"error": "order_not_owned"}
    current = await status(repo, session, {"order_id": order_id}, customer_id)
    order = current["orders"][0]
    action = args["action"]
    if action in {"exchange_size", "exchange_product"}:
        sku = args.get("new_variant_sku")
        if not sku:
            return {"error": "missing_new_variant_sku"}
        inv = _inventory(await repo.rows(session, "products"), await repo.rows(session, "inventory_events"),
                         sku, args["on"])
        if not inv.get("in_stock"):
            return {"error": "new_variant_out_of_stock", **inv}
        quoted = await _quote(repo, session, {"sku": sku, "on": args["on"],
                                             "customer_phone": order.get("customer_phone")}, customer_id)
        if "error" in quoted:
            return quoted
        fee = 0 if await repo.exchange_count(session, order_id) == 0 else 60_000
        diff = quoted["final_price_vnd"] - order["price_vnd"]
        result = {"order_id": order_id, "action": action, "new_variant_sku": sku,
                  "fee_vnd": fee, "price_diff_vnd": diff, "refund_vnd": max(-diff, 0),
                  "extra_payment_vnd": max(diff, 0), "refund_days": "3-5 ngày làm việc",
                  "status": "pickup_scheduled"}
    elif action == "return":
        result = {"order_id": order_id, "action": action, "reason": args.get("reason"),
                  "refund_vnd": order["price_vnd"], "refund_days": "3-5 ngày làm việc",
                  "status": "pickup_scheduled"}
    elif action == "update_address":
        result = {"order_id": order_id, "action": action, "status": "updated"}
    else:
        return {"error": "unknown_action"}
    await repo.insert_update(session, order_id, action, result)
    return result


async def callback(repo, session, args: dict, phone: str,
                   timezone_name: str = "Asia/Ho_Chi_Minh") -> dict:
    if args.get("customer_phone") != phone:
        return {"error": "identity_required"}
    try:
        moment = datetime.fromisoformat(args["callback_at"])
    except (KeyError, ValueError):
        return {"error": "invalid_callback_at"}
    moved = False
    while moment.date().isoformat() in HOLIDAYS or (moment.weekday() == 6 and not 9 <= moment.hour < 18):
        moment += timedelta(days=1)
        moment = moment.replace(hour=max(moment.hour, 8))
        moved = True
    if not 8 <= moment.hour < 21:
        moment = moment.replace(hour=8, minute=0)
        moved = True
    stored = moment if moment.tzinfo else moment.replace(tzinfo=ZoneInfo(timezone_name))
    number = await repo.insert_callback(session, phone, stored, args.get("note"))
    return {"callback_id": f"CB{number:04d}", "customer_phone": phone,
            "callback_at": moment.isoformat(timespec="minutes"),
            "moved_from": args["callback_at"] if moved else None, "note": args.get("note")}


async def handoff(repo, session, args: dict, customer_id: str | None, phone: str | None) -> dict:
    brief = args.get("brief") or {}
    required = ["customer_phone", "customer_name", "escalation_reason", "conversation_summary",
                "product_advised", "price_quoted_vnd", "open_questions", "next_action", "generated_at"]
    missing = [key for key in required if key not in brief]
    if missing:
        return {"error": "brief_invalid", "missing": missing}
    from pydantic import ValidationError
    from app.schemas.brief import HandoffBrief
    try:
        validated = HandoffBrief.model_validate(brief)
        brief = validated.model_dump(mode="json", exclude_none=True)
        for nullable in ("customer_name", "product_advised", "price_quoted_vnd"):
            brief.setdefault(nullable, None)
    except ValidationError:
        return {"error": "brief_invalid"}
    if customer_id and brief["customer_phone"] != phone:
        return {"error": "customer_not_owned"}
    if not customer_id and (args.get("source_channel") != "hotline" or
                            args.get("source_identity") != brief["customer_phone"]):
        return {"error": "identity_required"}
    number = await repo.insert_handoff(session, brief)
    return {"ticket_id": f"HT{number:04d}", "status": "queued", "brief_ok": True}


async def invoke(repo, name: str, args: dict,
                 timezone_name: str = "Asia/Ho_Chi_Minh") -> dict:
    functions = {"order.create": create, "order.status": status, "order.update": update,
                 "schedule.callback": callback, "handoff.transfer": handoff}
    if name not in functions:
        return {"error": "unknown_tool"}
    key = args.get("operation_key")
    clean = {k: v for k, v in args.items() if k != "operation_key"}
    digest = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    async with repo.transaction() as session:
        customer_id, phone = await _identity(repo, session, args)
        if name != "handoff.transfer" and not customer_id:
            return {"error": "identity_required"}
        if name in {"order.create", "order.update"}:
            await repo.lock_customer(session, phone)
        if key and name != "order.status":
            previous = await repo.claim_operation(session, key, name, digest)
            if previous is not None:
                return previous
        if name == "handoff.transfer":
            result = await handoff(repo, session, args, customer_id, phone)
        elif name == "schedule.callback":
            result = await callback(repo, session, args, phone, timezone_name)
        else:
            result = await functions[name](repo, session, args, customer_id) if name != "order.create" else \
                await create(repo, session, args, customer_id, phone)
        if key and name != "order.status":
            await repo.finish_operation(session, key, result)
        return result
