"""Idempotent import into a dedicated PostgreSQL source schema."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .source import PolicyChunk, json_digest

DDL = """
CREATE SCHEMA IF NOT EXISTS btc_source;
CREATE TABLE IF NOT EXISTS btc_source.products (
    sku text PRIMARY KEY, name text NOT NULL, category text NOT NULL,
    brand text NOT NULL, list_price_vnd bigint NOT NULL, stock integer NOT NULL,
    attributes jsonb NOT NULL, data jsonb NOT NULL, source_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS btc_source.variants (
    variant_sku text PRIMARY KEY, parent_sku text NOT NULL REFERENCES btc_source.products(sku),
    size_label text, color text, price_delta_vnd bigint NOT NULL,
    stock integer NOT NULL, data jsonb NOT NULL, source_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS btc_source.promotions (
    promo_code text PRIMARY KEY, name text NOT NULL, promo_type text NOT NULL,
    starts_on date NOT NULL, ends_on date NOT NULL, applies_to jsonb NOT NULL,
    conditions jsonb NOT NULL, data jsonb NOT NULL, source_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS btc_source.inventory_events (
    sku text NOT NULL, effective_on date NOT NULL, qty integer NOT NULL,
    note text, data jsonb NOT NULL, source_hash text NOT NULL,
    PRIMARY KEY (sku, effective_on)
);
CREATE TABLE IF NOT EXISTS btc_source.customers (
    customer_id text PRIMARY KEY, name text NOT NULL, honorific text,
    phone text NOT NULL, zalo_id text, fb_id text, region text,
    shared_phone_with text, data jsonb NOT NULL, source_hash text NOT NULL
);
CREATE INDEX IF NOT EXISTS customers_phone_idx ON btc_source.customers(phone);
CREATE INDEX IF NOT EXISTS customers_zalo_idx ON btc_source.customers(zalo_id);
CREATE INDEX IF NOT EXISTS customers_fb_idx ON btc_source.customers(fb_id);
CREATE TABLE IF NOT EXISTS btc_source.crm_orders (
    order_id text PRIMARY KEY, customer_id text NOT NULL REFERENCES btc_source.customers(customer_id),
    sku text NOT NULL, order_date date, status text NOT NULL,
    data jsonb NOT NULL, source_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS btc_source.crm_sessions (
    session_id text PRIMARY KEY, customer_id text NOT NULL REFERENCES btc_source.customers(customer_id),
    session_date date NOT NULL, channel text NOT NULL, outcome text,
    data jsonb NOT NULL, source_hash text NOT NULL
);
CREATE TABLE IF NOT EXISTS btc_source.policy_documents (
    document_id text PRIMARY KEY, access_level text NOT NULL,
    effective_from date, effective_until date, date_basis text NOT NULL
);
CREATE TABLE IF NOT EXISTS btc_source.policy_chunks (
    chunk_id text PRIMARY KEY, document_id text NOT NULL REFERENCES btc_source.policy_documents(document_id),
    title text NOT NULL, body text NOT NULL, access_level text NOT NULL,
    effective_from date, effective_until date, date_basis text NOT NULL,
    source_hash text NOT NULL
);
"""


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _asyncpg_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + database_url.split("://", 1)[1]
    return database_url


async def inspect_database(database_url: str) -> dict[str, Any]:
    """Return the actual target database and table counts, without credentials."""
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("Install dataloader_offline/requirements-postgres.txt first") from exc
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        row = await connection.fetchrow(
            "SELECT current_database() AS database, current_user AS username, "
            "inet_server_addr()::text AS server_address, inet_server_port() AS server_port, "
            "to_regclass('btc_source.products') IS NOT NULL AS tables_exist"
        )
        result = dict(row)
        if result["tables_exist"]:
            result["counts"] = {
                table: await connection.fetchval(f"SELECT count(*) FROM btc_source.{table}")
                for table in (
                    "products", "variants", "promotions", "inventory_events",
                    "customers", "crm_orders", "crm_sessions", "policy_documents", "policy_chunks",
                )
            }
        return result
    finally:
        await connection.close()


async def import_release(database_url: str, release: dict[str, Any]) -> dict[str, int]:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("Install dataloader_offline/requirements.txt to import into PostgreSQL") from exc

    # backend/.env uses SQLAlchemy's dialect name; asyncpg expects postgresql://.
    connection = await asyncpg.connect(_asyncpg_url(database_url), timeout=10)
    try:
        async with connection.transaction():
            await connection.execute(DDL)
            products = release["products"]["products"]
            for item in products:
                await connection.execute(
                    """INSERT INTO btc_source.products VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9)
                    ON CONFLICT (sku) DO UPDATE SET name=EXCLUDED.name, category=EXCLUDED.category,
                    brand=EXCLUDED.brand, list_price_vnd=EXCLUDED.list_price_vnd, stock=EXCLUDED.stock,
                    attributes=EXCLUDED.attributes, data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                    item["sku"], item["name"], item["category"], item["brand"],
                    item["list_price_vnd"], item["stock"], json.dumps(item["attributes"], ensure_ascii=False),
                    json.dumps(item, ensure_ascii=False), json_digest(item),
                )
                for variant in item.get("variants", []):
                    await connection.execute(
                        """INSERT INTO btc_source.variants VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8)
                        ON CONFLICT (variant_sku) DO UPDATE SET parent_sku=EXCLUDED.parent_sku,
                        size_label=EXCLUDED.size_label, color=EXCLUDED.color,
                        price_delta_vnd=EXCLUDED.price_delta_vnd, stock=EXCLUDED.stock,
                        data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                        variant["variant_sku"], item["sku"], str(variant.get("size")) if variant.get("size") is not None else None,
                        variant.get("color"), variant["price_delta_vnd"], variant["stock"],
                        json.dumps(variant, ensure_ascii=False), json_digest(variant),
                    )
            for promo in release["promotions"]["promotions"]:
                await connection.execute(
                    """INSERT INTO btc_source.promotions VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9)
                    ON CONFLICT (promo_code) DO UPDATE SET name=EXCLUDED.name, promo_type=EXCLUDED.promo_type,
                    starts_on=EXCLUDED.starts_on, ends_on=EXCLUDED.ends_on,
                    applies_to=EXCLUDED.applies_to, conditions=EXCLUDED.conditions,
                    data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                    promo["promo_code"], promo["name"], promo["type"], _date(promo["start"]), _date(promo["end"]),
                    json.dumps(promo["applies_to"], ensure_ascii=False),
                    json.dumps(promo.get("conditions", {}), ensure_ascii=False),
                    json.dumps(promo, ensure_ascii=False), json_digest(promo),
                )
            for event in release["inventory"]["events"]:
                await connection.execute(
                    """INSERT INTO btc_source.inventory_events VALUES($1,$2,$3,$4,$5::jsonb,$6)
                    ON CONFLICT (sku,effective_on) DO UPDATE SET qty=EXCLUDED.qty, note=EXCLUDED.note,
                    data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                    event["sku"], _date(event["date"]), event["qty"], event.get("note"),
                    json.dumps(event, ensure_ascii=False), json_digest(event),
                )
            customers = release["crm"]["customers"]
            for customer in customers:
                await connection.execute(
                    """INSERT INTO btc_source.customers VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)
                    ON CONFLICT (customer_id) DO UPDATE SET name=EXCLUDED.name,
                    honorific=EXCLUDED.honorific, phone=EXCLUDED.phone, zalo_id=EXCLUDED.zalo_id,
                    fb_id=EXCLUDED.fb_id, region=EXCLUDED.region,
                    shared_phone_with=EXCLUDED.shared_phone_with,
                    data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                    customer["customer_id"], customer["name"], customer.get("honorific"), customer["phone"],
                    customer.get("zalo_id"), customer.get("fb_id"), customer.get("region"),
                    customer.get("shared_phone_with"), json.dumps(customer, ensure_ascii=False), json_digest(customer),
                )
                for order in customer.get("orders", []):
                    await connection.execute(
                        """INSERT INTO btc_source.crm_orders VALUES($1,$2,$3,$4,$5,$6::jsonb,$7)
                        ON CONFLICT (order_id) DO UPDATE SET customer_id=EXCLUDED.customer_id,
                        sku=EXCLUDED.sku, order_date=EXCLUDED.order_date, status=EXCLUDED.status,
                        data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                        order["order_id"], customer["customer_id"], order["sku"], _date(order.get("date")),
                        order["status"], json.dumps(order, ensure_ascii=False), json_digest(order),
                    )
                for session in customer.get("sessions", []):
                    await connection.execute(
                        """INSERT INTO btc_source.crm_sessions VALUES($1,$2,$3,$4,$5,$6::jsonb,$7)
                        ON CONFLICT (session_id) DO UPDATE SET customer_id=EXCLUDED.customer_id,
                        session_date=EXCLUDED.session_date, channel=EXCLUDED.channel,
                        outcome=EXCLUDED.outcome, data=EXCLUDED.data, source_hash=EXCLUDED.source_hash""",
                        session["session_id"], customer["customer_id"], _date(session["date"]),
                        session["channel"], session.get("outcome"),
                        json.dumps(session, ensure_ascii=False), json_digest(session),
                    )
            chunks: list[PolicyChunk] = release["chunks"]
            for chunk in chunks:
                await connection.execute(
                    """INSERT INTO btc_source.policy_documents VALUES($1,$2,$3,$4,$5)
                    ON CONFLICT (document_id) DO UPDATE SET access_level=EXCLUDED.access_level,
                    effective_from=EXCLUDED.effective_from, effective_until=EXCLUDED.effective_until,
                    date_basis=EXCLUDED.date_basis""",
                    chunk.document_id, chunk.access_level, _date(chunk.effective_from),
                    _date(chunk.effective_until), chunk.date_basis,
                )
                await connection.execute(
                    """INSERT INTO btc_source.policy_chunks VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (chunk_id) DO UPDATE SET document_id=EXCLUDED.document_id,
                    title=EXCLUDED.title, body=EXCLUDED.body, access_level=EXCLUDED.access_level,
                    effective_from=EXCLUDED.effective_from, effective_until=EXCLUDED.effective_until,
                    date_basis=EXCLUDED.date_basis, source_hash=EXCLUDED.source_hash""",
                    chunk.chunk_id, chunk.document_id, chunk.title, chunk.body, chunk.access_level,
                    _date(chunk.effective_from), _date(chunk.effective_until), chunk.date_basis, chunk.content_hash,
                )
    finally:
        await connection.close()
    return {
        "products": len(products), "variants": sum(len(p.get("variants", [])) for p in products),
        "promotions": len(release["promotions"]["promotions"]),
        "inventory_events": len(release["inventory"]["events"]),
        "customers": len(customers), "policy_chunks": len(chunks),
    }
