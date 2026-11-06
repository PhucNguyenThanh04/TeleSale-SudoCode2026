"""LangMem memory reads and durable turn commits."""

import asyncio
import hashlib
import json
import logging
import re
import math
from datetime import date
from uuid import UUID

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_memory.repos.langmem_projection import select_facts, select_episodes
from app.constants import Slot


_FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SCOPE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ANONYMOUS_TURN_META: dict[tuple[str, str], tuple[list[dict], str]] = {}
_PRODUCT_KEYS = {Slot.PRODUCT_ADVISED, Slot.PRICE_QUOTED_VND, Slot.PROMO_CODE,
                 Slot.PROMO_EXPIRY, Slot.IN_STOCK, Slot.VARIANT_SKU,
                 Slot.SIZE, Slot.COLOR, Slot.PREFERRED_SIZE,
                 Slot.PREFERRED_COLOR, Slot.BLOCKER, Slot.OBJECTION,
                 Slot.PAYMENT, Slot.OWNED_SKU, Slot.ALT_SUGGESTED}
_ROOM_KEYS = {Slot.ROOM_AREA_M2, Slot.BUDGET_VND, Slot.HAS_CHILDREN,
              Slot.PRODUCT_ADVISED}


def _valid_iso_date(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _valid_scope(fact: dict) -> bool:
    scope_type = fact.get("scope_type", "global")
    scope_id = fact.get("scope_id", "")
    if scope_type == "global":
        return scope_id == ""
    if (not isinstance(scope_id, str) or not _SCOPE_ID.fullmatch(scope_id)
            or mask_pii(scope_id) != scope_id):
        return False
    if scope_type == "product":
        return fact.get("key") in _PRODUCT_KEYS
    if scope_type == "room":
        return fact.get("key") in _ROOM_KEYS
    return False


def _valid_fact(fact: dict) -> bool:
    value = fact.get("value")
    return (_valid_scope(fact)
            and isinstance(fact.get("key"), str)
            and bool(_FACT_KEY.fullmatch(fact["key"]))
            and fact.get("op") in {"set", "supersede", "delete"}
            and fact.get("source_kind") in {"customer", "tool"}
            and _valid_iso_date(fact.get("valid_until"))
            and (fact.get("key") != Slot.OBJECTION or fact.get("value") != "khac"
                 or fact.get("evidence_quote"))
            and (fact.get("evidence_quote") is None or
                 (isinstance(fact["evidence_quote"], str)
                  and 0 < len(fact["evidence_quote"]) <= 200
                  and mask_pii(fact["evidence_quote"]) == fact["evidence_quote"]))
            and (fact["source_kind"] != "tool" or
                 (isinstance(fact.get("source_tool"), str)
                  and 1 <= len(fact["source_tool"]) <= 64))
            and (fact["op"] == "delete" or (type(value) in {str, int, float, bool}
                and (not isinstance(value, float) or math.isfinite(value))
                and (not isinstance(value, str) or (value.strip() and len(value) <= 500
                    and mask_pii(value) == value)))))


async def _committed_episode_view(repo, conn, customer_id, session_id, previous, prior_episodes=None):
    """Read-your-committed-turns without waiting for or writing the projection."""
    from app.mcp_servers.mcp_shared.consultation import committed_consultation, admit_consultation
    from app.mcp_servers.mcp_memory.services.episode_state import apply_episode_delta
    if not hasattr(repo, 'recent_session_turns'):
        return previous
    if await repo.owner(conn, session_id) != customer_id:
        return previous
    count = await repo.turn_count(conn, session_id)
    if type(count) is not int:
        return previous
    rows = await repo.recent_session_turns(conn, session_id, customer_id, count, limit=12)
    if not isinstance(rows, list):
        return previous
    turns, calls = [], []
    view = previous
    for row in rows:
        if not isinstance(row, dict) or not row.get('client_msg_id'):
            continue
        tid = str(row['client_msg_id'])
        turn = {'customer_id': customer_id, 'session_id': session_id, 'turn_id': tid,
                'on': str(row['on_date']), 'customer_text': row['customer_text'], 'agent_text': row['agent_text']}
        turns.append(turn)
        observed = row.get('tool_observations') or []
        if isinstance(observed, str):
            observed = json.loads(observed)
        calls.extend({**c, 'source_turn_id': tid, 'customer_id': customer_id, 'session_id': session_id}
                     for c in observed if isinstance(c, dict))
        snapshot = committed_consultation(customer_id, session_id, turns, calls, prior_episodes=prior_episodes)
        payload = snapshot.model_dump(mode='json')
        fresh = {k: ref for k, ref in snapshot.source_refs.items() if ref.source_turn_id == tid}
        if not set(fresh) - {'candidates'}:
            continue
        patch = {k: payload[k] for k in fresh}
        patch['source_refs'] = {k: ref.model_dump(mode='json') for k, ref in fresh.items()}
        admitted = admit_consultation(patch, customer_id=customer_id, session_id=session_id,
                                     committed_turns=turns, tool_calls=calls, prior_episodes=prior_episodes)
        if admitted:
            old = view or {'schema_version': 1, 'customer_id': customer_id, 'session_id': session_id,
                           'on_date': turn['on'], 'status': 'active', 'topics': []}
            view = {**old, **apply_episode_delta(old, {'topic_updates': [
                {'scope_type': 'global', 'scope_id': '', 'consultation': admitted}]},
                source_turn_id=tid, customer_text=turn['customer_text'], agent_text=turn['agent_text'])}
    if view and turns:
        from app.mcp_servers.mcp_shared.presented_offers import derive_presented_offers
        # A bounded read view of existing committed evidence, not another persisted history.
        view = {**view, 'offer_candidates': [o.model_dump(mode='json') for o in
            derive_presented_offers(customer_id=customer_id, session_id=session_id,
                                    committed_turns=turns, tool_calls=calls)]}
    return view


from app.mcp_servers.mcp_shared.decision_diagnostics import memory_boundary, active as diagnostic_active, emit as diagnostic_emit


@memory_boundary("memory_read")
async def read(repo, customer_id: str | None, session_id: str,
               max_episodes: int = 5, include_prior: bool = True,
               projector=None) -> dict:
    async with repo.transaction() as conn:
        if customer_id and hasattr(repo, "is_erasure_blocked"):
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                return {"error": "customer_erasure_in_progress"}
        owner = await repo.owner(conn, session_id)
        if owner is not None and owner != customer_id:
            return {"error": "session_owner_mismatch"}
        turns = (await repo.recent_turns(conn, session_id, 12)
                 if hasattr(repo, "recent_turns") else await repo.turns(conn, session_id))
        result = {"history": [{"customer": row["customer_text"], "agent": row["agent_text"],
                               **({'source_turn_id': str(row['client_msg_id'])} if row.get('client_msg_id') else {})}
                              for row in turns], "profile": {},
                  "scoped_facts": {"product": {}, "room": {}},
                  "episodes": [], "current_episode": None,
                  "prior_session_ids": [], "owned_order_ids": [],
                  "turn_count": (await repo.turn_count(conn, session_id)
                                 if hasattr(repo, "turn_count") else len(turns))}
        if not customer_id:
            return result
        if projector is None:
            return {"error": "memory_store_unavailable"}
        try:
            async with asyncio.timeout(2.0):
                await repo.lock_key(conn, f"langmem:{customer_id}")
                fact_versions = await projector.list_fact_versions(customer_id)
                episode_versions = await projector.list_episode_versions(customer_id)
                revisions = {item.get("revision") for item in
                    [*fact_versions, *episode_versions]
                    if isinstance(item, dict)
                    and type(item.get("revision")) is int
                    and item["revision"] > 0}
                completed = (await repo.completed_job_revisions(
                    conn, customer_id, sorted(revisions))
                    if hasattr(repo, "completed_job_revisions") else revisions)
                facts = select_facts(fact_versions, completed)
                all_episodes = select_episodes(episode_versions, completed)
                if diagnostic_active():
                    from types import SimpleNamespace
                    diagnostic_state = {'customer_id': customer_id, 'history': result['history'],
                        'request': SimpleNamespace(session_id=session_id)}
                    for ep in all_episodes:
                        for topic in ep.get('topics', []) if isinstance(ep, dict) else []:
                            if isinstance(topic, dict) and isinstance(topic.get('consultation'), dict):
                                diagnostic_emit('memory_projection', state=diagnostic_state, component='memory',
                                    snapshot=topic['consultation'], revision=ep.get('revision'))
                current = next((item for item in all_episodes
                    if item.get("session_id") == session_id), None)
                episodes = all_episodes if include_prior else []
                episodes = list(episodes)
                if include_prior:
                    for index, episode in enumerate(episodes[:max_episodes]):
                        prior_id = str(episode.get('session_id', ''))
                        if prior_id and prior_id != session_id:
                            episodes[index] = await _committed_episode_view(
                                repo, conn, customer_id, prior_id, episode)
                current = await _committed_episode_view(repo, conn, customer_id, session_id, current,
                    [ep for ep in episodes if str(ep.get("session_id")) != session_id])
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "LangMem store read failed: %s", type(exc).__name__)
            return {"error": "memory_store_unavailable"}
        for fact in facts:
            if (not isinstance(fact, dict) or fact.get("schema_version") != 1
                    or not include_prior and fact.get("session_id") != session_id):
                continue
            key = fact.get("key")
            scope_type = fact.get("scope_type", "global")
            scope_id = fact.get("scope_id", "")
            if not isinstance(key, str) or not _valid_scope(fact):
                continue
            public = {"key": key, "value": fact.get("value"),
                      "source": fact.get("source"), "status": "active",
                      "on": fact.get("on"), "source_kind": fact.get("source_kind"),
                      "source_tool": fact.get("source_tool"),
                      "evidence_quote": fact.get("evidence_quote")}
            if fact.get("valid_until"):
                public["valid_until"] = fact.get("valid_until")
            if scope_type == "global":
                result["profile"][key] = public
            elif scope_type in {"product", "room"} and scope_id:
                result["scoped_facts"][scope_type].setdefault(scope_id, {})[key] = public
        result["current_episode"] = current
        result["episodes"] = [item for item in episodes
            if isinstance(item, dict) and item.get("schema_version") == 1
            and item.get("session_id") != session_id
            and item.get("status", "active") == "active"][:max_episodes]
        result["prior_session_ids"] = [item["session_id"]
            for item in episodes if isinstance(item, dict)
            and item.get("session_id") != session_id]
        result["owned_order_ids"] = await repo.order_links(conn, customer_id) if include_prior else []
        return result


@memory_boundary("memory_commit")
async def write(repo, action: str, customer_id: str | None, session_id: str,
                data: dict, operation_key: str | None = None) -> dict:
    if action != "commit_turn":
        return {"error": "unknown_memory_action"}
    try:
        source_turn_id = UUID(str(data["client_msg_id"]))
        on = date.fromisoformat(data["on"])
        customer_text = mask_pii(data["customer_text"])
        agent_text = mask_pii(data["agent_text"])
        channel = data["channel"]
    except (KeyError, TypeError, ValueError):
        return {"error": "invalid_turn_data"}
    if not all(isinstance(value, str) for value in (customer_text, agent_text, channel)):
        return {"error": "invalid_turn_data"}
    if "facts" in data or "episode_delta" in data:
        return {"error": "legacy_memory_action_disabled"}
    orders = data.get("orders", [])
    if (not isinstance(orders, list) or len(orders) > 10
            or any(not isinstance(item, str) or not item for item in orders)
            or (orders and not customer_id)):
        return {"error": "invalid_orders_or_identity"}
    observations = data.get("tool_observations", [])
    if not isinstance(observations, list) or len(observations) > 20:
        return {"error": "invalid_turn_data"}
    outcome = data.get("outcome", "khac")
    if outcome not in {"khac", "hen_goi_lai", "chot_don", "tu_choi", "chuyen_may"}:
        return {"error": "invalid_outcome"}
    digest = hashlib.sha256(json.dumps({"action": action, "customer_id": customer_id,
        "session_id": session_id, "data": data}, sort_keys=True, default=str,
        ensure_ascii=False).encode()).hexdigest()
    async with repo.transaction() as conn:
        if customer_id and hasattr(repo, "is_erasure_blocked"):
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                return {"error": "customer_erasure_in_progress"}
        if operation_key:
            previous = await repo.claim_operation(conn, operation_key, digest)
            if previous is not None:
                return previous
        await repo.lock_key(conn, session_id)
        if await repo.owner(conn, session_id) not in (None, customer_id):
            result = {"error": "session_owner_mismatch"}
        else:
            if customer_id and hasattr(repo, "attribute_anonymous_turns"):
                earlier = await repo.attribute_anonymous_turns(conn, session_id, customer_id)
                for prior in earlier:
                    if prior.get("source_turn_id"):
                        prior_id = str(prior["source_turn_id"])
                        prior_obs, prior_outcome = _ANONYMOUS_TURN_META.pop(
                            (session_id, prior_id), ([], "khac"))
                        if prior_outcome != "khac":
                            await repo.enqueue_distillation(conn, session_id, customer_id,
                                prior_id, prior_obs, prior_outcome, turn_no=prior["turn_no"])
                        else:
                            await repo.enqueue_distillation(conn, session_id, customer_id,
                                prior_id, prior_obs, turn_no=prior["turn_no"])
            number = await repo.next_turn(conn, session_id)
            await repo.insert_turn(conn, session_id, number, customer_id,
                                   channel, on, customer_text, agent_text,
                                   str(source_turn_id))
            from app.knowledge.config import enabled
            if enabled() and hasattr(repo, "enqueue_knowledge_event"):
                await repo.enqueue_knowledge_event(conn, data, session_id, customer_id)
            for order_id in orders:
                await repo.link_order(conn, customer_id, order_id)
            result = {"turn_no": number, "memory_writes": []}
            if customer_id:
                await repo.enqueue_distillation(conn, session_id, customer_id,
                    str(source_turn_id), observations, outcome)
                if diagnostic_active():
                    from types import SimpleNamespace
                    diagnostic_emit('memory_enqueue', component='memory', status='enqueued',
                        state={'customer_id': customer_id, 'request': SimpleNamespace(
                            session_id=session_id, client_msg_id=source_turn_id)})
            else:
                if len(_ANONYMOUS_TURN_META) > 500:
                    _ANONYMOUS_TURN_META.clear()
                _ANONYMOUS_TURN_META[(session_id, str(source_turn_id))] = (observations, outcome)
        if operation_key:
            await repo.finish_operation(conn, operation_key, result)
        return result
