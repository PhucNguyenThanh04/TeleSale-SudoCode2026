"""Read-only BTC source explorer; no CRM or live quote decisions."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId
from app.database.pg_session import get_pg_session


router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("")
async def reference_data(response: Response, _user_id: CurrentUserId,
                         on: date = Query(...), order_on: date | None = None,
                         db: AsyncSession = Depends(get_pg_session)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    products = await db.execute(text("""SELECT p.sku,p.name,p.category,p.brand,p.list_price_vnd,
        p.attributes,p.stock AS base_stock,
        COALESCE((SELECT e.qty FROM btc_source.inventory_events e WHERE e.sku=p.sku
            AND e.effective_on<=:on ORDER BY e.effective_on DESC LIMIT 1),p.stock) AS stock_on,
        (SELECT max(e.effective_on) FROM btc_source.inventory_events e WHERE e.sku=p.sku
            AND e.effective_on<=:on) AS stock_effective_on
        FROM btc_source.products p ORDER BY p.category,p.name"""), {"on": on})
    variants = await db.execute(text("""SELECT v.variant_sku,v.parent_sku,v.size_label,v.color,
        v.price_delta_vnd,v.stock AS base_stock,
        COALESCE((SELECT e.qty FROM btc_source.inventory_events e WHERE e.sku=v.variant_sku
            AND e.effective_on<=:on ORDER BY e.effective_on DESC LIMIT 1),v.stock) AS stock_on,
        (SELECT max(e.effective_on) FROM btc_source.inventory_events e WHERE e.sku=v.variant_sku
            AND e.effective_on<=:on) AS stock_effective_on
        FROM btc_source.variants v ORDER BY v.parent_sku,v.variant_sku"""), {"on": on})
    promotions = await db.execute(text("""SELECT promo_code,name,promo_type,starts_on,ends_on,
        applies_to,conditions,data FROM btc_source.promotions
        WHERE starts_on<=:on AND ends_on>=:on ORDER BY ends_on,promo_code"""), {"on": on})
    policies = await db.execute(text("""SELECT chunk_id,document_id,title,body,date_basis,
        effective_from,effective_until FROM btc_source.policy_chunks
        WHERE access_level='public' AND date_basis IN ('call_date','order_date')
        AND (date_basis='call_date' OR CAST(:order_on AS date) IS NOT NULL)
        AND (effective_from IS NULL OR effective_from<=
            CASE WHEN date_basis='order_date' THEN CAST(:order_on AS date) ELSE CAST(:on AS date) END)
        AND (effective_until IS NULL OR effective_until>=
            CASE WHEN date_basis='order_date' THEN CAST(:order_on AS date) ELSE CAST(:on AS date) END)
        ORDER BY document_id,chunk_id"""), {"on": on, "order_on": order_on})
    def stock_row(row):
        item = dict(row._mapping)
        item["stock_effective_on"] = item["stock_effective_on"].isoformat() if item["stock_effective_on"] else None
        return item
    return {"on": on.isoformat(), "order_on": order_on.isoformat() if order_on else None,
            "products": [stock_row(row) for row in products],
            "variants": [stock_row(row) for row in variants],
            "promotions": [{**dict(row._mapping), "starts_on": row.starts_on.isoformat(),
                            "ends_on": row.ends_on.isoformat()} for row in promotions],
            "policies": [{**dict(row._mapping),
                           "effective_from": row.effective_from.isoformat() if row.effective_from else None,
                           "effective_until": row.effective_until.isoformat() if row.effective_until else None}
                          for row in policies]}
