"""Opt-in, retryable LangMem worker. Run as a separate MCP-memory process."""

import asyncio
import json
import logging
from datetime import date
from uuid import UUID

from app.agent.memory.langmem_extractor import extract_candidates
from app.configs import get_settings
from app.infarstructure.llm import build_llm
from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary
from app.mcp_servers.mcp_memory.services.langmem_admission import (
    admit_episode_candidate, admit_profile_candidates)
from app.mcp_servers.mcp_memory.services.memory import _write_fact
from app.mcp_servers.mcp_shared.config import database_url


logger = logging.getLogger(__name__)


async def process_one(repo: MemoryRepo, extractor, projector) -> bool:
    """Claim one committed turn; return False when the queue is empty."""
    async with repo.transaction() as conn:
        job = await repo.claim_distillation(conn, 120)
    if not job:
        return False
    job_id = job["job_id"]
    customer_id = job["customer_id"]
    session_id = str(job["session_id"])
    source_turn_id = str(job["source_turn_id"])
    try:
        async with repo.transaction() as conn:
            turn = await repo.distillation_turn(conn, job)
        if turn is None:
            raise ValueError("missing_committed_turn")
        date_value = turn["on_date"]
        on = date_value.isoformat() if isinstance(date_value, date) else str(date_value)
        committed = {"turn_id": source_turn_id, "customer_id": customer_id,
                     "session_id": session_id, "customer_text": turn["customer_text"],
                     "agent_text": turn["agent_text"], "on": on}
        observations = job.get("tool_observations") or []
        if isinstance(observations, str):
            observations = json.loads(observations)
        calls = [{**call, "source_turn_id": source_turn_id} for call in observations]
        messages = [{"role": "user", "content": json.dumps({**committed,
            "channel": turn["channel"], "tool_observations": calls},
            ensure_ascii=False)}]
        facts, episode = await extractor(messages, [])
        accepted, rejected = admit_profile_candidates(customer_id, session_id,
                                                        facts, [committed], calls)
        delta = (admit_episode_candidate(customer_id, session_id, episode,
                                         [committed], calls) if episode else None)
        if rejected:
            logger.info("LangMem rejected %d proposals for job %d", len(rejected), job_id)
        if job.get("mode") == "shadow":
            async with repo.transaction() as conn:
                await repo.finish_distillation(conn, job_id, "completed")
            return True
        async with repo.transaction() as conn:
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                await repo.finish_distillation(conn, job_id, "completed", "erasure_blocked")
                return True
            for fact in accepted:
                await _write_fact(repo, conn, customer_id, session_id, fact,
                                  f"langmem:{session_id}:{source_turn_id}",
                                  UUID(source_turn_id), date.fromisoformat(on))
            if delta:
                prior = await repo.episode_state(conn, session_id, customer_id)
                def decoded(value):
                    return json.loads(value) if isinstance(value, str) else value
                old = {"topics": decoded(prior["topics"]) if prior else [],
                       "resolved_prior_items": decoded(prior["resolved_prior_items"])
                       if prior else []}
                state = apply_episode_delta(old, delta, source_turn_id=source_turn_id,
                    customer_text=turn["customer_text"], agent_text=turn["agent_text"])
                confirmed = await repo.session_facts(conn, session_id, customer_id)
                turns = await repo.customer_turns(conn, session_id, customer_id)
                summary = build_episode_summary(confirmed, turns, 800, episode_state=state)
                await repo.upsert_episode_state(conn, session_id, customer_id,
                    turn["channel"], date.fromisoformat(on), summary,
                    episode.outcome, state["topics"], state["resolved_prior_items"])
        if projector is None:
            raise RuntimeError("projection_unavailable")
        async with repo.transaction() as conn:
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                await repo.finish_distillation(conn, job_id, "completed", "erasure_blocked")
                return True
            canonical = await repo.episode_state(conn, session_id, customer_id)
            if canonical is not None:
                await projector.put_episode(customer_id, session_id, dict(canonical))
            await repo.finish_distillation(conn, job_id, "completed")
    except Exception as exc:
        code = type(exc).__name__[:64]
        logger.warning("LangMem job %d failed: %s", job_id, code)
        status = "failed" if job.get("attempts", 0) >= 5 else "pending"
        async with repo.transaction() as conn:
            await repo.finish_distillation(conn, job_id, status, code)
    return True


async def run() -> None:
    settings = get_settings()
    if settings.langmem_mode == "off":
        raise RuntimeError("LANGMEM_MODE must be shadow or enabled for the worker")
    model = build_llm(settings.model_copy(update={"llm_model": settings.langmem_model
                                           or settings.llm_model}))
    repo = MemoryRepo(database_url(settings))
    from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
    projector = LangMemProjection(database_url(settings)) if settings.langmem_mode == "enabled" else None
    async def extractor(turns, existing):
        return await extract_candidates(model, turns, existing)
    try:
        while True:
            if not await process_one(repo, extractor, projector):
                await asyncio.sleep(1)
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(run())
