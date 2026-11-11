"""Retryable LangMem worker for the primary long-term store."""

from app.mcp_servers.mcp_shared.decision_diagnostics import worker_boundary, worker_envelope, emit as diagnostic_emit, active as diagnostic_active, save_worker_envelope


import asyncio
import inspect
import json
import logging
import re
from datetime import date

from app.agent.memory.langmem_extractor import extract_candidates
from app.agent.memory.deterministic_tool_facts import (deterministic_episode_tools,
                                                       verified_order_details,
                                                       verified_tool_candidates,
                                                       verified_variant_details)
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


def collect_prior_open_items(episodes: list[dict], current_session_id: str) -> list[dict]:
    """Return open items from prior sessions that have not yet been resolved."""
    resolved_ids = set()
    for ep in episodes:
        if not isinstance(ep, dict) or ep.get("status", "active") != "active":
            continue
        for item in decoded(ep.get("resolved_prior_items") or []) or []:
            if isinstance(item, dict) and isinstance(item.get("item_id"), str):
                resolved_ids.add(item["item_id"])
    open_items = []
    seen = set()
    for ep in episodes:
        if (not isinstance(ep, dict) or ep.get("session_id") == current_session_id
                or ep.get("status", "active") != "active"):
            continue
        for topic in decoded(ep.get("topics") or []) or []:
            if not isinstance(topic, dict):
                continue
            scope_type = topic.get("scope_type", "global")
            scope_id = topic.get("scope_id", "")
            for item in topic.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("item_id")
                if (isinstance(item_id, str) and item_id not in resolved_ids
                        and item_id not in seen and item.get("status") == "open"):
                    seen.add(item_id)
                    open_items.append({
                        "item_id": item_id,
                        "kind": item.get("kind", "blocker"),
                        "text": item.get("text", ""),
                        "scope_type": scope_type,
                        "scope_id": scope_id,
                    })
    return open_items


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


@worker_boundary
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
            if hasattr(repo, 'distillation_claim_current') and not await repo.distillation_claim_current(conn, job_id, job['attempts']):
                return True
            # Reclaim a crashed final attempt so it cannot block this customer's queue forever.
            if job.get('attempts', 0) > 5:
                await repo.finish_distillation(conn, job_id, 'failed', 'lease_attempts_exhausted')
                return True
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
        window = []
        if type(job.get("turn_no")) is int:
            async with repo.transaction() as conn:
                window = await repo.recent_session_turns(
                    conn, session_id, customer_id, job["turn_no"], 5)
        if not isinstance(window, list) or not any(
                str(item.get("client_msg_id")) == source_turn_id
                for item in window if isinstance(item, dict)):
            window = [{**turn, "client_msg_id": source_turn_id}]
        messages = []
        consultation_turns, consultation_calls = [], []
        for item in window:
            if not isinstance(item, dict) or not item.get("client_msg_id"):
                continue
            item_on = item.get("on_date", on)
            payload = {"turn_id": str(item["client_msg_id"]),
                "customer_id": customer_id, "session_id": session_id,
                "customer_text": item.get("customer_text", ""),
                "agent_text": item.get("agent_text", ""),
                "on": item_on.isoformat() if isinstance(item_on, date) else str(item_on),
                "channel": item.get("channel", turn["channel"])}
            prior_calls=decoded(item.get('tool_observations') or [])
            observed=calls if payload['turn_id']==source_turn_id else prior_calls
            if isinstance(observed,list):
                consultation_calls.extend({**c,'source_turn_id':payload['turn_id']} for c in observed if isinstance(c,dict))
            consultation_turns.append(payload.copy())
            if payload["turn_id"] == source_turn_id:
                payload["tool_observations"] = calls
            messages.append({"role": "user", "content": json.dumps(
                payload, ensure_ascii=False)})
        stored = job.get("accepted_proposals")
        if isinstance(stored, str):
            stored = json.loads(stored)
        if stored is None:
            versions = await projector.list_fact_versions(customer_id) if projector is not None else []
            completed = await completed_revisions(repo, customer_id, versions)
            existing = select_facts(versions, completed)
            ep_versions = await projector.list_episode_versions(customer_id) if projector is not None else []
            completed_eps = await completed_revisions(repo, customer_id, ep_versions)
            prior_episodes = select_episodes(ep_versions, completed_eps)
            prior_open_list = collect_prior_open_items(prior_episodes, '')
            prior_open_map = {item["item_id"]: (item["scope_type"], item["scope_id"])
                              for item in prior_open_list}
            # Each job owns one unseen source turn. Previous speech is reference
            # context, not another turn to extract again on every job.
            latest = json.loads(messages[-1]['content'])
            previous = json.loads(messages[-2]['content']) if len(messages) > 1 else {}
            latest['reference_context'] = {'previous_agent_text': previous.get('agent_text', '')}
            extraction_messages = [{'role': 'user', 'content': json.dumps(latest, ensure_ascii=False)}]
            arguments = (extraction_messages, existing, prior_open_list)
            signature = inspect.signature(extractor)
            try:
                signature.bind(*arguments)
            except TypeError:
                arguments = arguments[:2]
                signature.bind(*arguments)
            facts, episode = await extractor(*arguments)
            facts = [fact for fact in facts if fact.source_kind == "customer"]
            facts.extend(verified_tool_candidates(turn["agent_text"], calls,
                                                  source_turn_id, on))
            accepted, rejected = admit_profile_candidates(customer_id, session_id,
                                                            facts, [committed], calls)
            for call in calls:
                name = call.get("name")
                result = call.get("result", {})
                if not isinstance(result, dict) or "error" in result:
                    continue
                if name == "order.create" and result.get("status") == "created":
                    sku = call.get("args", {}).get("sku")
                    if isinstance(sku, str):
                        async with repo.transaction() as conn:
                            variant = await repo.variant_details(conn, sku)
                        accepted.extend(verified_order_details(call, variant, source_turn_id))
                elif name in {"inventory.check", "pricing.get_quote"}:
                    sku = result.get("sku") or call.get("args", {}).get("sku")
                    if isinstance(sku, str) and sku.count("-") >= 3:
                        async with repo.transaction() as conn:
                            variant = await repo.variant_details(conn, sku)
                        accepted.extend(verified_variant_details(call, variant, source_turn_id))
            delta = (admit_episode_candidate(customer_id, session_id, episode,
                                             [committed], calls, prior_open_map)
                     if episode else None)
            # Independent deterministic admission: an LLM need not propose the
            # snapshot, and cannot grant consent through an unsupported proposal.
            from app.mcp_servers.mcp_shared.consultation import committed_consultation, admit_consultation
            snapshot=committed_consultation(customer_id,session_id,consultation_turns,consultation_calls,
                prior_episodes=[ep for ep in prior_episodes if ep.get('session_id') != session_id])
            snapshot_data=snapshot.model_dump(mode='json')
            if diagnostic_active():
                from types import SimpleNamespace
                diagnostic_state = {'customer_id': customer_id, 'request': SimpleNamespace(session_id=session_id, client_msg_id=source_turn_id), 'history': [{'source_turn_id': t['turn_id']} for t in consultation_turns]}
                diagnostic_emit('provenance', state=diagnostic_state, component='worker', provenance=True)
                diagnostic_emit('worker_admission', state=diagnostic_state, component='worker', snapshot=snapshot_data, revision=job_id, status='unknown', rejected_count=len(rejected))
            changed={k:v for k,v in snapshot.source_refs.items() if v.source_turn_id==source_turn_id}
            if set(changed)-{'candidates'}:
                patch={k:snapshot_data[k] for k in changed}
                patch['source_refs']={k:v.model_dump(mode='json') for k,v in changed.items()}
                admitted_snapshot=admit_consultation(patch,customer_id=customer_id,session_id=session_id,
                    committed_turns=consultation_turns,tool_calls=consultation_calls,
                    prior_episodes=[ep for ep in prior_episodes if ep.get('session_id') != session_id])
                if diagnostic_active():
                    diagnostic_emit('worker_admission', state=diagnostic_state, component='worker', snapshot=admitted_snapshot or {}, revision=job_id, status='admitted' if admitted_snapshot else 'rejected')
                if admitted_snapshot:
                    delta=delta or {'topic_updates':[]}
                    global_topic=next((t for t in delta['topic_updates'] if t['scope_type']=='global'),None)
                    if global_topic is None:
                        global_topic={'scope_type':'global','scope_id':''};delta['topic_updates'].append(global_topic)
                    global_topic['consultation']=admitted_snapshot
            if (delta and episode
                    and not any(fact["key"] == Slot.BLOCKER for fact in accepted)):
                first_blocker = None
                if episode.open_blockers:
                    first_blocker = episode.open_blockers[0]
                else:
                    for topic in episode.topics:
                        for item in topic.open_items:
                            if item.kind == "blocker":
                                first_blocker = item
                                break
                        if first_blocker:
                            break
                if first_blocker is not None:
                    blocker_text = (first_blocker.text if hasattr(first_blocker, "text")
                                    else str(first_blocker))
                    blocker_quote = (first_blocker.evidence_quote
                                     if hasattr(first_blocker, "evidence_quote")
                                     else blocker_text)
                    try:
                        proposed = ProfileFactCandidate(
                            key=Slot.BLOCKER, value=blocker_text,
                            source_kind="customer", source_turn_id=source_turn_id,
                            evidence_quote=blocker_quote,
                            observed_on=date.fromisoformat(on))
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
            actions_completed, quoted_prices = deterministic_episode_tools(calls, on)
            stored = {"facts": accepted, "delta": delta, "outcome": outcome,
                      "actions_completed": actions_completed,
                      "quoted_prices": quoted_prices}
            envelope = worker_envelope()
            if envelope is not None:
                stored['_decision_diagnostics'] = envelope
            async with repo.transaction() as conn:
                if hasattr(repo, 'distillation_claim_current') and not await repo.distillation_claim_current(conn, job_id, job['attempts']):
                    return True
                await repo.save_distillation_proposals(conn, job_id, stored)
        else:
            accepted = stored.get("facts", [])
            delta = stored.get("delta")
            outcome = stored.get("outcome", "khac")
            actions_completed = stored.get("actions_completed", [])
            quoted_prices = stored.get("quoted_prices", [])
        if diagnostic_active():
            from types import SimpleNamespace
            diagnostic_state = {'customer_id': customer_id, 'request': SimpleNamespace(session_id=session_id, client_msg_id=source_turn_id), 'history': [{'source_turn_id': t['turn_id']} for t in consultation_turns]}
            if job.get('accepted_proposals') is not None:
                from app.mcp_servers.mcp_shared.decision_diagnostics import ingest
                ingest(stored.get('_decision_diagnostics'))
        if projector is None:
            raise RuntimeError("memory_store_unavailable")
        async with repo.transaction() as conn:
            await repo.lock_key(conn, f"erasure:{customer_id}")
            await repo.lock_key(conn, f"langmem:{customer_id}")
            if hasattr(repo, 'distillation_claim_current') and not await repo.distillation_claim_current(conn, job_id, job['attempts']):
                return True
            if await repo.is_erasure_blocked(conn, customer_id):
                await repo.finish_distillation(conn, job_id, "completed", "erasure_blocked")
                return True
            versions = await projector.list_fact_versions(customer_id)
            completed = await completed_revisions(repo, customer_id, versions, conn)
            written = await projector.put_facts(customer_id, session_id, source_turn_id,
                on, accepted, revision=job_id, completed_revisions=completed)
            if delta or accepted or outcome != "khac" or actions_completed or quoted_prices:
                episode_versions = await projector.list_episode_versions(customer_id)
                completed_episodes = await completed_revisions(
                    repo, customer_id, episode_versions, conn)
                all_eps = select_episodes(episode_versions, completed_episodes)
                prior = next((item for item in all_eps
                    if item.get("session_id") == session_id), None)
                prior_open_map = {item["item_id"]: (item["scope_type"], item["scope_id"])
                                  for item in collect_prior_open_items(all_eps, session_id)}
                old = {"topics": decoded(prior["topics"]) if prior else [],
                       "resolved_prior_items": decoded(prior["resolved_prior_items"])
                       if prior else []}
                state = (apply_episode_delta(old, delta, source_turn_id=source_turn_id,
                    customer_text=turn["customer_text"], agent_text=turn["agent_text"],
                    prior_open_items=prior_open_map)
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
                    if (fact.get("source_kind") == "customer" and quote
                            and quote not in " | ".join(fragments)):
                        fragments.append(quote)
                summary = " | ".join(fragments)[:800]
                if not summary:
                    summary = "Chưa có diễn biến riêng được xác minh."
                prior_actions = decoded(prior.get("actions_completed") or []) if prior else []
                prior_quotes = decoded(prior.get("quoted_prices") or []) if prior else []
                merged_actions = list(prior_actions) if isinstance(prior_actions, list) else []
                for act in actions_completed:
                    if act not in merged_actions:
                        merged_actions.append(act)
                merged_quotes = list(prior_quotes) if isinstance(prior_quotes, list) else []
                for q in quoted_prices:
                    if q not in merged_quotes:
                        merged_quotes.append(q)
                await projector.put_episode(customer_id, session_id, {
                    "channel": turn["channel"], "on_date": on,
                    "summary": summary,
                    "outcome": outcome if outcome != "khac" else (
                        prior.get("outcome", "khac") if prior else "khac"),
                    "status": "active", "topics": state["topics"],
                    "resolved_prior_items": state["resolved_prior_items"],
                    "actions_completed": merged_actions,
                    "quoted_prices": merged_quotes},
                    revision=job_id)
            if diagnostic_active():
                diagnostic_emit('worker_projection', state=diagnostic_state, component='worker', revision=job_id, status='projected')
                if delta or accepted or outcome != 'khac' or actions_completed or quoted_prices:
                    for topic in state.get('topics', []):
                        if isinstance(topic, dict) and isinstance(topic.get('consultation'), dict):
                            diagnostic_emit('worker_projection', state=diagnostic_state, component='worker', revision=job_id, status='projected', snapshot=topic['consultation'])
                await save_worker_envelope(repo, conn, job_id, stored)
            await repo.finish_distillation(conn, job_id, "completed", accepted_writes=(
                written if isinstance(written, list) else []))
            if hasattr(projector, "compact_customer") and callable(
                    getattr(projector, "compact_customer", None)):
                try:
                    all_revs = set(completed) | {job_id}
                    if delta or accepted or outcome != "khac" or actions_completed or quoted_prices:
                        all_revs |= set(completed_episodes)
                    await projector.compact_customer(customer_id, all_revs)
                except Exception:
                    pass
    except Exception as exc:
        code = type(exc).__name__[:64]
        logger.warning("LangMem job %d failed: %s", job_id, code)
        status = "failed" if job.get("attempts", 0) >= 5 else "pending"
        async with repo.transaction() as conn:
            if hasattr(repo, 'distillation_claim_current') and not await repo.distillation_claim_current(conn, job_id, job['attempts']):
                return True
            await repo.finish_distillation(conn, job_id, status, code)
    return True


async def run() -> None:
    settings = get_settings()
    model = build_llm(settings.model_copy(update={"llm_model": settings.langmem_model
                                           or settings.llm_model,
                                           "llm_max_tokens": settings.langmem_max_tokens}))
    repo = MemoryRepo(database_url(settings))
    from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
    projector = LangMemProjection(database_url(settings))
    async def extractor(turns, existing, open_items=None):
        return await extract_candidates(model, turns, existing, open_items)
    try:
        while True:
            if not await process_one(repo, extractor, projector):
                await asyncio.sleep(1)
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(run())
