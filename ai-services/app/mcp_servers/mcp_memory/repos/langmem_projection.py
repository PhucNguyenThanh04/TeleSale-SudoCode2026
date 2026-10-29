"""Customer-scoped long-term knowledge in LangGraph AsyncPostgresStore."""

import json
from datetime import date
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


_OPAQUE_FIELDS = {"session_id", "source_turn_id", "source", "scope_id",
                  "sku", "item_id", "resolved_turn_id", "narrative_source_turn_id"}


def _safe(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _safe(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item, field) for item in value]
    if isinstance(value, str):
        return value if field in _OPAQUE_FIELDS else mask_pii(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _json_array(value: Any) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, list) else []


def _revision(value: dict) -> int:
    revision = value.get("revision", -1)
    return revision if type(revision) is int else -1


def select_facts(versions: list[dict], completed: set[int] | None = None) -> list[dict]:
    """Choose the newest visible version of each customer/scope/slot."""
    latest = {}
    for item in versions:
        if not isinstance(item, dict) or item.get("schema_version") != 1:
            continue
        revision = _revision(item)
        if revision > 0 and completed is not None and revision not in completed:
            continue
        identity = (item.get("scope_type", "global"), item.get("scope_id", ""),
                    item.get("key"))
        if not identity[2]:
            continue
        if identity not in latest or revision > _revision(latest[identity]):
            latest[identity] = item
    return [item for item in latest.values() if not item.get("deleted")]


def select_episodes(versions: list[dict], completed: set[int] | None = None) -> list[dict]:
    latest = {}
    for item in versions:
        if not isinstance(item, dict) or item.get("schema_version") != 1:
            continue
        revision = _revision(item)
        if revision > 0 and completed is not None and revision not in completed:
            continue
        session_id = item.get("session_id")
        if session_id and (session_id not in latest
                           or revision > _revision(latest[session_id])):
            latest[session_id] = item
    return sorted(latest.values(), key=lambda item: str(item.get("on", "")),
                  reverse=True)


async def _search_all(store, namespace: tuple[str, ...]) -> list:
    items = []
    while True:
        batch = await store.asearch(namespace, limit=200, offset=len(items))
        items.extend(batch)
        if len(batch) < 200:
            return items


class LangMemProjection:
    def __init__(self, dsn: str) -> None:
        self.dsn = store_dsn(dsn)

    @staticmethod
    def namespace(customer_id: str) -> tuple[str, ...]:
        if not customer_id:
            raise ValueError("verified customer ID required")
        return ("customers", customer_id, "episodes")

    @staticmethod
    def fact_namespace(customer_id: str) -> tuple[str, ...]:
        if not customer_id:
            raise ValueError("verified customer ID required")
        return ("customers", customer_id, "facts")

    async def put_facts(self, customer_id: str, session_id: str,
                        source_turn_id: str, on: str,
                        facts: list[dict], *, revision: int = 0,
                        completed_revisions: set[int] | None = None) -> list[dict]:
        """Append a job version; unfinished writes cannot replace completed data."""
        namespace = self.fact_namespace(customer_id)
        written = []
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            items = await _search_all(store, namespace)
            versions = [item.value for item in items if item.namespace == namespace
                        and isinstance(item.value, dict)]
            for fact in facts:
                scope_type = fact.get("scope_type", "global")
                scope_id = fact.get("scope_id", "")
                key = json.dumps([scope_type, scope_id, fact["key"], revision],
                                 ensure_ascii=False, separators=(",", ":"))
                slot_versions = [item for item in versions
                    if item.get("scope_type", "global") == scope_type
                    and item.get("scope_id", "") == scope_id
                    and item.get("key") == fact["key"]
                    and (completed_revisions is None or _revision(item) <= 0
                         or _revision(item) in completed_revisions
                         or _revision(item) == revision)]
                previous = max(slot_versions, key=_revision) if slot_versions else None
                if previous and _revision(previous) > revision:
                    continue
                if revision < 0 and previous and _revision(previous) == revision:
                    continue
                same = await store.aget(namespace, key)
                same_value = same.value if same else None
                if fact.get("op") == "delete":
                    await store.aput(namespace, key, {"schema_version": 1,
                        "key": fact["key"], "scope_type": scope_type,
                        "scope_id": scope_id, "deleted": True,
                        "revision": revision}, index=False)
                    written.append({"key": fact["key"], "op": "delete",
                                    "customer_id": customer_id,
                                    "scope_type": scope_type, "scope_id": scope_id})
                    continue
                write_op = (same_value.get("write_op", "set")
                    if isinstance(same_value, dict) else
                    "supersede" if previous and not previous.get("deleted") else "set")
                value = _safe({"schema_version": 1, "key": fact["key"],
                    "value": fact["value"], "scope_type": scope_type,
                    "scope_id": scope_id, "source_kind": fact["source_kind"],
                    "source_tool": fact.get("source_tool"),
                    "evidence_quote": fact.get("evidence_quote"),
                    "source_turn_id": source_turn_id, "session_id": session_id,
                    "source": f"langmem:{session_id}:{source_turn_id}", "on": on,
                    "revision": revision, "write_op": write_op})
                await store.aput(namespace, key, value, index=False)
                written.append({"key": fact["key"], "value": fact["value"],
                                "op": write_op, "customer_id": customer_id,
                                "scope_type": scope_type, "scope_id": scope_id,
                                "evidence_quote": fact.get("evidence_quote")})
        return written

    async def list_fact_versions(self, customer_id: str) -> list[dict]:
        namespace = self.fact_namespace(customer_id)
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            items = await _search_all(store, namespace)
        return [item.value for item in items if item.namespace == namespace
                and isinstance(item.value, dict)
                and item.value.get("schema_version") == 1]

    async def list_facts(self, customer_id: str) -> list[dict]:
        return select_facts(await self.list_fact_versions(customer_id))

    async def get_episode(self, customer_id: str, session_id: str) -> dict | None:
        return next((item for item in select_episodes(
            await self.list_episode_versions(customer_id))
            if item.get("session_id") == session_id), None)

    async def put_episode(self, customer_id: str, session_id: str,
                          canonical: dict, *, revision: int = -1) -> None:
        value = _safe({"schema_version": 1, "session_id": session_id,
            "revision": revision,
            "channel": canonical.get("channel"), "on": canonical.get("on_date"),
            "summary": canonical.get("summary", ""),
            "outcome": canonical.get("outcome", "khac"),
            "status": canonical.get("status", "active"),
            "topics": _json_array(canonical.get("topics", [])),
            "resolved_prior_items": _json_array(canonical.get("resolved_prior_items", []))})
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            key = json.dumps([session_id, revision], separators=(",", ":"))
            await store.aput(self.namespace(customer_id), key, value, index=False)

    async def list_episode_versions(self, customer_id: str) -> list[dict]:
        namespace = self.namespace(customer_id)
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            items = await _search_all(store, namespace)
        return [item.value for item in items if item.namespace == namespace
                and isinstance(item.value, dict)
                and item.value.get("schema_version") == 1]

    async def list_episodes(self, customer_id: str, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        return select_episodes(await self.list_episode_versions(customer_id))[:min(limit, 20)]

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
