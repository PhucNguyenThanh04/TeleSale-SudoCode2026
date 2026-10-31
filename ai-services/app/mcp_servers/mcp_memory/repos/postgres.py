"""PostgreSQL storage operations for turns, episodes and profile facts."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

import asyncpg
from sqlalchemy.engine import make_url
from app.mcp_servers.mcp_shared.pii import mask_pii


_BUSINESS_TOOLS = {"catalog.search", "catalog.get_product", "inventory.check",
                   "pricing.get_quote", "policy.search", "order.get_status"}


def _bounded_observations(calls: list[dict]) -> list[dict]:
    safe = []
    for call in calls[:20]:
        if not isinstance(call, dict) or call.get("name") not in _BUSINESS_TOOLS:
            continue
        if not isinstance(call.get("result"), dict) or "error" in call["result"]:
            continue
        item = {"name": call["name"], "args": call.get("args", {}),
                "result": call["result"]}
        encoded = json.dumps(item, ensure_ascii=False, default=str)
        if len(encoded) <= 4000:
            safe.append(json.loads(mask_pii(encoded)))
    return safe[:8]


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
        return await conn.fetchval("""SELECT COALESCE(
            (SELECT customer_id FROM runtime.turns
             WHERE session_id=$1 AND customer_id IS NOT NULL LIMIT 1),
            (SELECT customer_id FROM runtime.episodes WHERE session_id=$1))""",
            UUID(session_id))

    async def turns(self, conn, session_id: str) -> list:
        return await conn.fetch("""SELECT customer_text,agent_text FROM runtime.turns
            WHERE session_id=$1 ORDER BY turn_no""", UUID(session_id))

    async def customer_turns(self, conn, session_id: str, customer_id: str) -> list:
        return await conn.fetch("""SELECT customer_text,agent_text FROM runtime.turns
            WHERE session_id=$1 AND customer_id=$2 ORDER BY turn_no""",
            UUID(session_id), customer_id)

    async def recent_turns(self, conn, session_id: str, maximum: int) -> list:
        rows = await conn.fetch("""SELECT customer_text,agent_text FROM runtime.turns
            WHERE session_id=$1 ORDER BY turn_no DESC LIMIT $2""", UUID(session_id), maximum)
        return list(reversed(rows))

    async def recent_customer_turns(self, conn, session_id: str, customer_id: str,
                                    maximum: int) -> list:
        rows = await conn.fetch("""SELECT customer_text,agent_text FROM runtime.turns
            WHERE session_id=$1 AND customer_id=$2 ORDER BY turn_no DESC LIMIT $3""",
            UUID(session_id), customer_id, maximum)
        return list(reversed(rows))

    async def turn_count(self, conn, session_id: str) -> int:
        return await conn.fetchval("SELECT COUNT(*) FROM runtime.turns WHERE session_id=$1",
                                   UUID(session_id))

    async def facts(self, conn, customer_id: str, session_id: str, include_prior: bool) -> list:
        return await conn.fetch("""SELECT key,value,source,observed_at,on_date,source_kind,source_tool,evidence_quote,
            scope_type,scope_id
            FROM runtime.facts
            WHERE customer_id=$1 AND status='active' AND ($2::boolean OR source_session_id=$3)""",
            customer_id, include_prior, UUID(session_id))

    async def session_facts(self, conn, session_id: str, customer_id: str) -> list:
        rows = await conn.fetch("""SELECT key,value,scope_type,scope_id,status
            FROM runtime.facts WHERE source_session_id=$1 AND customer_id=$2
            AND status='active' ORDER BY observed_at,fact_id""", UUID(session_id), customer_id)
        return [{"key": row["key"], "value": (json.loads(row["value"])
                 if isinstance(row["value"], str) else row["value"]),
                 "scope_type": row["scope_type"], "scope_id": row["scope_id"],
                 "status": row["status"]} for row in rows]

    async def episodes(self, conn, customer_id: str, session_id: str, maximum: int) -> list:
        return await conn.fetch("""SELECT session_id,channel,on_date,summary,outcome,topics,resolved_prior_items,status FROM runtime.episodes
            WHERE customer_id=$1 AND session_id<>$2 ORDER BY on_date DESC,updated_at DESC LIMIT $3""",
            customer_id, UUID(session_id), maximum)

    async def episode_state(self, conn, session_id: str, customer_id: str):
        return await conn.fetchrow("""SELECT session_id,channel,on_date,summary,outcome,topics,resolved_prior_items,status FROM runtime.episodes
            WHERE session_id=$1 AND customer_id=$2""", UUID(session_id), customer_id)

    async def prior_open_items(self, conn, customer_id: str, session_id: str) -> dict[str, tuple[str, str]]:
        rows = await conn.fetch("""SELECT topics,resolved_prior_items FROM runtime.episodes
            WHERE customer_id=$1 AND session_id<>$2""", customer_id, UUID(session_id))
        decoded = [(json.loads(row["topics"]) if isinstance(row["topics"], str)
                    else row["topics"],
                    json.loads(row["resolved_prior_items"])
                    if isinstance(row["resolved_prior_items"], str)
                    else row["resolved_prior_items"]) for row in rows]
        resolved = {item.get("item_id") for _, markers in decoded
                    for item in markers if isinstance(item, dict)}
        return {item["item_id"]: (topic["scope_type"], topic["scope_id"])
                for topics, _ in decoded for topic in topics if isinstance(topic, dict)
                for item in topic.get("items", []) if isinstance(item, dict)
                and item.get("status") == "open" and item.get("item_id") not in resolved}

    async def prior_session_ids(self, conn, customer_id: str, session_id: str) -> list[str]:
        rows = await conn.fetch("""SELECT DISTINCT session_id FROM runtime.episodes
            WHERE customer_id=$1 AND session_id<>$2""", customer_id, UUID(session_id))
        return [str(row["session_id"]) for row in rows]

    async def order_links(self, conn, customer_id: str) -> list[str]:
        rows = await conn.fetch("SELECT order_id FROM runtime.order_links WHERE customer_id=$1", customer_id)
        return [row["order_id"] for row in rows]

    async def lock_key(self, conn, key: str) -> None:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", key)

    async def is_erasure_blocked(self, conn, customer_id: str) -> bool:
        return bool(await conn.fetchval("""SELECT EXISTS(
            SELECT 1 FROM runtime.erasure_requests WHERE customer_id=$1
        )""", customer_id))

    async def create_erasure_request(self, conn, request_key: str, customer_id: str,
                                     verification_ref: str, verified_by: str,
                                     scope: list[str]) -> dict:
        await conn.execute("""INSERT INTO runtime.erasure_requests
            (request_key,customer_id,verification_ref,verified_by,scope)
            VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(request_key) DO NOTHING""",
            UUID(request_key), customer_id, verification_ref, verified_by,
            json.dumps(scope))
        row = await conn.fetchrow("""SELECT customer_id,verification_ref,verified_by,scope,status
            FROM runtime.erasure_requests WHERE request_key=$1""", UUID(request_key))
        if (row["customer_id"] != customer_id
                or row["verification_ref"] != verification_ref
                or row["verified_by"] != verified_by):
            return {"error": "request_key_conflict"}
        stored_scope = json.loads(row["scope"]) if isinstance(row["scope"], str) else row["scope"]
        if stored_scope != scope:
            return {"error": "request_key_conflict"}
        return {"request_key": request_key, "customer_id": customer_id,
                "scope": stored_scope, "status": row["status"]}

    async def erasure_request(self, conn, request_key: str, *, for_update: bool = False):
        row = await conn.fetchrow("""SELECT customer_id,scope,status,store_results
            FROM runtime.erasure_requests WHERE request_key=$1""" +
            (" FOR UPDATE" if for_update else ""), UUID(request_key))
        if row is None:
            return None
        def decoded(value):
            return json.loads(value) if isinstance(value, str) else value
        return {"customer_id": row["customer_id"], "scope": decoded(row["scope"]),
                "status": row["status"], "store_results": decoded(row["store_results"])}

    async def purge_customer_memory(self, conn, customer_id: str) -> dict:
        sessions = await conn.fetch("""SELECT session_id FROM runtime.turns
                WHERE customer_id=$1
            UNION SELECT source_session_id FROM runtime.facts WHERE customer_id=$1
            UNION SELECT session_id FROM runtime.episodes WHERE customer_id=$1""",
            customer_id)
        session_ids = [str(row["session_id"]) for row in sessions]
        fully_owned = await conn.fetch("""SELECT DISTINCT t.session_id
            FROM runtime.turns AS t WHERE t.customer_id=$1
            AND NOT EXISTS (SELECT 1 FROM runtime.turns AS other
                WHERE other.session_id=t.session_id
                AND other.customer_id IS DISTINCT FROM $1)""", customer_id)
        await conn.execute("""UPDATE runtime.write_operations
            SET result='{"error":"erased"}'::jsonb
            WHERE result->>'customer_id'=$1 OR EXISTS (
                SELECT 1 FROM unnest($2::text[]) AS session_key
                WHERE operation_key LIKE session_key || ':%')""",
            customer_id, session_ids)
        await conn.execute("DELETE FROM runtime.pending_facts WHERE session_id=ANY($1::uuid[])",
                           [row["session_id"] for row in fully_owned])
        deleted = {}
        job_result = await conn.execute("""DELETE FROM runtime.langmem_distillation_jobs
            WHERE customer_id=$1""", customer_id)
        deleted["langmem_distillation_jobs"] = int(job_result.rsplit(" ", 1)[-1])
        for table in ("order_links", "facts", "episodes", "turns"):
            result = await conn.execute(f"DELETE FROM runtime.{table} WHERE customer_id=$1",
                                        customer_id)
            deleted[table] = int(result.rsplit(" ", 1)[-1])
        ambiguous_pending = await conn.fetchval("""SELECT count(*) FROM runtime.pending_facts
            WHERE session_id=ANY($1::uuid[])""", [UUID(session) for session in session_ids])
        return {"status": "partial" if ambiguous_pending else "completed",
                "deleted_rows": deleted, "unresolved_pending_sessions": bool(ambiguous_pending)}

    async def finish_erasure_request(self, conn, request_key: str, status: str,
                                     results: dict) -> None:
        await conn.execute("""UPDATE runtime.erasure_requests
            SET status=$2,store_results=$3::jsonb,updated_at=now()
            WHERE request_key=$1""", UUID(request_key), status,
            json.dumps(results, ensure_ascii=False))

    async def next_turn(self, conn, session_id: str) -> int:
        return await conn.fetchval("SELECT COALESCE(MAX(turn_no),0)+1 FROM runtime.turns WHERE session_id=$1", UUID(session_id))

    async def insert_turn(self, conn, session_id: str, number: int, customer_id: str | None,
                          channel: str, on, customer_text: str, agent_text: str) -> None:
        await conn.execute("""INSERT INTO runtime.turns
            (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text)
            VALUES($1,$2,$3,$4,$5,$6,$7)""", UUID(session_id), number, customer_id,
            channel, on, customer_text, agent_text)

    async def enqueue_distillation(self, conn, session_id: str, customer_id: str,
                                   source_turn_id: str, tool_observations: list[dict],
                                   mode: str = "enabled", outcome: str = "khac") -> None:
        turn_no = await conn.fetchval("SELECT MAX(turn_no) FROM runtime.turns WHERE session_id=$1",
                                      UUID(session_id))
        await conn.execute("""INSERT INTO runtime.langmem_distillation_jobs
            (session_id,customer_id,source_turn_id,turn_no,tool_observations,mode,verified_outcome)
            VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)
            ON CONFLICT(session_id,source_turn_id) DO NOTHING""",
            UUID(session_id), customer_id, UUID(source_turn_id), turn_no,
            json.dumps(_bounded_observations(tool_observations), ensure_ascii=False), mode,
            outcome)

    async def claim_distillation(self, conn, lease_seconds: int = 120) -> dict | None:
        row = await conn.fetchrow("""WITH candidate AS (
            SELECT j.job_id FROM runtime.langmem_distillation_jobs j
            WHERE (j.status='pending' OR (j.status='leased' AND j.lease_until<now()))
              AND j.attempts<5
              AND NOT EXISTS (SELECT 1 FROM runtime.langmem_distillation_jobs earlier
                  WHERE earlier.session_id=j.session_id AND earlier.turn_no<j.turn_no
                    AND earlier.status IN ('pending','leased'))
            ORDER BY j.created_at,j.job_id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE runtime.langmem_distillation_jobs j
        SET status='leased',attempts=attempts+1,
            lease_until=now()+($1::int * interval '1 second'),updated_at=now()
        FROM candidate WHERE j.job_id=candidate.job_id
        RETURNING j.job_id,j.session_id,j.customer_id,j.source_turn_id,j.turn_no,
                  j.tool_observations,j.mode,j.attempts,j.accepted_proposals,
                  j.verified_outcome""", lease_seconds)
        return dict(row) if row else None

    async def save_distillation_proposals(self, conn, job_id: int,
                                          proposals: dict) -> None:
        await conn.execute("""UPDATE runtime.langmem_distillation_jobs
            SET accepted_proposals=$2::jsonb,updated_at=now()
            WHERE job_id=$1 AND status='leased'""", job_id,
            json.dumps(proposals, ensure_ascii=False))

    async def distillation_turn(self, conn, job: dict) -> dict | None:
        row = await conn.fetchrow("""SELECT customer_id,customer_text,agent_text,on_date,channel
            FROM runtime.turns WHERE session_id=$1 AND turn_no=$2 AND customer_id=$3""",
            job["session_id"], job["turn_no"], job["customer_id"])
        return dict(row) if row else None

    async def finish_distillation(self, conn, job_id: int, status: str,
                                  error_code: str | None = None,
                                  accepted_writes: list[dict] | None = None) -> None:
        await conn.execute("""UPDATE runtime.langmem_distillation_jobs
            SET status=$2,lease_until=NULL,error_code=$3,
                accepted_writes=$4::jsonb,updated_at=now()
            WHERE job_id=$1""", job_id, status, error_code,
            json.dumps(accepted_writes or [], ensure_ascii=False))

    async def completed_job_revisions(self, conn, customer_id: str,
                                      revisions: list[int]) -> set[int]:
        if not revisions:
            return set()
        rows = await conn.fetch("""SELECT job_id FROM runtime.langmem_distillation_jobs
            WHERE customer_id=$1 AND status='completed' AND job_id=ANY($2::bigint[])""",
            customer_id, revisions)
        return {row["job_id"] for row in rows}

    async def upsert_episode(self, conn, session_id: str, customer_id: str, channel: str,
                             on, summary: str, outcome: str) -> None:
        await conn.execute("""INSERT INTO runtime.episodes(session_id,customer_id,channel,on_date,summary,outcome)
            VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(session_id) DO UPDATE SET summary=$5,
            outcome=CASE WHEN $6='khac' THEN runtime.episodes.outcome ELSE $6 END,updated_at=now()""",
            UUID(session_id), customer_id, channel, on, summary, outcome)

    async def upsert_episode_state(self, conn, session_id: str, customer_id: str,
                                   channel: str, on, summary: str, outcome: str,
                                   topics: list[dict], resolved_prior_items: list[dict]) -> None:
        await conn.execute("""INSERT INTO runtime.episodes
            (session_id,customer_id,channel,on_date,summary,outcome,topics,resolved_prior_items)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb)
            ON CONFLICT(session_id) DO UPDATE SET summary=$5,
            outcome=CASE WHEN $6='khac' THEN runtime.episodes.outcome ELSE $6 END,
            topics=$7::jsonb,resolved_prior_items=$8::jsonb,updated_at=now()""",
            UUID(session_id), customer_id, channel, on, summary, outcome,
            json.dumps(topics, ensure_ascii=False),
            json.dumps(resolved_prior_items, ensure_ascii=False))

    async def seed_episode(self, conn, session_id: str, customer_id: str, channel: str,
                           on, summary: str, outcome: str) -> None:
        await conn.execute("""INSERT INTO runtime.episodes(session_id,customer_id,channel,on_date,summary,outcome)
            VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(session_id) DO NOTHING""",
            UUID(session_id), customer_id, channel, on, summary, outcome)

    async def link_order(self, conn, customer_id: str, order_id: str) -> None:
        await conn.execute("""INSERT INTO runtime.order_links(customer_id,order_id)
            VALUES($1,$2) ON CONFLICT DO NOTHING""", customer_id, order_id)

    async def active_fact(self, conn, customer_id: str, key: str,
                          scope_type: str = "global", scope_id: str = ""):
        return await conn.fetchval("""SELECT fact_id FROM runtime.facts
            WHERE customer_id=$1 AND key=$2 AND scope_type=$3 AND scope_id=$4
            AND status='active' FOR UPDATE""", customer_id, key, scope_type, scope_id)

    async def active_fact_record(self, conn, customer_id: str, key: str,
                                 scope_type: str = "global", scope_id: str = ""):
        return await conn.fetchrow("""SELECT fact_id,value FROM runtime.facts
            WHERE customer_id=$1 AND key=$2 AND scope_type=$3 AND scope_id=$4
            AND status='active' FOR UPDATE""", customer_id, key, scope_type, scope_id)

    async def set_fact_status(self, conn, fact_id, status: str) -> None:
        await conn.execute("UPDATE runtime.facts SET status=$1 WHERE fact_id=$2", status, fact_id)

    async def insert_fact(self, conn, fact_id, customer_id: str, key: str, value,
                          source: str, session_id: str, previous, *, source_turn_id=None,
                          on_date=None, source_kind=None, source_tool=None,
                          evidence_quote=None, scope_type="global", scope_id="") -> None:
        await conn.execute("""INSERT INTO runtime.facts
            (fact_id,customer_id,key,value,source,source_session_id,status,supersedes_fact_id,
             source_turn_id,on_date,source_kind,source_tool,evidence_quote,scope_type,scope_id)
            VALUES($1,$2,$3,$4::jsonb,$5,$6,'active',$7,$8,$9,$10,$11,$12,$13,$14)""", fact_id,
            customer_id, key, json.dumps(value, ensure_ascii=False), source,
            UUID(session_id), previous, source_turn_id, on_date, source_kind,
            source_tool, evidence_quote, scope_type, scope_id)

    async def claim_operation(self, conn, key: str, args_hash: str) -> dict | None:
        await conn.execute("""INSERT INTO runtime.write_operations(operation_key,args_hash)
            VALUES($1,$2) ON CONFLICT DO NOTHING""", key, args_hash)
        row = await conn.fetchrow("""SELECT args_hash,result FROM runtime.write_operations
            WHERE operation_key=$1 FOR UPDATE""", key)
        if row["args_hash"] != args_hash:
            return {"error": "operation_key_conflict"}
        result = row["result"]
        return json.loads(result) if isinstance(result, str) else result

    async def finish_operation(self, conn, key: str, result: dict) -> None:
        await conn.execute("""UPDATE runtime.write_operations SET result=$2::jsonb
            WHERE operation_key=$1""", key, json.dumps(result, ensure_ascii=False, default=str))
