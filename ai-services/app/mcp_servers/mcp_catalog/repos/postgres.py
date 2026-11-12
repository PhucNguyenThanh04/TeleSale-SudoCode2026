"""Read-only PostgreSQL queries for customer, products, stock and promotions."""

import json
from datetime import date

from sqlalchemy import text
from app.mcp_servers.mcp_shared.database import Database


class CatalogRepo(Database):
    async def same_day_orders(self, session, phone: str, on: str) -> list[dict]:
        result = await session.execute(text('''SELECT promos FROM runtime.tool_orders
            WHERE customer_phone=:phone AND created_on=:on'''),
            {'phone': phone, 'on': date.fromisoformat(on)})
        return [{'promos': row[0] if isinstance(row[0], list) else json.loads(row[0])} for row in result]

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
        rows = [dict(row._mapping) for row in result]
        if not rows and column != 'phone' and len(identity) == 10 and identity.startswith('0') and identity.isdigit():
            fallback = await session.execute(text(
                'SELECT customer_id,phone FROM btc_source.customers WHERE phone=:identity'
            ), {'identity': identity})
            rows = [dict(row._mapping) for row in fallback]
        return rows

    async def runtime_orders(self, session, customer_id: str) -> list[dict]:
        result = await session.execute(text("""SELECT order_id,sku,qty,price_vnd,total_vnd,lines,
            created_on,status,payment,promos FROM runtime.tool_orders WHERE customer_id=:id"""), {"id": customer_id})
        return [dict(row._mapping) for row in result]

    async def used_promos(self, session) -> set[tuple[str, str]]:
        result = await session.execute(text("SELECT customer_phone,promo_code FROM runtime.promo_uses"))
        return {(row[0], row[1]) for row in result}
