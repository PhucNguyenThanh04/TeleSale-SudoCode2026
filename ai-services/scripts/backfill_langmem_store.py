"""One-time, provenance-filtered migration from legacy customer knowledge."""

import asyncio
import json
from datetime import date

from app.configs import get_settings
from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.services.memory import _valid_fact
from app.mcp_servers.mcp_shared.config import database_url


def _value(value):
    return json.loads(value) if isinstance(value, str) else value


async def backfill_customer(repo: MemoryRepo, store: LangMemProjection,
                            customer_id: str) -> dict[str, int]:
    """Copy only sourced, safe active records; never overwrite new LangMem writes."""
    counts = {"facts": 0, "episodes": 0, "skipped": 0}
    async with repo.transaction() as conn:
        await repo.lock_key(conn, f"erasure:{customer_id}")
        await repo.lock_key(conn, f"langmem:{customer_id}")
        if await repo.is_erasure_blocked(conn, customer_id):
            return counts
        facts = await conn.fetch("""SELECT key,value,scope_type,scope_id,source_kind,
            source_tool,evidence_quote,source_turn_id,source_session_id,on_date
            FROM runtime.facts WHERE customer_id=$1 AND status='active'
            ORDER BY observed_at,fact_id""", customer_id)
        for row in facts:
            source_turn_id = row["source_turn_id"]
            session_id = row["source_session_id"]
            on = row["on_date"]
            fact = {"key": row["key"], "value": _value(row["value"]),
                "op": "set", "scope_type": row["scope_type"],
                "scope_id": row["scope_id"], "source_kind": row["source_kind"],
                "source_tool": row["source_tool"],
                "evidence_quote": row["evidence_quote"]}
            if (not source_turn_id or not session_id or not isinstance(on, date)
                    or not _valid_fact(fact)):
                counts["skipped"] += 1
                continue
            written = await store.put_facts(customer_id, str(session_id),
                str(source_turn_id), on.isoformat(), [fact], revision=-1)
            counts["facts"] += len(written)
        episodes = await conn.fetch("""SELECT session_id,channel,on_date,summary,
            outcome,status,topics,resolved_prior_items FROM runtime.episodes
            WHERE customer_id=$1 ORDER BY on_date,session_id""", customer_id)
        for row in episodes:
            session_id = str(row["session_id"])
            if await store.get_episode(customer_id, session_id) is not None:
                continue
            await store.put_episode(customer_id, session_id, dict(row))
            counts["episodes"] += 1
    return counts


async def main() -> None:
    dsn = database_url(get_settings())
    repo = MemoryRepo(dsn)
    store = LangMemProjection(dsn)
    counts = {"facts": 0, "episodes": 0, "skipped": 0}
    try:
        async with repo.transaction() as conn:
            customers = await conn.fetch("""SELECT customer_id FROM runtime.facts
                UNION SELECT customer_id FROM runtime.episodes""")
        for row in customers:
            result = await backfill_customer(repo, store, row["customer_id"])
            for key in counts:
                counts[key] += result[key]
    finally:
        await repo.close()
    print(counts)


if __name__ == "__main__":
    asyncio.run(main())
