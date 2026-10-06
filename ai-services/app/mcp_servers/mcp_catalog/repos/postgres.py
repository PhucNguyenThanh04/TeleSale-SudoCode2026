"""Read-only PostgreSQL queries for customer, products, stock and promotions."""

import json

from sqlalchemy import text
from app.mcp_servers.mcp_shared.database import Database


class CatalogRepo(Database):
    async def rows(self, session, table: str) -> list[dict]:
        if table not in {"products", "inventory_events", "promotions", "customers"}:
            raise ValueError("Unsupported BTC table")
        result = await session.execute(text(f"SELECT data FROM btc_source.{table}"))
        return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in result]

    async def identity_matches(self, session, channel: str | None, identity: str | None) -> list[dict]:
        column = {"hotline": "phone", "chat_fanpage": "fb_id", "zalo_oa": "zalo_id"}.get(channel)
        if not column or not identity:
            return []
        result = await session.execute(text(
            f"SELECT customer_id, phone FROM btc_source.customers WHERE {column}=:identity"
        ), {"identity": identity})
        return [dict(row._mapping) for row in result]

    async def runtime_orders(self, session, customer_id: str) -> list[dict]:
        result = await session.execute(text("""SELECT order_id,sku,qty,price_vnd,total_vnd,
            created_on,status FROM app_runtime.tool_orders WHERE customer_id=:id"""), {"id": customer_id})
        return [dict(row._mapping) for row in result]

    async def used_promos(self, session) -> set[tuple[str, str]]:
        result = await session.execute(text("SELECT customer_phone,promo_code FROM app_runtime.promo_uses"))
        return {(row[0], row[1]) for row in result}
