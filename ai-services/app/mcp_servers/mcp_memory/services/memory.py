"""Memory rules: ownership, provenance, masking, supersession and replay."""

import hashlib
import json
import math
import re
import unicodedata
from datetime import date
from uuid import UUID, uuid4

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.constants import Slot


_FACT_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _valid_fact(fact: dict) -> bool:
    value = fact.get("value")
    return (isinstance(fact.get("key"), str)
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
    await repo.lock_key(conn, customer_id + ":" + key)
    if hasattr(repo, "active_fact_record"):
        previous_record = await repo.active_fact_record(conn, customer_id, key)
        previous = previous_record["fact_id"] if previous_record else None
        old_value = previous_record["value"] if previous_record else None
        if isinstance(old_value, str):
            old_value = json.loads(old_value)
        if previous and op != "delete" and type(old_value) is type(fact.get("value")) and old_value == fact.get("value"):
            return {"key": key, "op": "unchanged", "fact_id": str(previous)}
        if not previous and op == "delete":
            return {"key": key, "op": "unchanged"}
    else:
        previous = await repo.active_fact(conn, customer_id, key)
    if previous:
        await repo.set_fact_status(conn, previous,
                                   "retracted" if op == "delete" else "superseded")
    actual_op = "delete" if op == "delete" else ("supersede" if previous else "set")
    result = {"customer_id": customer_id, "key": key, "op": actual_op, "source": source}
    if op != "delete":
        fact_id = uuid4()
        extra = ({"source_turn_id": source_turn_id, "on_date": on_date,
                  "source_kind": fact.get("source_kind"),
                  "source_tool": fact.get("source_tool")}
                 if source_turn_id else {})
        if fact.get("evidence_quote"):
            extra["evidence_quote"] = fact["evidence_quote"]
        await repo.insert_fact(conn, fact_id, customer_id, key, fact["value"],
                               source, session_id, previous, **extra)
        result.update(value=fact["value"], fact_id=str(fact_id))
        if fact.get("evidence_quote"):
            result["evidence_quote"] = fact["evidence_quote"]
    return result


async def read(repo, customer_id: str | None, session_id: str,
               max_episodes: int = 5, include_prior: bool = True) -> dict:
    async with repo.transaction() as conn:
        owner = await repo.owner(conn, session_id)
        if owner is not None and owner != customer_id:
            return {"error": "session_owner_mismatch"}
        turns = (await repo.recent_turns(conn, session_id, 12)
                 if hasattr(repo, "recent_turns") else await repo.turns(conn, session_id))
        result = {"history": [{"customer": row["customer_text"], "agent": row["agent_text"]}
                              for row in turns], "profile": {}, "episodes": [], "owned_order_ids": [],
                  "turn_count": (await repo.turn_count(conn, session_id)
                                 if hasattr(repo, "turn_count") else len(turns))}
        if not customer_id:
            return result
        facts = await repo.facts(conn, customer_id, session_id, include_prior)
        result["profile"] = {row["key"]: {"key": row["key"],
            "value": json.loads(row["value"]) if isinstance(row["value"], str) else row["value"],
            "source": row["source"], "status": "active",
            "on": row.get("on_date").isoformat() if row.get("on_date") else None,
            "source_kind": row.get("source_kind"), "source_tool": row.get("source_tool"),
            "evidence_quote": row.get("evidence_quote")}
            for row in facts}
        episodes = await repo.episodes(conn, customer_id, session_id, max_episodes) if include_prior else []
        result["episodes"] = [{"session_id": str(row["session_id"]), "channel": row["channel"],
            "on": row["on_date"].isoformat(), "summary": row["summary"],
            "outcome": row["outcome"]} for row in episodes]
        result["owned_order_ids"] = await repo.order_links(conn, customer_id) if include_prior else []
        return result


async def write(repo, action: str, customer_id: str | None, session_id: str,
                data: dict, operation_key: str | None = None,
                summary_turns: int = 3, summary_max_chars: int = 800) -> dict:
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
    digest = hashlib.sha256(json.dumps({"action": action, "customer_id": customer_id,
        "session_id": session_id, "data": data}, sort_keys=True, default=str,
        ensure_ascii=False).encode()).hexdigest()
    async with repo.transaction() as conn:
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
                await repo.insert_turn(conn, session_id, number, customer_id,
                                       data["channel"], on, customer_text, agent_text)
                if customer_id:
                    last = (await repo.turns(conn, session_id))[-summary_turns:]
                    summary = " | ".join(f"Khách: {row['customer_text']} Trợ lý: {row['agent_text']}"
                                         for row in last)[:summary_max_chars]
                    await repo.upsert_episode(conn, session_id, customer_id, data["channel"],
                                              on, summary, data.get("outcome", "khac"))
                result = {"turn_no": number}
                if action == "commit_turn":
                    writes = []
                    source = f"{session_id}:{source_turn_id}"
                    for fact in facts:
                        if customer_id:
                            written = await _write_fact(repo, conn, customer_id, session_id,
                                                        fact, source, source_turn_id, on)
                            if written["op"] != "unchanged":
                                writes.append(written)
                        elif hasattr(repo, "stage_fact"):
                            await repo.stage_fact(conn, session_id, source_turn_id,
                                                  number, fact, on)
                    for order_id in orders:
                        await repo.link_order(conn, customer_id, order_id)
                    result["memory_writes"] = writes
        elif action == "claim_pending" and customer_id:
            await repo.lock_key(conn, session_id)
            owner = await repo.owner(conn, session_id)
            if owner not in (None, customer_id):
                result = {"error": "session_owner_mismatch"}
            else:
                writes = []
                for pending in await repo.pending_facts(conn, session_id):
                    value = pending["value"]
                    fact = {"key": pending["key"],
                            "value": json.loads(value) if isinstance(value, str) else value,
                            "op": pending["op"], "source_kind": pending["source_kind"],
                            "source_tool": pending["source_tool"],
                            "evidence_quote": pending.get("evidence_quote")}
                    source_turn_id = pending["source_turn_id"]
                    written = await _write_fact(repo, conn, customer_id, session_id,
                                                fact, f"{session_id}:{source_turn_id}",
                                                source_turn_id, pending["on_date"])
                    if written["op"] != "unchanged":
                        writes.append(written)
                await repo.clear_pending(conn, session_id)
                await repo.bind_owner(conn, session_id, customer_id)
                result = {"memory_writes": writes}
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
            if op not in {"set", "supersede", "delete"}:
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
