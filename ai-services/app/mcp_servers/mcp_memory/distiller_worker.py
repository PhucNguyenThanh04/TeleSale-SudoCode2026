"""Retryable LangMem worker for the primary long-term store."""

import asyncio
import json
import logging
import re
from datetime import date

from app.agent.memory.langmem_extractor import extract_candidates
from app.constants import Slot
from app.schemas.langmem import ProfileFactCandidate
from app.configs import get_settings
from app.infarstructure.llm import build_llm
from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
from app.mcp_servers.mcp_memory.repos.langmem_projection import select_facts, select_episodes
from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary
from app.mcp_servers.mcp_memory.services.langmem_admission import (
    admit_episode_candidate, admit_profile_candidates)
from app.mcp_servers.mcp_shared.config import database_url


logger = logging.getLogger(__name__)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def completed_revisions(repo, customer_id: str, versions: list[dict],
                              conn=None) -> set[int]:
    revisions = sorted({item["revision"] for item in versions
        if isinstance(item, dict) and type(item.get("revision")) is int
        and item["revision"] > 0})
    if not revisions:
        return set()
    if conn is None:
        async with repo.transaction() as reader:
            result = await repo.completed_job_revisions(reader, customer_id, revisions)
    else:
        result = await repo.completed_job_revisions(conn, customer_id, revisions)
    return result if isinstance(result, set) else set(revisions)


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
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                await repo.finish_distillation(conn, job_id, "completed", "erasure_blocked")
                return True
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
        stored = job.get("accepted_proposals")
        if isinstance(stored, str):
            stored = json.loads(stored)
        if stored is None:
            versions = await projector.list_fact_versions(customer_id) if projector is not None else []
            completed = await completed_revisions(repo, customer_id, versions)
            existing = select_facts(versions, completed)
            facts, episode = await extractor(messages, existing)
            accepted, rejected = admit_profile_candidates(customer_id, session_id,
                                                            facts, [committed], calls)
            delta = (admit_episode_candidate(customer_id, session_id, episode,
                                             [committed], calls) if episode else None)
            if (delta and episode and episode.open_blockers
                    and not any(fact["key"] == Slot.BLOCKER for fact in accepted)):
                blocker = episode.open_blockers[0]
                try:
                    proposed = ProfileFactCandidate(key=Slot.BLOCKER, value=blocker,
                        source_kind="customer", source_turn_id=source_turn_id,
                        evidence_quote=blocker, observed_on=date.fromisoformat(on))
                    admitted, blocker_rejected = admit_profile_candidates(
                        customer_id, session_id, [proposed], [committed], calls)
                    accepted.extend(admitted)
                    rejected.extend(blocker_rejected)
                except ValueError:
                    pass
            if rejected:
                logger.info("LangMem rejected %d proposals for job %d", len(rejected), job_id)
            outcome = job.get("verified_outcome", "khac")
            if (outcome == "khac" and episode
                    and episode.customer_id == customer_id
                    and episode.session_id == session_id
                    and source_turn_id in episode.source_turn_ids
                    and episode.outcome == "hen_goi_lai"
                    and re.search(r"gọi lại|hẹn gọi", turn["customer_text"], re.I)):
                outcome = "hen_goi_lai"
            stored = {"facts": accepted, "delta": delta, "outcome": outcome}
            if job.get("mode") != "shadow":
                async with repo.transaction() as conn:
                    await repo.save_distillation_proposals(conn, job_id, stored)
        else:
            accepted = stored["facts"]
            delta = stored.get("delta")
            outcome = stored.get("outcome", "khac")
        if job.get("mode") == "shadow":
            async with repo.transaction() as conn:
                await repo.finish_distillation(conn, job_id, "completed")
            return True
        if projector is None:
            raise RuntimeError("memory_store_unavailable")
        async with repo.transaction() as conn:
            await repo.lock_key(conn, f"erasure:{customer_id}")
            await repo.lock_key(conn, f"langmem:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                await repo.finish_distillation(conn, job_id, "completed", "erasure_blocked")
                return True
            versions = await projector.list_fact_versions(customer_id)
            completed = await completed_revisions(repo, customer_id, versions, conn)
            written = await projector.put_facts(customer_id, session_id, source_turn_id,
                on, accepted, revision=job_id, completed_revisions=completed)
            if delta or accepted or outcome != "khac":
                episode_versions = await projector.list_episode_versions(customer_id)
                completed_episodes = await completed_revisions(
                    repo, customer_id, episode_versions, conn)
                prior = next((item for item in select_episodes(
                    episode_versions, completed_episodes)
                    if item.get("session_id") == session_id), None)
                old = {"topics": decoded(prior["topics"]) if prior else [],
                       "resolved_prior_items": decoded(prior["resolved_prior_items"])
                       if prior else []}
                state = (apply_episode_delta(old, delta, source_turn_id=source_turn_id,
                    customer_text=turn["customer_text"], agent_text=turn["agent_text"])
                    if delta else old)
                fragments = []
                previous_summary = prior.get("summary") if prior else None
                if previous_summary and previous_summary != "Chưa có diễn biến riêng được xác minh.":
                    fragments.append(previous_summary)
                narrative = build_episode_summary([], [], 800, episode_state=state)
                if narrative != "Chưa có diễn biến riêng được xác minh." and narrative not in fragments:
                    fragments.append(narrative)
                for fact in accepted:
                    quote = fact.get("evidence_quote")
                    if fact.get("source_kind") == "customer" and quote:
                        if quote not in " | ".join(fragments):
                            fragments.append(quote)
                summary = " | ".join(fragments)[:800]
                if not summary:
                    summary = "Chưa có diễn biến riêng được xác minh."
                await projector.put_episode(customer_id, session_id, {
                    "channel": turn["channel"], "on_date": on,
                    "summary": summary,
                    "outcome": outcome if outcome != "khac" else (
                        prior.get("outcome", "khac") if prior else "khac"),
                    "status": "active", "topics": state["topics"],
                    "resolved_prior_items": state["resolved_prior_items"]},
                    revision=job_id)
            await repo.finish_distillation(conn, job_id, "completed", accepted_writes=(
                written if isinstance(written, list) else []))
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
        while True:
            await asyncio.sleep(3600)
    model = build_llm(settings.model_copy(update={"llm_model": settings.langmem_model
                                           or settings.llm_model,
                                           "llm_max_tokens": settings.langmem_max_tokens}))
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
