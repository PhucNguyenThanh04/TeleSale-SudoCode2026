"""Catalog business rules independent of FastMCP and SQL transport."""

from app.mcp_servers.mcp_shared.commerce_rules import _catalog, _inventory, quote


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
    return _catalog(await repo.rows(session, "products"), args)


async def inventory(repo, session, args: dict) -> dict:
    products = await repo.rows(session, "products")
    events = await repo.rows(session, "inventory_events")
    return _inventory(products, events, args["sku"], args["on"])


async def get_quote(repo, session, args: dict) -> dict:
    payload = dict(args)
    matches = await repo.identity_matches(session, args.get("source_channel"), args.get("source_identity"))
    if len(matches) != 1 or payload.get("customer_phone") != matches[0]["phone"]:
        payload.pop("customer_phone", None)
    owned = set()
    if payload.get("customer_phone"):
        customers = await repo.rows(session, "customers")
        customer = next((c for c in customers if c["customer_id"] == matches[0]["customer_id"]), None)
        if customer:
            owned = {o["sku"] for o in customer.get("orders", []) if o.get("status") == "delivered"}
    return quote(await repo.rows(session, "products"), await repo.rows(session, "promotions"),
                 payload, owned, await repo.used_promos(session))
