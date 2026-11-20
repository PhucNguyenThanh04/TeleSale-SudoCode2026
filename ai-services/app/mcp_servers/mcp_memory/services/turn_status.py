
import json
import re

from app.constants import SLOT_SPEC_BY_KEY
from app.mcp_servers.mcp_shared.pii import mask_pii


def public_changes(writes: list[dict]) -> list[dict]:
    changes = []
    for write in writes[:100]:
        if not isinstance(write, dict):
            continue
        spec = SLOT_SPEC_BY_KEY.get(write.get("key"))
        action = {"set": "added", "supersede": "updated", "delete": "deleted"}.get(write.get("op"))
        scope = write.get("scope_type", "global")
        scope_id = write.get("scope_id", "")
        if (spec is None or action is None or scope not in {"global", "room", "product"}
                or not isinstance(scope_id, str)
                or scope_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", scope_id)):
            continue
        value = write.get("value") if action != "deleted" else None
        allowed = spec.value_type if isinstance(spec.value_type, tuple) else (spec.value_type,)
        if action != "deleted" and type(value) not in allowed:
            continue
        if isinstance(value, str):
            value = mask_pii(value)[:300]
        changes.append({"field": spec.key, "action": action, "value": value,
                        "source": spec.evidence_source,
                        "scope_type": scope, "scope_id": mask_pii(scope_id)})
    return changes


async def read_turn_status(repo, customer_id: str | None, session_id: str,
                           client_msg_id: str) -> dict:
    async with repo.transaction() as conn:
        if customer_id:
            await repo.lock_key(conn, f"erasure:{customer_id}")
            if await repo.is_erasure_blocked(conn, customer_id):
                return {"error": "customer_erasure_in_progress"}
        owner = await repo.owner(conn, session_id)
        if owner is not None and owner != customer_id:
            return {"error": "session_owner_mismatch"}
        row = await repo.turn_memory_status(conn, session_id, client_msg_id)
        if row is None:
            return {"turn_saved": False, "status": "unavailable", "changes": []}
        if row["customer_id"] != customer_id:
            return {"error": "session_owner_mismatch"}
        status = ("not_applicable" if not customer_id else
                  "pending" if row.get("status") in {"pending", "leased"} else
                  row.get("status") if row.get("status") in {"completed", "failed"} else
                  "unavailable")
        changes = []
        if status == "completed":
            if row.get("error_code"):
                status = "unavailable"
            else:
                writes = row.get("accepted_writes") or []
                if isinstance(writes, str):
                    writes = json.loads(writes)
                if not isinstance(writes, list):
                    return {"error": "invalid_tool_result"}
                changes = public_changes(writes)
        return {"turn_saved": True, "status": status, "changes": changes}
