
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
from app.mcp_servers.mcp_shared.memory_retrieval import rank_episodes, resolved_episode_view


_FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SCOPE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
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


async def _committed_episode_view(repo, conn, customer_id, session_id, previous, *, rows_cache=None):
    if not hasattr(repo, 'recent_session_turns') or await repo.owner(conn, session_id) != customer_id:
        return previous
    if rows_cache is not None and session_id in rows_cache:
        rows = rows_cache[session_id]
    else:
        count = await repo.turn_count(conn, session_id)
        if type(count) is not int:
            return previous
        rows = await repo.recent_session_turns(conn, session_id, customer_id, count, limit=None)
    if not isinstance(rows, list):
        return previous
    if rows_cache is not None:
        rows_cache[session_id] = rows
    calls = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('client_msg_id'):
            continue
        observed = row.get('tool_observations') or []
        observed = json.loads(observed) if isinstance(observed, str) else observed
        calls.extend({**call, 'source_turn_id': str(row['client_msg_id'])}
                     for call in observed if isinstance(call, dict))
    view = resolved_episode_view([previous], [])[0] if previous else None
    if not rows:
        return view
    from app.agent.memory.deterministic_tool_facts import deterministic_episode_tools
    from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary
    from app.agent.memory.episode_candidates import outcome_from_tool_calls
    on = str(rows[-1]['on_date'])
    actions, quotes = deterministic_episode_tools(calls, on)
    view = {**(view or {'schema_version': 1, 'customer_id': customer_id,
        'session_id': session_id, 'on_date': on, 'status': 'active', 'topics': []}),
        'actions_completed': actions, 'quoted_prices': quotes,
        'committed_turns': [{'source_turn_id': str(row['client_msg_id']),
            'customer': mask_pii(row['customer_text']), 'agent': mask_pii(row['agent_text'])}
            for row in rows[-12:]], 'turn_count': len(rows)}
    if view:
        view = {**view, 'on': on,
            'summary': view.get('summary') or build_episode_summary([], [], 800, episode_state=view),
            'outcome': view.get('outcome') or outcome_from_tool_calls(calls)}
        if rows[-1].get('channel'):
            view['channel'] = rows[-1]['channel']
    return view


async def _operational_facts(repo, conn, customer_id, sessions, facts, rows_cache, revision_barriers):
    from app.agent.memory.deterministic_tool_facts import verified_tool_candidates
    from app.agent.memory.deterministic_tool_facts import verified_variant_details
    from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
    indexed = {(fact.get('scope_type', 'global'), fact.get('scope_id', ''), fact.get('key')): fact
               for fact in facts if isinstance(fact, dict)}
    for session_id in sessions:
        if await repo.owner(conn, session_id) != customer_id:
            continue
        count = await repo.turn_count(conn, session_id)
        rows = await repo.recent_session_turns(conn, session_id, customer_id, count, limit=None)
        rows_cache[session_id] = rows
        variants = {}
        for row in rows:
            tid = str(row['client_msg_id'])
            on = str(row['on_date'])
            turn = {'customer_id': customer_id, 'session_id': session_id, 'turn_id': tid,
                    'on': on, 'customer_text': row['customer_text'], 'agent_text': row['agent_text']}
            observed = row.get('tool_observations') or []
            observed = json.loads(observed) if isinstance(observed, str) else observed
            calls = [{**call, 'source_turn_id': tid} for call in observed if isinstance(call, dict)]
            for call in calls:
                if call.get('name') == 'catalog.search' and 'error' not in call.get('result', {}):
                    for item in call['result'].get('items', []):
                        for variant in item.get('variants', []):
                            variants[variant['variant_sku']] = {**variant, 'parent_sku': item['sku']}
            candidates = verified_tool_candidates(turn['agent_text'], calls, tid, on)
            accepted, _ = admit_profile_candidates(customer_id, session_id, candidates, [turn], calls)
            for call in calls:
                sku = call.get('args', {}).get('sku')
                accepted.extend(verified_variant_details(call, variants.get(sku), tid))
            for fact in accepted:
                key = (fact.get('scope_type', 'global'), fact.get('scope_id', ''), fact['key'])
                if key[0] == 'room':
                    from app.mcp_servers.mcp_shared.room_context import canonical_room
                    aliases = {scope_id for scope, scope_id, slot in {*indexed, *revision_barriers}
                               if scope == 'room' and slot == key[2]
                               and canonical_room(scope_id) == canonical_room(key[1])}
                    if len(aliases) > 1:
                        continue
                    if aliases:
                        fact = {**fact, 'scope_id': next(iter(aliases))}
                        key = ('room', fact['scope_id'], key[2])
                if (row.get('memory_status') == 'completed' and key[0] == 'global'
                        and type(row.get('job_id')) is int and any(
                            scope != 'global' and slot == fact['key'] and revision >= row['job_id']
                            for (scope, _, slot), revision in revision_barriers.items())):
                    continue
                old = indexed.get(key, {})
                old_revision = old.get('revision')
                barrier = max(revision_barriers.get(key, -1), old_revision if type(old_revision) is int else -1)
                if type(row.get('job_id')) is int and row['job_id'] <= barrier:
                    continue
                indexed[key] = {**fact, 'schema_version': 1, 'session_id': session_id,
                                'source': f'langmem:{session_id}:{tid}', 'on': on,
                                'revision': row['job_id'] if type(row.get('job_id')) is int else 0}
    return list(indexed.values())


from app.mcp_servers.mcp_shared.decision_diagnostics import memory_boundary, active as diagnostic_active, emit as diagnostic_emit


@memory_boundary("memory_read")
async def read(repo, customer_id: str | None, session_id: str,
               max_episodes: int = 5, include_prior: bool = True,
               projector=None, query: str = "") -> dict:
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
                async with asyncio.TaskGroup() as reads:
                    fact_read = reads.create_task(projector.list_fact_versions(customer_id))
                    episode_read = reads.create_task(projector.list_episode_versions(customer_id))
                fact_versions, episode_versions = fact_read.result(), episode_read.result()
                revisions = {item.get("revision") for item in
                    [*fact_versions, *episode_versions]
                    if isinstance(item, dict)
                    and type(item.get("revision")) is int
                    and item["revision"] > 0}
                completed = (await repo.completed_job_revisions(
                    conn, customer_id, sorted(revisions))
                    if hasattr(repo, "completed_job_revisions") else revisions)
                facts = select_facts(fact_versions, completed)
                revision_barriers = {}
                for version in fact_versions:
                    if not isinstance(version, dict) or type(version.get('revision')) is not int:
                        continue
                    revision = version['revision']
                    if revision > 0 and revision not in completed:
                        continue
                    key = (version.get('scope_type', 'global'), version.get('scope_id', ''), version.get('key'))
                    revision_barriers[key] = max(revision_barriers.get(key, -1), revision)
                all_episodes = select_episodes(episode_versions, completed)
                operational_sessions = []
                rows_cache = {}
                if hasattr(repo, 'recent_customer_sessions'):
                    recent = await repo.recent_customer_sessions(conn, customer_id, max_episodes + 1)
                    for session in reversed(recent):
                        sid = str(session['session_id'])
                        if sid == session_id or include_prior:
                            operational_sessions.append(sid)
                        if include_prior and sid != session_id and not any(
                                str(episode.get('session_id')) == sid for episode in all_episodes):
                            all_episodes.append({'schema_version': 1, 'customer_id': customer_id,
                                'session_id': sid, 'on_date': str(session['on_date']),
                                'on': str(session['on_date']), 'channel': session['channel'],
                                'summary': 'Chưa có diễn biến riêng được xác minh.', 'outcome': 'khac',
                                'status': 'active', 'topics': [], 'operational_only': True})
                    if session_id not in operational_sessions:
                        operational_sessions.append(session_id)
                    facts = await _operational_facts(repo, conn, customer_id, operational_sessions, facts, rows_cache, revision_barriers)
                    recency = {str(item['session_id']): len(recent) - index for index, item in enumerate(recent)}
                    all_episodes.sort(key=lambda item: (str(item.get('on', item.get('on_date', ''))),
                        recency.get(str(item.get('session_id')), 0)), reverse=True)
                current = next((item for item in all_episodes
                    if item.get("session_id") == session_id), None)
                prior_episodes = [item for item in all_episodes
                    if item.get('session_id') != session_id
                    and item.get('status', 'active') == 'active'] if include_prior else []
                prior_episodes = resolved_episode_view(prior_episodes, all_episodes)
                episodes = (rank_episodes(prior_episodes, mask_pii(query), max_episodes)
                            if query else prior_episodes[:max_episodes])
                if include_prior:
                    for index, episode in enumerate(episodes):
                        prior_id = str(episode.get('session_id', ''))
                        if prior_id and prior_id != session_id:
                            episodes[index] = await _committed_episode_view(
                                repo, conn, customer_id, prior_id, episode, rows_cache=rows_cache)
                current = await _committed_episode_view(repo, conn, customer_id, session_id, current, rows_cache=rows_cache)
                session_calls = []
                for row in rows_cache.get(session_id, []):
                    observed = row.get('tool_observations') or []
                    observed = json.loads(observed) if isinstance(observed, str) else observed
                    session_calls.extend({**call, 'source_turn_id': str(row['client_msg_id']),
                        'customer_id': customer_id, 'session_id': session_id}
                        for call in observed if isinstance(call, dict))
                result['session_tool_calls'] = session_calls
                episodes = resolved_episode_view(episodes, [*all_episodes, *([current] if current else [])])
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
            for field in ("source_turn_id", "session_id"):
                if isinstance(fact.get(field), str):
                    public[field] = fact[field]
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
            for item in all_episodes if isinstance(item, dict)
            and item.get("session_id") != session_id] if include_prior else []
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
                        prior_obs = prior.get('tool_observations') or []
                        if isinstance(prior_obs, str):
                            prior_obs = json.loads(prior_obs)
                        prior_outcome = prior.get('verified_outcome') or 'khac'
                        if prior_outcome != "khac":
                            await repo.enqueue_distillation(conn, session_id, customer_id,
                                prior_id, prior_obs, prior_outcome, turn_no=prior["turn_no"])
                        else:
                            await repo.enqueue_distillation(conn, session_id, customer_id,
                                prior_id, prior_obs, turn_no=prior["turn_no"])
            number = await repo.next_turn(conn, session_id)
            await repo.insert_turn(conn, session_id, number, customer_id,
                                   channel, on, customer_text, agent_text,
                                   str(source_turn_id), observations, outcome)
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
        if operation_key:
            await repo.finish_operation(conn, operation_key, result)
        return result
