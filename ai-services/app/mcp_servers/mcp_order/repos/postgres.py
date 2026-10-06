"""Order PostgreSQL queries; no commerce decisions live here."""

import json
from datetime import date, datetime

from sqlalchemy import text
from app.mcp_servers.mcp_shared.database import Database


class OrderRepo(Database):
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
            f"SELECT customer_id,phone FROM btc_source.customers WHERE {column}=:identity"
        ), {"identity": identity})
        return [dict(row._mapping) for row in result]

    async def phone_owned(self, session, phone: str, customer_id: str) -> bool:
        result = await session.execute(text("""SELECT 1 FROM btc_source.customers
            WHERE phone=:phone AND customer_id=:customer_id"""),
            {"phone": phone, "customer_id": customer_id})
        return result.first() is not None

    async def order_owned(self, session, order_id: str, customer_id: str) -> bool:
        result = await session.execute(text("""SELECT customer_id FROM btc_source.crm_orders WHERE order_id=:id
            UNION ALL SELECT customer_id FROM app_runtime.tool_orders WHERE order_id=:id"""), {"id": order_id})
        return any(row[0] == customer_id for row in result)

    async def runtime_orders(self, session, customer_id: str, order_id: str | None) -> list[dict]:
        result = await session.execute(text("""SELECT order_id,customer_phone,sku,qty,price_vnd,total_vnd,
            created_on,status FROM app_runtime.tool_orders WHERE customer_id=:customer_id
            AND (CAST(:order_id AS text) IS NULL OR order_id=CAST(:order_id AS text))"""),
            {"customer_id": customer_id, "order_id": order_id})
        return [dict(row._mapping) for row in result]

    async def used_promos(self, session) -> set[tuple[str, str]]:
        result = await session.execute(text("SELECT customer_phone,promo_code FROM app_runtime.promo_uses"))
        return {(row[0], row[1]) for row in result}

    async def next_order_id(self, session) -> str:
        result = await session.execute(text("SELECT nextval('app_runtime.tool_order_seq')"))
        return f"OD{result.scalar_one()}"

    async def insert_order(self, session, order_id: str, customer_id: str, args: dict,
                           price: int, total: int, codes: list[str]) -> None:
        await session.execute(text("""INSERT INTO app_runtime.tool_orders
            (order_id,customer_id,customer_phone,sku,qty,price_vnd,total_vnd,payment,address,promos,created_on)
            VALUES (:order_id,:customer_id,:phone,:sku,:qty,:price,:total,:payment,:address,CAST(:promos AS jsonb),:on)"""),
            {"order_id": order_id, "customer_id": customer_id, "phone": args["customer_phone"],
             "sku": args["sku"], "qty": args["qty"], "price": price, "total": total,
             "payment": args["payment"], "address": args.get("address"),
             "promos": json.dumps(codes), "on": date.fromisoformat(args["on"])})

    async def use_promo(self, session, phone: str, code: str) -> None:
        await session.execute(text("""INSERT INTO app_runtime.promo_uses(customer_phone,promo_code)
            VALUES (:phone,:code) ON CONFLICT DO NOTHING"""), {"phone": phone, "code": code})

    async def exchange_count(self, session, order_id: str) -> int:
        result = await session.execute(text("""SELECT count(*) FROM app_runtime.tool_updates
            WHERE order_id=:id AND action LIKE 'exchange%'"""), {"id": order_id})
        return result.scalar_one()

    async def insert_update(self, session, order_id: str, action: str, result: dict) -> None:
        await session.execute(text("""INSERT INTO app_runtime.tool_updates(order_id,action,result)
            VALUES (:id,:action,CAST(:result AS jsonb))"""),
            {"id": order_id, "action": action, "result": json.dumps(result)})

    async def insert_callback(self, session, phone: str, moment: datetime, note: str | None) -> int:
        result = await session.execute(text("""INSERT INTO app_runtime.tool_callbacks(customer_phone,callback_at,note)
            VALUES (:phone,:moment,:note) RETURNING callback_id"""),
            {"phone": phone, "moment": moment, "note": note})
        return result.scalar_one()

    async def insert_handoff(self, session, brief: dict) -> int:
        result = await session.execute(text("""INSERT INTO app_runtime.tool_handoffs(brief)
            VALUES (CAST(:brief AS jsonb)) RETURNING ticket_id"""),
            {"brief": json.dumps(brief, ensure_ascii=False)})
        return result.scalar_one()

    async def claim_operation(self, session, key: str, name: str, args_hash: str) -> dict | None:
        await session.execute(text("""INSERT INTO app_runtime.tool_operations(operation_key,tool_name,args_hash)
            VALUES (:key,:name,:hash) ON CONFLICT DO NOTHING"""),
            {"key": key, "name": name, "hash": args_hash})
        row = await session.execute(text("""SELECT tool_name,args_hash,result FROM app_runtime.tool_operations
            WHERE operation_key=:key FOR UPDATE"""), {"key": key})
        value = row.one()
        if value.tool_name != name or value.args_hash != args_hash:
            return {"error": "operation_key_conflict"}
        return json.loads(value.result) if isinstance(value.result, str) else value.result

    async def finish_operation(self, session, key: str, result: dict) -> None:
        await session.execute(text("""UPDATE app_runtime.tool_operations SET result=CAST(:result AS jsonb)
            WHERE operation_key=:key"""), {"key": key, "result": json.dumps(result, ensure_ascii=False, default=str)})
