"""PostgreSQL storage operations for turns and LangMem jobs."""
from app.knowledge.config import enabled, configured_url, pinned_release

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

import asyncpg
from sqlalchemy.engine import make_url
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_shared.memory_observations import memory_observations


def _bounded_observations(calls: list[dict]) -> list[dict]:
    return memory_observations(calls)


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
                "SELECT current_database() AS database, "
                "pg_postmaster_start_time() AS server_started_at"
            )
        url = make_url(self.dsn)
        return {"database": row["database"], "host": url.host,
                "port": url.port or 5432,
                "server_started_at": row["server_started_at"].isoformat()}

    async def owner(self, conn, session_id: str) -> str | None:
        return await conn.fetchval("""SELECT customer_id FROM runtime.turns
            WHERE session_id=$1 AND customer_id IS NOT NULL LIMIT 1""",
            UUID(session_id))

    async def turns(self, conn, session_id: str) -> list:
        return await conn.fetch("""SELECT customer_text,agent_text FROM runtime.turns
            WHERE session_id=$1 ORDER BY turn_no""", UUID(session_id))

    async def recent_turns(self, conn, session_id: str, maximum: int) -> list:
        rows = await conn.fetch("""SELECT customer_text,agent_text FROM runtime.turns
            WHERE session_id=$1 ORDER BY turn_no DESC LIMIT $2""", UUID(session_id), maximum)
        return list(reversed(rows))

    async def turn_count(self, conn, session_id: str) -> int:
        return await conn.fetchval("SELECT COUNT(*) FROM runtime.turns WHERE session_id=$1",
                                   UUID(session_id))

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
                WHERE customer_id=$1""",
            customer_id)
        session_ids = [str(row["session_id"]) for row in sessions]
        await conn.execute("""UPDATE runtime.write_operations
            SET result='{"error":"erased"}'::jsonb
            WHERE result->>'customer_id'=$1 OR EXISTS (
                SELECT 1 FROM unnest($2::text[]) AS session_key
                WHERE operation_key LIKE session_key || ':%')""",
            customer_id, session_ids)
        deleted = {"facts": 0, "episodes": 0}
        job_result = await conn.execute("""DELETE FROM runtime.langmem_distillation_jobs
            WHERE customer_id=$1""", customer_id)
        deleted["langmem_distillation_jobs"] = int(job_result.rsplit(" ", 1)[-1])
        for table in ("order_links", "turns"):
            result = await conn.execute(f"DELETE FROM runtime.{table} WHERE customer_id=$1",
                                        customer_id)
            deleted[table] = int(result.rsplit(" ", 1)[-1])
        return {"status": "completed", "deleted_rows": deleted,
                "unresolved_pending_sessions": False}

    async def finish_erasure_request(self, conn, request_key: str, status: str,
                                     results: dict) -> None:
        await conn.execute("""UPDATE runtime.erasure_requests
            SET status=$2,store_results=$3::jsonb,updated_at=now()
            WHERE request_key=$1""", UUID(request_key), status,
            json.dumps(results, ensure_ascii=False))

    async def next_turn(self, conn, session_id: str) -> int:
        return await conn.fetchval("SELECT COALESCE(MAX(turn_no),0)+1 FROM runtime.turns WHERE session_id=$1", UUID(session_id))

    async def insert_turn(self, conn, session_id: str, number: int, customer_id: str | None,
                          channel: str, on, customer_text: str, agent_text: str,
                          client_msg_id: str) -> None:
        await conn.execute("""INSERT INTO runtime.turns
            (session_id,turn_no,customer_id,channel,on_date,customer_text,agent_text,client_msg_id)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8)""", UUID(session_id), number, customer_id,
            channel, on, customer_text, agent_text, UUID(client_msg_id))

    async def attribute_anonymous_turns(self, conn, session_id: str,
                                        customer_id: str) -> list[dict]:
        """Bind only this session's earlier anonymous turns after trusted identity."""
        rows = await conn.fetch("""UPDATE runtime.turns SET customer_id=$2,
            attributed_after_verification=TRUE
            WHERE session_id=$1 AND customer_id IS NULL
            RETURNING turn_no,client_msg_id AS source_turn_id""",
            UUID(session_id), customer_id)
        return [dict(row) for row in rows]

    async def enqueue_distillation(self, conn, session_id: str, customer_id: str,
                                   source_turn_id: str, tool_observations: list[dict],
                                   outcome: str = "khac", turn_no: int | None = None) -> None:
        if turn_no is None:
            turn_no = await conn.fetchval("SELECT MAX(turn_no) FROM runtime.turns WHERE session_id=$1",
                                          UUID(session_id))
        await conn.execute("""INSERT INTO runtime.langmem_distillation_jobs
            (session_id,customer_id,source_turn_id,turn_no,tool_observations,mode,verified_outcome)
            VALUES($1,$2,$3,$4,$5::jsonb,'enabled',$6)
            ON CONFLICT(session_id,source_turn_id) DO NOTHING""",
            UUID(session_id), customer_id, UUID(source_turn_id), turn_no,
            json.dumps(_bounded_observations(tool_observations), ensure_ascii=False), outcome)

    async def claim_distillation(self, conn, lease_seconds: int = 120) -> dict | None:
        row = await conn.fetchrow("""WITH candidate AS (
            SELECT j.job_id FROM runtime.langmem_distillation_jobs j
            WHERE j.mode='enabled'
              AND (j.status='pending' OR (j.status='leased' AND j.lease_until<now()))
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
                  j.tool_observations,j.attempts,j.accepted_proposals,
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

    async def recent_session_turns(self, conn, session_id: str, customer_id: str,
                                   through_turn_no: int, limit: int = 5) -> list[dict]:
        rows = await conn.fetch("""SELECT client_msg_id,customer_text,agent_text,
            on_date,channel FROM runtime.turns
            WHERE session_id=$1 AND customer_id=$2 AND turn_no<=$3
              AND client_msg_id IS NOT NULL
            ORDER BY turn_no DESC LIMIT $4""",
            UUID(session_id), customer_id, through_turn_no, limit)
        return [dict(row) for row in reversed(rows)]

    async def variant_details(self, conn, sku: str) -> dict | None:
        row = await conn.fetchrow("""SELECT variant_sku,parent_sku,size_label AS size,color
            FROM btc_source.variants WHERE variant_sku=$1""", sku)
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

    async def link_order(self, conn, customer_id: str, order_id: str) -> None:
        await conn.execute("""INSERT INTO runtime.order_links(customer_id,order_id)
            VALUES($1,$2) ON CONFLICT DO NOTHING""", customer_id, order_id)

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

    async def enqueue_knowledge_event(self, conn, data, session_id, customer_id):
        import os
        if enabled():
            from app.knowledge.runtime_events import enqueue_turn
            await enqueue_turn(conn, data, session_id, customer_id)

    async def purge_knowledge_evidence(self, conn, customer_id):
        import os
        if not await conn.fetchval("SELECT to_regclass('knowledge.events')"):
            return {"status": "not_configured"}
        from app.knowledge.repo import AsyncpgUnitOfWork
        from app.knowledge.erasure import erase_in_transaction
        async with conn.transaction():
            await conn.execute('SELECT pg_advisory_xact_lock(714221, 1)')
            return await erase_in_transaction(AsyncpgUnitOfWork(conn), customer_id)
