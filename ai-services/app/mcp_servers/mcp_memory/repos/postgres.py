"""PostgreSQL storage operations for turns, episodes and profile facts."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

import asyncpg
from sqlalchemy.engine import make_url


class MemoryRepo:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 5) -> None:
        self.dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        self.min_size = min_size
        self.max_size = max_size
        self.pool: asyncpg.Pool | None = None
        self.lock = asyncio.Lock()

    async def _pool(self) -> asyncpg.Pool:
        async with self.lock:
            if self.pool is None:
                self.pool = await asyncpg.create_pool(self.dsn, min_size=self.min_size,
                                                       max_size=self.max_size)
            return self.pool

    @asynccontextmanager
    async def transaction(self):
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            yield conn

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def database_identity(self) -> dict:
        """Report the database reached by this pool, without exposing credentials."""
        async with self.transaction() as conn:
            row = await conn.fetchrow(
                "SELECT current_database() AS database"
            )
        url = make_url(self.dsn)
        return {"database": row["database"], "host": url.host,
                "port": url.port or 5432}

    async def owner(self, conn, session_id: str) -> str | None:
        return await conn.fetchval("SELECT customer_id FROM ai_memory.turns WHERE session_id=$1 AND customer_id IS NOT NULL LIMIT 1", UUID(session_id))

    async def bind_owner(self, conn, session_id: str, customer_id: str) -> None:
        await conn.execute("UPDATE ai_memory.turns SET customer_id=$2 WHERE session_id=$1 AND customer_id IS NULL",
                           UUID(session_id), customer_id)

    async def stage_fact(self, conn, session_id: str, source_turn_id: UUID,
                         turn_no: int, fact: dict, on: date) -> None:
        await conn.execute("""INSERT INTO ai_memory.pending_facts
            (session_id,source_turn_id,turn_no,key,value,op,source_kind,source_tool,on_date)
            VALUES($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9)
            ON CONFLICT(session_id,source_turn_id,key) DO NOTHING""",
            UUID(session_id), source_turn_id, turn_no, fact["key"],
            json.dumps(fact.get("value"), ensure_ascii=False), fact["op"],
            fact["source_kind"], fact.get("source_tool"), on)

    async def pending_facts(self, conn, session_id: str) -> list:
        return await conn.fetch("""SELECT source_turn_id,key,value,op,source_kind,
            source_tool,on_date FROM ai_memory.pending_facts
            WHERE session_id=$1 AND expires_at>now()
            ORDER BY turn_no,key FOR UPDATE""", UUID(session_id))

    async def clear_pending(self, conn, session_id: str) -> None:
        await conn.execute("DELETE FROM ai_memory.pending_facts WHERE session_id=$1", UUID(session_id))

    async def turns(self, conn, session_id: str) -> list:
        return await conn.fetch("""SELECT customer_text,agent_text FROM ai_memory.turns
            WHERE session_id=$1 ORDER BY turn_no""", UUID(session_id))

    async def recent_turns(self, conn, session_id: str, maximum: int) -> list:
        rows = await conn.fetch("""SELECT customer_text,agent_text FROM ai_memory.turns
            WHERE session_id=$1 ORDER BY turn_no DESC LIMIT $2""", UUID(session_id), maximum)
        return list(reversed(rows))

    async def turn_count(self, conn, session_id: str) -> int:
        return await conn.fetchval("SELECT COUNT(*) FROM ai_memory.turns WHERE session_id=$1",
                                   UUID(session_id))

    async def facts(self, conn, customer_id: str, session_id: str, include_prior: bool) -> list:
        return await conn.fetch("""SELECT key,value,source,observed_at,on_date,source_kind,source_tool
            FROM ai_memory.facts
            WHERE customer_id=$1 AND status='active' AND ($2::boolean OR source_session_id=$3)""",
            customer_id, include_prior, UUID(session_id))

    async def episodes(self, conn, customer_id: str, session_id: str, maximum: int) -> list:
        return await conn.fetch("""SELECT session_id,channel,on_date,summary,outcome FROM ai_memory.episodes
            WHERE customer_id=$1 AND session_id<>$2 ORDER BY on_date DESC,updated_at DESC LIMIT $3""",
            customer_id, UUID(session_id), maximum)

    async def order_links(self, conn, customer_id: str) -> list[str]:
        rows = await conn.fetch("SELECT order_id FROM ai_memory.order_links WHERE customer_id=$1", customer_id)
        return [row["order_id"] for row in rows]

    async def lock_key(self, conn, key: str) -> None:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", key)

    async def next_turn(self, conn, session_id: str) -> int:
        return await conn.fetchval("SELECT COALESCE(MAX(turn_no),0)+1 FROM ai_memory.turns WHERE session_id=$1", UUID(session_id))

    async def insert_turn(self, conn, session_id: str, number: int, customer_id: str | None,
                          channel: str, on, customer_text: str, agent_text: str) -> None:
        await conn.execute("""INSERT INTO ai_memory.turns
            (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text)
            VALUES($1,$2,$3,$4,$5,$6,$7)""", UUID(session_id), number, customer_id,
            channel, on, customer_text, agent_text)

    async def upsert_episode(self, conn, session_id: str, customer_id: str, channel: str,
                             on, summary: str, outcome: str) -> None:
        await conn.execute("""INSERT INTO ai_memory.episodes(session_id,customer_id,channel,on_date,summary,outcome)
            VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(session_id) DO UPDATE SET summary=$5,
            outcome=CASE WHEN $6='khac' THEN ai_memory.episodes.outcome ELSE $6 END,updated_at=now()""",
            UUID(session_id), customer_id, channel, on, summary, outcome)

    async def seed_episode(self, conn, session_id: str, customer_id: str, channel: str,
                           on, summary: str, outcome: str) -> None:
        await conn.execute("""INSERT INTO ai_memory.episodes(session_id,customer_id,channel,on_date,summary,outcome)
            VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(session_id) DO NOTHING""",
            UUID(session_id), customer_id, channel, on, summary, outcome)

    async def link_order(self, conn, customer_id: str, order_id: str) -> None:
        await conn.execute("""INSERT INTO ai_memory.order_links(customer_id,order_id)
            VALUES($1,$2) ON CONFLICT DO NOTHING""", customer_id, order_id)

    async def active_fact(self, conn, customer_id: str, key: str):
        return await conn.fetchval("""SELECT fact_id FROM ai_memory.facts
            WHERE customer_id=$1 AND key=$2 AND status='active' FOR UPDATE""", customer_id, key)

    async def active_fact_record(self, conn, customer_id: str, key: str):
        return await conn.fetchrow("""SELECT fact_id,value FROM ai_memory.facts
            WHERE customer_id=$1 AND key=$2 AND status='active' FOR UPDATE""", customer_id, key)

    async def set_fact_status(self, conn, fact_id, status: str) -> None:
        await conn.execute("UPDATE ai_memory.facts SET status=$1 WHERE fact_id=$2", status, fact_id)

    async def insert_fact(self, conn, fact_id, customer_id: str, key: str, value,
                          source: str, session_id: str, previous, *, source_turn_id=None,
                          on_date=None, source_kind=None, source_tool=None) -> None:
        await conn.execute("""INSERT INTO ai_memory.facts
            (fact_id,customer_id,key,value,source,source_session_id,status,supersedes_fact_id,
             source_turn_id,on_date,source_kind,source_tool)
            VALUES($1,$2,$3,$4::jsonb,$5,$6,'active',$7,$8,$9,$10,$11)""", fact_id,
            customer_id, key, json.dumps(value, ensure_ascii=False), source,
            UUID(session_id), previous, source_turn_id, on_date, source_kind, source_tool)

    async def claim_operation(self, conn, key: str, args_hash: str) -> dict | None:
        await conn.execute("""INSERT INTO ai_memory.write_operations(operation_key,args_hash)
            VALUES($1,$2) ON CONFLICT DO NOTHING""", key, args_hash)
        row = await conn.fetchrow("""SELECT args_hash,result FROM ai_memory.write_operations
            WHERE operation_key=$1 FOR UPDATE""", key)
        if row["args_hash"] != args_hash:
            return {"error": "operation_key_conflict"}
        result = row["result"]
        return json.loads(result) if isinstance(result, str) else result

    async def finish_operation(self, conn, key: str, result: dict) -> None:
        await conn.execute("""UPDATE ai_memory.write_operations SET result=$2::jsonb
            WHERE operation_key=$1""", key, json.dumps(result, ensure_ascii=False, default=str))
