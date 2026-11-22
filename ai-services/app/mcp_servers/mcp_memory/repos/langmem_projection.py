
import json
from datetime import date
from typing import Any

from langgraph.store.postgres.aio import AsyncPostgresStore
from sqlalchemy.engine import make_url

from app.mcp_servers.mcp_shared.pii import mask_pii


def store_dsn(dsn: str) -> str:
    url = make_url(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    query = dict(url.query)
    query["options"] = "-csearch_path=runtime"
    return url.set(drivername="postgresql", query=query).render_as_string(
        hide_password=False)


_OPAQUE_FIELDS = {"session_id", "source_turn_id", "source", "scope_id",
                  "sku", "item_id", "resolved_turn_id", "narrative_source_turn_id"}


def _safe(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _safe(item, key) for key, item in value.items()
                if key not in {'consultation', 'offer_candidates', 'basket_offers'}}
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
                                    'source_kind': fact['source_kind'],
                                    "customer_id": customer_id,
                                    "scope_type": scope_type, "scope_id": scope_id})
                    continue
                write_op = (same_value.get("write_op", "set")
                    if isinstance(same_value, dict) else
                    "supersede" if previous and not previous.get("deleted") else "set")
                raw_record = {"schema_version": 1, "key": fact["key"],
                    "value": fact["value"], "scope_type": scope_type,
                    "scope_id": scope_id, "source_kind": fact["source_kind"],
                    "source_tool": fact.get("source_tool"),
                    "evidence_quote": fact.get("evidence_quote"),
                    "source_turn_id": source_turn_id, "session_id": session_id,
                    "source": f"langmem:{session_id}:{source_turn_id}", "on": on,
                    "revision": revision, "write_op": write_op}
                if fact.get("valid_until"):
                    raw_record["valid_until"] = fact["valid_until"]
                value = _safe(raw_record)
                await store.aput(namespace, key, value, index=False)
                entry = {"key": fact["key"], "value": fact["value"],
                         'source_kind': fact['source_kind'],
                         "op": write_op, "customer_id": customer_id,
                         "scope_type": scope_type, "scope_id": scope_id,
                         "evidence_quote": fact.get("evidence_quote")}
                if fact.get("valid_until"):
                    entry["valid_until"] = fact["valid_until"]
                written.append(entry)
        return written

    async def discard_fact_revision(self, customer_id: str, revision: int) -> int:
        if type(revision) is not int or revision < 1:
            raise ValueError('A positive job revision is required')
        namespace = self.fact_namespace(customer_id)
        deleted = 0
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            for item in await _search_all(store, namespace):
                if (item.namespace == namespace and isinstance(item.value, dict)
                        and _revision(item.value) == revision):
                    await store.adelete(namespace, item.key)
                    deleted += 1
        return deleted

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
        record = {"schema_version": 1, "session_id": session_id,
            "revision": revision,
            "channel": canonical.get("channel"), "on": canonical.get("on_date"),
            "summary": canonical.get("summary", ""),
            "outcome": canonical.get("outcome", "khac"),
            "status": canonical.get("status", "active"),
            "topics": _json_array(canonical.get("topics", [])),
            "resolved_prior_items": _json_array(canonical.get("resolved_prior_items", []))}
        if canonical.get("actions_completed"):
            record["actions_completed"] = _json_array(canonical["actions_completed"])
        if canonical.get("quoted_prices"):
            record["quoted_prices"] = _json_array(canonical["quoted_prices"])
        value = _safe(record)
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            key = json.dumps([session_id, revision], separators=(",", ":"))
            await store.aput(self.namespace(customer_id), key, value, index=False)

    async def compact_customer(self, customer_id: str,
                               completed_revisions: set[int]) -> int:
        if not customer_id or not completed_revisions:
            return 0
        deleted = 0
        fact_ns = self.fact_namespace(customer_id)
        ep_ns = self.namespace(customer_id)
        async with AsyncPostgresStore.from_conn_string(self.dsn, index=None) as store:
            fact_items = [item for item in await _search_all(store, fact_ns)
                          if item.namespace == fact_ns and isinstance(item.value, dict)
                          and item.value.get("schema_version") == 1]
            fact_groups: dict[tuple[str, str, str], list] = {}
            for item in fact_items:
                rev = _revision(item.value)
                if rev > 0 and rev not in completed_revisions:
                    continue
                ident = (item.value.get("scope_type", "global"),
                         item.value.get("scope_id", ""),
                         str(item.value.get("key", "")))
                if ident[2]:
                    fact_groups.setdefault(ident, []).append(item)
            for group in fact_groups.values():
                if len(group) <= 1:
                    continue
                newest = max(group, key=lambda x: _revision(x.value))
                for item in group:
                    if item.key != newest.key:
                        await store.adelete(item.namespace, item.key)
                        deleted += 1

            ep_items = [item for item in await _search_all(store, ep_ns)
                        if item.namespace == ep_ns and isinstance(item.value, dict)
                        and item.value.get("schema_version") == 1]
            ep_groups: dict[str, list] = {}
            for item in ep_items:
                rev = _revision(item.value)
                if rev > 0 and rev not in completed_revisions:
                    continue
                sid = item.value.get("session_id")
                if isinstance(sid, str) and sid:
                    ep_groups.setdefault(sid, []).append(item)
            for group in ep_groups.values():
                if len(group) <= 1:
                    continue
                newest = max(group, key=lambda x: _revision(x.value))
                for item in group:
                    if item.key != newest.key:
                        await store.adelete(item.namespace, item.key)
                        deleted += 1
        return deleted

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
