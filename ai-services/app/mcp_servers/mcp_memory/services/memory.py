"""Memory rules: ownership, provenance, masking, supersession and replay."""

import hashlib
import asyncio
import logging
import json
import math
import re
import unicodedata
from datetime import date
from uuid import UUID, uuid4, uuid5

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_memory.services.episode_summary import build_episode_summary
from app.mcp_servers.mcp_memory.services.episode_state import (
    EpisodeCapacityError, apply_episode_delta)
from app.mcp_servers.mcp_memory.repos.langmem_projection import select_facts, select_episodes
from app.constants import Slot
from app.agent.guardrails.checks import safe_tool_result


_FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SCOPE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_PRODUCT_KEYS = {Slot.PRODUCT_ADVISED, Slot.PRICE_QUOTED_VND, Slot.PROMO_CODE,
                 Slot.PROMO_EXPIRY, Slot.IN_STOCK, Slot.VARIANT_SKU}
_ROOM_KEYS = {Slot.ROOM_AREA_M2, Slot.BUDGET_VND}


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


async def _write_fact(repo, conn, customer_id: str, session_id: str, fact: dict,
                      source: str, source_turn_id: UUID | None = None,
                      on_date: date | None = None) -> dict:
    key, op = fact["key"], fact["op"]
    scope_type, scope_id = fact.get("scope_type", "global"), fact.get("scope_id", "")
    await repo.lock_key(conn, f"{customer_id}:{scope_type}:{scope_id}:{key}")
    if hasattr(repo, "active_fact_record"):
        previous_record = (await repo.active_fact_record(conn, customer_id, key)
                           if scope_type == "global" else
                           await repo.active_fact_record(conn, customer_id, key,
                                                         scope_type, scope_id))
        previous = previous_record["fact_id"] if previous_record else None
        old_value = previous_record["value"] if previous_record else None
        if isinstance(old_value, str):
            old_value = json.loads(old_value)
        if previous and op != "delete" and type(old_value) is type(fact.get("value")) and old_value == fact.get("value"):
            return {"key": key, "op": "unchanged", "fact_id": str(previous)}
        if not previous and op == "delete":
            return {"key": key, "op": "unchanged"}
    else:
        previous = (await repo.active_fact(conn, customer_id, key)
                    if scope_type == "global" else
                    await repo.active_fact(conn, customer_id, key, scope_type, scope_id))
    if previous:
        await repo.set_fact_status(conn, previous,
                                   "retracted" if op == "delete" else "superseded")
    actual_op = "delete" if op == "delete" else ("supersede" if previous else "set")
    result = {"customer_id": customer_id, "key": key, "op": actual_op, "source": source}
    if scope_type != "global":
        result.update(scope_type=scope_type, scope_id=scope_id)
    if op != "delete":
        fact_id = uuid4()
        extra = ({"source_turn_id": source_turn_id, "on_date": on_date,
                  "source_kind": fact.get("source_kind"),
                  "source_tool": fact.get("source_tool")}
                 if source_turn_id else {})
        if fact.get("evidence_quote"):
            extra["evidence_quote"] = fact["evidence_quote"]
        if scope_type != "global":
            extra.update(scope_type=scope_type, scope_id=scope_id)
        await repo.insert_fact(conn, fact_id, customer_id, key, fact["value"],
                               source, session_id, previous, **extra)
        result.update(value=fact["value"], fact_id=str(fact_id))
        if fact.get("evidence_quote"):
            result["evidence_quote"] = fact["evidence_quote"]
    return result


async def read(repo, customer_id: str | None, session_id: str,
               max_episodes: int = 5, include_prior: bool = True,
               langmem_mode: str = "off", projector=None) -> dict:
    async with repo.transaction() as conn:
        if customer_id and hasattr(repo, "is_erasure_blocked"):
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                return {"error": "customer_erasure_in_progress"}
        owner = await repo.owner(conn, session_id)
        if owner is not None and owner != customer_id:
            return {"error": "session_owner_mismatch"}
        if customer_id:
            turns = await repo.recent_customer_turns(conn, session_id, customer_id, 12)
        else:
            turns = (await repo.recent_turns(conn, session_id, 12)
                     if hasattr(repo, "recent_turns") else await repo.turns(conn, session_id))
        result = {"history": [{"customer": row["customer_text"], "agent": row["agent_text"]}
                              for row in turns], "profile": {}, "scoped_facts": {"product": {}, "room": {}},
                  "episodes": [], "current_episode": None,
                  "prior_session_ids": [], "owned_order_ids": [],
                  "turn_count": (await repo.turn_count(conn, session_id)
                                 if hasattr(repo, "turn_count") else len(turns))}
        if not customer_id:
            return result
        if langmem_mode == "enabled":
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
                    current = next((item for item in all_episodes
                        if item.get("session_id") == session_id), None)
                    episodes = all_episodes if include_prior else []
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
        facts = await repo.facts(conn, customer_id, session_id, include_prior)
        for row in facts:
            fact = {"key": row["key"],
                "value": json.loads(row["value"]) if isinstance(row["value"], str) else row["value"],
                "source": row["source"], "status": "active",
                "on": row.get("on_date").isoformat() if row.get("on_date") else None,
                "source_kind": row.get("source_kind"), "source_tool": row.get("source_tool"),
                "evidence_quote": row.get("evidence_quote")}
            scope_type, scope_id = row.get("scope_type", "global"), row.get("scope_id", "")
            if scope_type == "global":
                result["profile"][row["key"]] = fact
            elif scope_type in {"product", "room"} and scope_id:
                result["scoped_facts"][scope_type].setdefault(scope_id, {})[row["key"]] = fact
        if hasattr(repo, "episode_state"):
            current = await repo.episode_state(conn, session_id, customer_id)
            if current is not None:
                topics = current["topics"]
                result["current_episode"] = {"summary": current["summary"],
                    "outcome": current["outcome"], "status": current.get("status", "active"),
                    "topics": json.loads(topics) if isinstance(topics, str) else topics,
                    "resolved_prior_items": (json.loads(current["resolved_prior_items"])
                        if isinstance(current.get("resolved_prior_items", []), str)
                        else current.get("resolved_prior_items", []))}
        episodes = await repo.episodes(conn, customer_id, session_id, max_episodes) if include_prior else []
        result["episodes"] = [{"session_id": str(row["session_id"]), "channel": row["channel"],
            "on": row["on_date"].isoformat(), "summary": row["summary"],
            "outcome": row["outcome"], "status": row.get("status", "active"),
            "topics": (json.loads(row["topics"]) if isinstance(row.get("topics", []), str)
                       else row.get("topics", [])),
            "resolved_prior_items": (json.loads(row["resolved_prior_items"])
                if isinstance(row.get("resolved_prior_items", []), str)
                else row.get("resolved_prior_items", []))} for row in episodes]
        if include_prior and hasattr(repo, "prior_session_ids"):
            result["prior_session_ids"] = await repo.prior_session_ids(conn, customer_id, session_id)
        result["owned_order_ids"] = await repo.order_links(conn, customer_id) if include_prior else []
        return result


async def write(repo, action: str, customer_id: str | None, session_id: str,
                data: dict, operation_key: str | None = None,
                summary_turns: int = 3, summary_max_chars: int = 800,
                langmem_mode: str = "off") -> dict:
    if langmem_mode == "enabled" and action in {"fact", "seed_episode"}:
        return {"error": "legacy_memory_action_disabled"}
    episode_delta = {}
    if action == "commit_turn":
        try:
            source_turn_id = UUID(str(data["client_msg_id"]))
            facts = data["facts"]
            date.fromisoformat(data["on"])
        except (KeyError, TypeError, ValueError):
            return {"error": "invalid_turn_data"}
        if (not isinstance(facts, list) or len(facts) > 20
                or any(not isinstance(f, dict) or not _valid_fact(f) for f in facts)
                ):
            return {"error": "invalid_facts_or_identity"}
        source_text = " ".join(unicodedata.normalize("NFC", data["customer_text"])
                               .casefold().split())
        if any(fact.get("evidence_quote") and
               " ".join(unicodedata.normalize("NFC", fact["evidence_quote"])
                        .casefold().split()) not in source_text for fact in facts):
            return {"error": "invalid_facts_or_identity"}
        orders = data.get("orders", [])
        if (not isinstance(orders, list) or len(orders) > 10
                or any(not isinstance(item, str) or not item for item in orders)
                or (orders and not customer_id)):
            return {"error": "invalid_orders_or_identity"}
        episode_delta = data.get("episode_delta", {})
        if not isinstance(episode_delta, dict):
            return {"error": "invalid_episode_delta"}
        if data.get("outcome", "khac") not in {
                "khac", "hen_goi_lai", "chot_don", "tu_choi", "chuyen_may"}:
            return {"error": "invalid_outcome"}
        observations = data.get("tool_observations", [])
        if not isinstance(observations, list) or len(observations) > 20:
            return {"error": "invalid_turn_data"}
        if langmem_mode == "enabled" and (facts or episode_delta):
            return {"error": "legacy_memory_action_disabled"}
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
        if action in {"turn", "commit_turn"}:
            await repo.lock_key(conn, session_id)
            if await repo.owner(conn, session_id) not in (None, customer_id):
                result = {"error": "session_owner_mismatch"}
            else:
                number = await repo.next_turn(conn, session_id)
                customer_text = mask_pii(data["customer_text"])
                agent_text = mask_pii(data["agent_text"])
                on = date.fromisoformat(data["on"])
                if action == "commit_turn" and langmem_mode == "enabled":
                    await repo.insert_turn(conn, session_id, number, customer_id,
                                           data["channel"], on, customer_text, agent_text)
                    for order_id in orders:
                        await repo.link_order(conn, customer_id, order_id)
                    result = {"turn_no": number, "memory_writes": []}
                    if customer_id:
                        await repo.enqueue_distillation(conn, session_id, customer_id,
                            str(source_turn_id), observations, "enabled",
                            data.get("outcome", "khac"))
                    if operation_key:
                        await repo.finish_operation(conn, operation_key, result)
                    return result
                episode_state = {"topics": [], "resolved_prior_items": []}
                episode_warning = None
                if customer_id:
                    prior = (await repo.episode_state(conn, session_id, customer_id)
                             if hasattr(repo, "episode_state") else None)
                    old_topics = prior["topics"] if prior is not None else []
                    old_resolved = prior.get("resolved_prior_items", []) if prior is not None else []
                    if isinstance(old_topics, str):
                        old_topics = json.loads(old_topics)
                    if isinstance(old_resolved, str):
                        old_resolved = json.loads(old_resolved)
                    prior_open = (await repo.prior_open_items(conn, customer_id, session_id)
                                  if hasattr(repo, "prior_open_items") and any(
                                      isinstance(item, dict) and item.get("resolve_items")
                                      for item in episode_delta.get("topic_updates", [])) else {})
                    try:
                        episode_state = apply_episode_delta({"topics": old_topics,
                            "resolved_prior_items": old_resolved}, episode_delta,
                            source_turn_id=(str(source_turn_id) if action == "commit_turn" else
                                            str(uuid5(UUID(session_id), str(number)))),
                            customer_text=customer_text, agent_text=agent_text,
                            prior_open_items=prior_open)
                    except EpisodeCapacityError:
                        episode_state = {"topics": old_topics,
                                         "resolved_prior_items": old_resolved}
                        episode_warning = "capacity_reached"
                    except ValueError:
                        return {"error": "invalid_episode_delta"}
                await repo.insert_turn(conn, session_id, number, customer_id,
                                       data["channel"], on, customer_text, agent_text)
                result = {"turn_no": number}
                if episode_warning:
                    result["episode_warning"] = episode_warning
                if action == "commit_turn":
                    writes = []
                    source = f"{session_id}:{source_turn_id}"
                    for fact in facts:
                        if customer_id:
                            written = await _write_fact(repo, conn, customer_id, session_id,
                                                        fact, source, source_turn_id, on)
                            if written["op"] != "unchanged":
                                writes.append(written)
                    for order_id in orders:
                        await repo.link_order(conn, customer_id, order_id)
                    result["memory_writes"] = writes
                    if (customer_id and langmem_mode in {"shadow", "enabled"}
                            and hasattr(repo, "enqueue_distillation")):
                        await repo.enqueue_distillation(conn, session_id, customer_id,
                            str(source_turn_id), observations, langmem_mode)
                if customer_id:
                    turns = await repo.customer_turns(conn, session_id, customer_id)
                    confirmed = (await repo.session_facts(conn, session_id, customer_id)
                                 if hasattr(repo, "session_facts") else [])
                    summary = build_episode_summary(confirmed, turns, summary_max_chars,
                                                    episode_state=episode_state)
                    if hasattr(repo, "upsert_episode_state"):
                        await repo.upsert_episode_state(conn, session_id, customer_id,
                            data["channel"], on, summary, data.get("outcome", "khac"),
                            episode_state["topics"], episode_state["resolved_prior_items"])
                    else:
                        await repo.upsert_episode(conn, session_id, customer_id, data["channel"],
                                                  on, summary, data.get("outcome", "khac"))
        elif not customer_id:
            result = {"error": "identity_required"}
        elif action == "seed_episode":
            try:
                on = date.fromisoformat(data["on"])
            except (KeyError, TypeError, ValueError):
                result = {"error": "invalid_on"}
            else:
                await repo.seed_episode(conn, session_id, customer_id, data.get("channel", "hotline"),
                                        on, mask_pii(str(data.get("summary", "")))[:summary_max_chars],
                                        data.get("outcome", "khac"))
                result = {"session_id": session_id}
        elif action == "order":
            await repo.link_order(conn, customer_id, data["order_id"])
            result = {"order_id": data["order_id"]}
        elif action == "fact":
            key, op = data["key"], data["op"]
            quote = data.get("evidence_quote")
            if not _valid_scope(data):
                result = {"error": "invalid_scope"}
            elif op not in {"set", "supersede", "delete"}:
                result = {"error": "invalid_op"}
            elif isinstance(data.get("value"), str) and mask_pii(data["value"]) != data["value"]:
                result = {"error": "pii_rejected"}
            elif quote is not None and (not isinstance(quote, str) or not quote.strip()
                                        or len(quote) > 200 or mask_pii(quote) != quote):
                result = {"error": "pii_rejected"}
            elif key == Slot.OBJECTION and data.get("value") == "khac" and not quote:
                result = {"error": "invalid_facts_or_identity"}
            else:
                result = await _write_fact(repo, conn, customer_id, session_id, data,
                                           data["source"])
        else:
            result = {"error": "unknown_memory_action"}
        if operation_key:
            await repo.finish_operation(conn, operation_key, result)
        return result
