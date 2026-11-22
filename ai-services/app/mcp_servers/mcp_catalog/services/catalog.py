from app.mcp_servers.mcp_shared.commerce_rules import _catalog, _inventory, _delivery, _parent, quote, quote_order
from app.mcp_servers.mcp_shared.identity import resolve_identity
from app.mcp_servers.mcp_shared.catalog_evidence import enrich_products, product_details


async def get_customer(repo, session, args: dict) -> dict:
    keys = {key: args.get(key) for key in ("phone", "zalo_id", "fb_id") if args.get(key)}
    if not keys:
        return {"error": "missing_identity"}
    customers = await repo.rows(session, "customers")
    hits = [customer for customer in customers
            if any(customer.get(key) == value for key, value in keys.items())]
    if not hits:
        return {"found": False}
    if len(hits) > 1:
        return {"found": True, "ambiguous": True, "candidates": [
            {"customer_id": customer["customer_id"], "name": customer["name"],
             "honorific": customer.get("honorific"), "sessions": customer.get("sessions", []),
             "orders": customer.get("orders", [])} for customer in hits]}
    customer = hits[0]
    orders = list(customer.get("orders", [])) + await repo.runtime_orders(session, customer["customer_id"])
    return {"found": True, "ambiguous": False, "customer_id": customer["customer_id"],
            "name": customer["name"], "honorific": customer.get("honorific"),
            "phone": customer["phone"],
            "identities": {"zalo_id": customer.get("zalo_id"), "fb_id": customer.get("fb_id")},
            "orders": orders, "sessions": customer.get("sessions", [])}


async def search(repo, session, args: dict) -> dict:
    products = enrich_products(await repo.rows(session, 'products'), await repo.rows(session, 'policy_chunks'))
    return _catalog(products, args)


async def get_details(repo, session, args: dict) -> dict:
    product, variant = _parent(await repo.rows(session, 'products'), args['sku'])
    if product is None:
        return {'error': 'unknown_sku'}
    item = product_details(product, await repo.rows(session, 'policy_chunks'), args['sku'], selected_variant=variant)
    return {'requested_sku': args['sku'], 'items': [item], 'total': 1}


async def inventory(repo, session, args: dict) -> dict:
    products = await repo.rows(session, "products")
    events = await repo.rows(session, "inventory_events")
    return _inventory(products, events, args["sku"], args["on"])


async def _pricing_context(repo, session, args: dict, verified_customer_id=None):
    payload = dict(args)
    identity = await resolve_identity(repo, session, args.get('source_channel'),
                                      args.get('source_identity'), verified_customer_id)
    if verified_customer_id is not None and identity is None:
        raise PermissionError('Verified identity no longer matches')
    if identity is None or payload.get("customer_phone") != identity["phone"]:
        payload.pop("customer_phone", None)
    owned = set()
    if payload.get("customer_phone"):
        customers = await repo.rows(session, "customers")
        customer = next((c for c in customers if c["customer_id"] == identity["customer_id"]), None)
        if customer:
            owned = {o["sku"] for o in customer.get("orders", []) if o.get("status") == "delivered"}
    return payload, owned


async def get_quote_order(repo, session, args: dict, *, verified_customer_id=None) -> dict:
    payload, owned = await _pricing_context(repo, session, args, verified_customer_id)
    same_day = (await repo.same_day_orders(session, payload['customer_phone'], payload['on'])
                if payload.get('customer_phone') else [])
    promotions = await repo.rows(session, 'promotions')
    result = quote_order(await repo.rows(session, 'products'), promotions,
                       payload, owned, await repo.used_promos(session),
                       used_today={code for order in same_day for code in order['promos']})
    _promotion_validity(result, promotions)
    return result


def _promotion_validity(result, promotions):
    ends = {promo['promo_code']: promo.get('end') for promo in promotions}
    applied = [*result.get('applied_promos', []), *result.get('order_promos', []),
               *(promo for unit in result.get('units', []) for promo in unit.get('applied_promos', []))]
    for promo in applied:
        until = ends.get(promo.get('promo_code'))
        if until:
            promo['valid_until'] = str(until)


async def get_quote(repo, session, args: dict, *, verified_customer_id=None) -> dict:
    payload, owned = await _pricing_context(repo, session, args, verified_customer_id)
    promotions = await repo.rows(session, "promotions")
    products = await repo.rows(session, "products")
    result = quote(products, promotions,
                   payload, owned, await repo.used_promos(session))
    if "error" not in result:
        stock = _inventory(products, await repo.rows(session, "inventory_events"), args["sku"], args["on"])
        if stock.get("in_stock") and stock.get("qty", 0) >= args.get("qty", 1):
            result["estimated_delivery"] = _delivery(args["on"], args.get("address"))
        _promotion_validity(result, promotions)
    return result
