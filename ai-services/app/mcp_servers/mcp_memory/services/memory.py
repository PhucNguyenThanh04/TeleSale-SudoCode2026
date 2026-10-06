"""Memory rules: ownership, provenance, masking, supersession and replay."""

import hashlib
import json
from datetime import date
from uuid import uuid4

from app.mcp_servers.mcp_shared.pii import mask_pii


async def read(repo, customer_id: str | None, session_id: str,
               max_episodes: int = 5, include_prior: bool = True) -> dict:
    async with repo.transaction() as conn:
        owner = await repo.owner(conn, session_id)
        if owner is not None and owner != customer_id:
            return {"error": "session_owner_mismatch"}
        turns = await repo.turns(conn, session_id)
        result = {"history": [{"customer": row["customer_text"], "agent": row["agent_text"]}
                              for row in turns], "profile": {}, "episodes": [], "owned_order_ids": []}
        if not customer_id:
            return result
        facts = await repo.facts(conn, customer_id, session_id, include_prior)
        result["profile"] = {row["key"]: {"key": row["key"],
            "value": json.loads(row["value"]) if isinstance(row["value"], str) else row["value"],
            "source": row["source"], "status": "active"} for row in facts}
        episodes = await repo.episodes(conn, customer_id, session_id, max_episodes) if include_prior else []
        result["episodes"] = [{"session_id": str(row["session_id"]), "channel": row["channel"],
            "on": row["on_date"].isoformat(), "summary": row["summary"],
            "outcome": row["outcome"]} for row in episodes]
        result["owned_order_ids"] = await repo.order_links(conn, customer_id) if include_prior else []
        return result


async def write(repo, action: str, customer_id: str | None, session_id: str,
                data: dict, operation_key: str | None = None,
                summary_turns: int = 3, summary_max_chars: int = 800) -> dict:
    digest = hashlib.sha256(json.dumps({"action": action, "customer_id": customer_id,
        "session_id": session_id, "data": data}, sort_keys=True, default=str,
        ensure_ascii=False).encode()).hexdigest()
    async with repo.transaction() as conn:
        if operation_key:
            previous = await repo.claim_operation(conn, operation_key, digest)
            if previous is not None:
                return previous
        if action == "turn":
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
            if op not in {"set", "supersede", "delete"}:
                result = {"error": "invalid_op"}
            elif isinstance(data.get("value"), str) and mask_pii(data["value"]) != data["value"]:
                result = {"error": "pii_rejected"}
            else:
                await repo.lock_key(conn, customer_id + ":" + key)
                previous = await repo.active_fact(conn, customer_id, key)
                if previous:
                    await repo.set_fact_status(conn, previous,
                                               "retracted" if op == "delete" else "superseded")
                if op == "delete":
                    result = {"customer_id": customer_id, "key": key,
                              "op": op, "source": data["source"]}
                else:
                    fact_id = uuid4()
                    await repo.insert_fact(conn, fact_id, customer_id, key, data["value"],
                                           data["source"], session_id, previous)
                    result = {"customer_id": customer_id, "key": key, "value": data["value"],
                              "op": op, "source": data["source"], "fact_id": str(fact_id)}
        else:
            result = {"error": "unknown_memory_action"}
        if operation_key:
            await repo.finish_operation(conn, operation_key, result)
        return result
