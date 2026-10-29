"""Derived, customer-scoped recall through LangGraph AsyncPostgresStore."""

import json
from typing import Any

from langgraph.store.postgres.aio import AsyncPostgresStore
from sqlalchemy.engine import make_url

from app.mcp_servers.mcp_shared.pii import mask_pii


def store_dsn(dsn: str) -> str:
    """Force unqualified LangGraph DDL and DML into its dedicated schema."""
    url = make_url(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    query = dict(url.query)
    query["options"] = "-csearch_path=langmem_store"
    return url.set(drivername="postgresql", query=query).render_as_string(
        hide_password=False)


def _safe(value: Any) -> Any:
    return json.loads(mask_pii(json.dumps(value, ensure_ascii=False, default=str)))


def _json_array(value: Any) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, list) else []


class LangMemProjection:
    def __init__(self, dsn: str) -> None:
        self.dsn = store_dsn(dsn)

    @staticmethod
    def namespace(customer_id: str) -> tuple[str, ...]:
        if not customer_id:
            raise ValueError("verified customer ID required")
        return ("customers", customer_id, "episodes")

    async def put_episode(self, customer_id: str, session_id: str,
                          canonical: dict) -> None:
        value = _safe({"schema_version": 1, "session_id": session_id,
            "channel": canonical.get("channel"), "on": canonical.get("on_date"),
            "summary": canonical.get("summary", ""),
            "outcome": canonical.get("outcome", "khac"),
            "status": canonical.get("status", "active"),
            "topics": _json_array(canonical.get("topics", [])),
            "resolved_prior_items": _json_array(canonical.get("resolved_prior_items", []))})
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            await store.aput(self.namespace(customer_id), session_id, value, index=False)

    async def list_episodes(self, customer_id: str, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            items = await store.asearch(self.namespace(customer_id), limit=min(limit, 20))
        return [item.value for item in items if item.namespace == self.namespace(customer_id)
                and isinstance(item.value, dict) and item.value.get("schema_version") == 1]

    async def delete_customer(self, customer_id: str) -> int:
        prefix = ("customers", customer_id)
        if not customer_id:
            raise ValueError("verified customer ID required")
        deleted = 0
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            while True:
                items = await store.asearch(prefix, limit=100)
                if not items:
                    break
                for item in items:
                    if item.namespace[:2] != prefix:
                        continue
                    await store.adelete(item.namespace, item.key)
                    deleted += 1
        return deleted
