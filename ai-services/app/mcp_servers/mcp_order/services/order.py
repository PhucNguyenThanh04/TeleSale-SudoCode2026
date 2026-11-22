
import hashlib
import json
from datetime import date, datetime

from app.mcp_servers.mcp_shared.commerce_rules import _delivery, _inventory, _parent, quote_order
from app.mcp_servers.mcp_shared.business_calendar import callback_arguments
from app.mcp_servers.mcp_order.write_authorization import (
    WRITE_TOOLS, normalized_write, verify_write_authorization)
from app.mcp_servers.mcp_shared.identity import resolve_identity, verify_identity


async def _identity(repo, session, args: dict, verified_customer_id=None) -> tuple[str | None, str | None]:
    identity = await resolve_identity(repo, session, args.get('source_channel'),
                                      args.get('source_identity'), verified_customer_id)
    return (identity['customer_id'], identity['phone']) if identity else (None, None)


async def _quote(repo, session, args: dict, customer_id: str | None, qty: int) -> dict:
    products = await repo.rows(session, "products")
    promos = await repo.rows(session, "promotions")
    owned = set()
    args = dict(args)
    if customer_id:
        customers = await repo.rows(session, "customers")
        customer = next((c for c in customers if c["customer_id"] == customer_id), None)
        if customer:
            owned = {o["sku"] for o in customer.get("orders", []) if o.get("status") == "delivered"}
            if customer.get('phone'):
                args['customer_phone'] = customer['phone']
    return quote_order(products, promos, {**args, 'lines': [{'sku': args['sku'], 'qty': qty}]},
                       owned, await repo.used_promos(session))


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
    orders = [dict(order) for order in historical + await repo.runtime_orders(session, customer_id, order_id)]
    for order in orders:
        changes = await repo.order_updates(session, order['order_id'])
        if changes:
            order['updates'] = changes
        for change in changes:
            if change.get('action') == 'update_address' and change.get('address'):
                order['address'] = change['address']
        try:
            order['lines'] = _order_lines(order)
        except (ValueError, TypeError, KeyError):
            order['data_status'] = 'inconsistent'
    return {"orders": orders}


def _order_lines(order):
    lines = order.get('lines')
    if isinstance(lines, str):
        lines = json.loads(lines)
    if lines is None:
        lines = [{'sku': order['sku'], 'qty': order.get('qty', 1), 'price_vnd': order['price_vnd']}]
    if (not isinstance(lines, list) or not lines or any(not isinstance(line, dict)
            or not isinstance(line.get('sku'), str) or not line['sku']
            or type(line.get('qty', 1)) is not int or line.get('qty', 1) < 1
            or type(line.get('price_vnd')) is not int or line['price_vnd'] < 0 for line in lines)):
        raise ValueError('Invalid stored order lines')
    total = sum(line.get('qty', 1) * line['price_vnd'] for line in lines)
    if order.get('total_vnd') is not None and (type(order['total_vnd']) is not int or order['total_vnd'] != total):
        raise ValueError('Inconsistent stored total')
    return [{'line_index': i, 'sku': line['sku'], 'qty': line.get('qty', 1), 'price_vnd': line['price_vnd']}
            for i, line in enumerate(lines)]


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


def _order_date(order, *fields):
    for field in fields:
        value = order.get(field)
        if isinstance(value, (str, date)):
            try:
                return date.fromisoformat(str(value)[:10])
            except ValueError:
                pass
    return None


def _return_eligibility(order, lines, products, on):
    created = _order_date(order, 'created_on', 'created_at', 'date')
    received = _order_date(order, 'received_on', 'delivered_on', 'received_at', 'delivered_at')
    today = date.fromisoformat(on)
    old = created is not None and created < date(2026, 10, 1)
    conditions = order.get('return_conditions')
    conditions = conditions if isinstance(conditions, dict) else {}
    missing = []
    if created is None:
        missing.append('order_date')
    if received is None:
        missing.append('received_on')
    if created and created > today or received and (received > today or created and received < created):
        missing.append('consistent_order_dates')
    if order.get('status') != 'delivered':
        missing.append('delivered_status')
    selected = [_parent(products, line['sku'])[0] for line in lines]
    if any(product is None for product in selected):
        missing.append('product')
    result = {'policy_version': '2026-06' if old else '2026-10' if created else 'unverified'}
    for field, error in (('customer_damage', 'return_customer_damage'),
                          ('clearance_no_return', 'return_clearance_excluded')):
        if conditions.get(field) is True:
            return {**result, 'status': 'ineligible', 'error': error, 'missing_fields': []}
        if conditions.get(field) is not False:
            missing.append(field)
    defect = conditions.get('manufacturer_defect_confirmed')
    extended = old or all(product and product.get('category', '').split('/')[0] in {'gia-dung', 'me-be'}
                          for product in selected)
    days = 14 if old else 7
    maximum = 15 if old else 30
    if received and 'consistent_order_dates' not in missing:
        elapsed = (today - received).days
        if elapsed > days:
            if elapsed > maximum or created and (not extended and 'product' not in missing or defect is False):
                return {**result, 'status': 'ineligible', 'error': 'return_window_expired', 'missing_fields': []}
            if defect is not True:
                missing.append('manufacturer_defect_confirmed')
    for field in ('tags_intact', 'packaging_intact', 'unused'):
        if field == 'unused' and defect is True:
            continue
        if conditions.get(field) is False:
            return {**result, 'status': 'ineligible', 'error': 'return_condition_not_met', 'missing_fields': []}
        if conditions.get(field) is not True:
            missing.append(field)
    hygiene = any(product and (product['sku'] == 'SKU-MB-BOT'
        or product.get('attributes', {}).get('hygiene_sensitive') is True) for product in selected)
    if hygiene:
        if conditions.get('seal_intact') is False:
            return {**result, 'status': 'ineligible', 'error': 'return_hygiene_excluded', 'missing_fields': []}
        if conditions.get('seal_intact') is not True:
            missing.append('seal_intact')
    return {**result, 'status': 'pending' if missing else 'eligible', 'missing_fields': missing}


async def _update_plan(repo, session, args: dict, customer_id: str) -> dict:
    order_id = args["order_id"]
    if not await repo.order_owned(session, order_id, customer_id):
        return {"error": "order_not_owned"}
    current = await status(repo, session, {"order_id": order_id}, customer_id)
    if not current['orders']:
        return {'error': 'order_not_found'}
    order = current["orders"][0]
    action = args["action"]
    if action == 'update_address':
        address = args.get('address')
        if not isinstance(address, str) or not address.strip():
            return {'error': 'address_required'}
        result = {'order_id': order_id, 'action': action, 'address': address.strip(), 'status': 'updated'}
        return result
    if action not in {'return', 'exchange_size', 'exchange_product'}:
        return {'error': 'unknown_action'}
    try:
        lines = _order_lines(order)
    except (ValueError, TypeError, KeyError):
        return {'error': 'order_data_inconsistent'}
    index, quantity = args.get('line_index'), args.get('qty')
    if index is None and (action != 'return' or quantity is not None):
        if len(lines) != 1:
            return {'error': 'order_line_required'}
        index = 0
    if index is not None and (type(index) is not int or not 0 <= index < len(lines)):
        return {'error': 'invalid_order_line'}
    selected = [dict(lines[index])] if index is not None else [dict(line) for line in lines]
    if quantity is not None:
        if type(quantity) is not int or not 1 <= quantity <= selected[0]['qty']:
            return {'error': 'invalid_update_quantity'}
        selected[0]['qty'] = quantity
    paid = sum(line['qty'] * line['price_vnd'] for line in selected)
    products = await repo.rows(session, 'products')
    eligibility = _return_eligibility(order, selected, products, args['on'])
    if eligibility['status'] == 'ineligible':
        return {'error': eligibility['error'], 'eligibility': eligibility}
    old_policy = eligibility['policy_version'] == '2026-06'
    policy_known = eligibility['policy_version'] != 'unverified'
    refund_days = ('7 ngày làm việc' if old_policy else '3-5 ngày làm việc') if policy_known else None
    if action in {"exchange_size", "exchange_product"}:
        sku = args.get("new_variant_sku")
        if not sku:
            return {"error": "missing_new_variant_sku"}
        product, variant = _parent(products, sku)
        if product and product.get('variants') and variant is None:
            return {'error': 'variant_selection_required'}
        inv = _inventory(products, await repo.rows(session, "inventory_events"),
                         sku, args["on"])
        quantity = selected[0]['qty']
        if not inv.get("in_stock") or inv.get('qty', 0) < quantity:
            return {"error": "new_variant_out_of_stock", **inv}
        quoted = await _quote(repo, session, {"sku": sku, "on": args["on"],
                                             "customer_phone": order.get("customer_phone")}, customer_id, quantity)
        if "error" in quoted:
            return quoted
        fee = 20_000 if old_policy else 0 if await repo.exchange_count(session, order_id) == 0 else 60_000
        if not policy_known:
            fee = None
        diff = quoted['total_vnd'] - paid
        result = {"order_id": order_id, "action": action, "new_variant_sku": sku,
                  "fee_vnd": fee, "price_diff_vnd": diff, "refund_vnd": max(-diff, 0),
                  "extra_payment_vnd": max(diff, 0), "refund_days": refund_days,
                  "status": "pickup_scheduled"}
        result['replacement_lines'] = quoted['lines']
        result['replacement_inventory'] = {'sku': sku, 'on': args['on'], **inv}
    elif action == "return":
        result = {"order_id": order_id, "action": action, "reason": args.get("reason"),
                  "refund_vnd": paid, "refund_days": refund_days,
                  "status": "pickup_scheduled"}
    result['selected_lines'] = selected
    result['eligibility'] = eligibility
    if eligibility['status'] == 'pending':
        result.update(status='review_pending', estimate=True, requires_policy_check=True)
    return result


async def preview_update(repo, session, args: dict, customer_id: str) -> dict:
    result = await _update_plan(repo, session, args, customer_id)
    if 'error' in result:
        return result
    fee = result.get('fee_vnd', 0)
    settlement = result.get('extra_payment_vnd', 0) + fee - result['refund_vnd'] if fee is not None else None
    return {**result, 'status': 'preview', 'estimate': True, 'on': args['on'],
            'requires_policy_check': result['eligibility']['status'] != 'eligible',
            'estimated_total_payment_vnd': max(settlement, 0) if settlement is not None else None,
            'estimated_total_refund_vnd': max(-settlement, 0) if settlement is not None else None}


async def update(repo, session, args: dict, customer_id: str) -> dict:
    result = await _update_plan(repo, session, args, customer_id)
    if 'error' not in result:
        result.pop('replacement_inventory', None)
        await repo.insert_update(session, args['order_id'], args['action'], result)
    return result


async def callback(repo, session, args: dict, phone: str,
                   timezone_name: str = "Asia/Ho_Chi_Minh") -> dict:
    if args.get("customer_phone") != phone:
        return {"error": "identity_required"}
    try:
        payload = callback_arguments(args, naive_timezone=timezone_name)
        moment = datetime.fromisoformat(payload['callback_at'])
    except (KeyError, ValueError):
        return {"error": "invalid_callback_at"}
    number = await repo.insert_callback(session, phone, moment, args.get("note"))
    return {"callback_id": f"CB{number:04d}", "customer_phone": phone,
            'status': 'scheduled',
            "callback_at": moment.isoformat(timespec="minutes"),
            "moved_from": payload.get('requested_callback_at'), "note": args.get("note")}


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
                 timezone_name: str = "Asia/Ho_Chi_Minh", *,
                 context_secret: str | None = None) -> dict:
    functions = {"order.create": create, "order.status": status, "order.update": update,
                 'order.preview_update': preview_update,
                 "schedule.callback": callback, "handoff.transfer": handoff}
    if name not in functions:
        return {"error": "unknown_tool"}
    context = None
    verified_customer_id = None
    if name in WRITE_TOOLS:
        try:
            context = verify_write_authorization(name, args, context_secret)
            verified_customer_id = context.customer_id
            args = normalized_write(name, args)
        except PermissionError:
            return {'error': 'write_authorization_required'}
    elif name in {'order.status', 'order.preview_update'} and args.get('trusted_identity'):
        try:
            verified_customer_id = verify_identity(name, args, context_secret)
        except PermissionError:
            return {'error': 'identity_required'}
    key = args.get("operation_key")
    clean = {k: v for k, v in args.items() if k != "operation_key"}
    digest = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    async with repo.transaction() as session:
        customer_id, phone = await _identity(repo, session, args, verified_customer_id)
        if verified_customer_id is not None and customer_id != verified_customer_id:
            return {'error': 'identity_changed'}
        if context is not None and context.customer_id != customer_id:
            return {'error': 'identity_changed'}
        if name != "handoff.transfer" and not customer_id:
            return {"error": "identity_required"}
        if name in {"order.create", "order.update"}:
            await repo.lock_customer(session, phone)
        if key and name in WRITE_TOOLS:
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
        if key and name in WRITE_TOOLS:
            await repo.finish_operation(session, key, result)
        return result
