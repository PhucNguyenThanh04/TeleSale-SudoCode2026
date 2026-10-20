"""Internal request registration; never exposed as a sales-agent MCP tool."""

import re
from uuid import UUID


_REFERENCE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_SCOPES = frozenset({"ai_memory", "backend_chats", "runtime_orders",
                     "btc_source", "traces", "backups"})


async def request_erasure(repo, *, customer_id: str, request_key: str,
                          verification_ref: str, verified_by: str,
                          scope: list[str]) -> dict:
    """Register a verified, scoped job and erect the customer read/write barrier."""
    if not (isinstance(customer_id, str) and _REFERENCE.fullmatch(customer_id)
            and isinstance(verification_ref, str) and _REFERENCE.fullmatch(verification_ref)
            and isinstance(verified_by, str) and _REFERENCE.fullmatch(verified_by)):
        return {"error": "verification_required"}
    try:
        UUID(request_key)
    except (TypeError, ValueError):
        return {"error": "invalid_request_key"}
    if (not isinstance(scope, list) or not scope
            or any(not isinstance(item, str) or item not in _SCOPES for item in scope)):
        return {"error": "invalid_scope"}
    async with repo.transaction() as conn:
        await repo.lock_key(conn, f"erasure:{customer_id}")
        return await repo.create_erasure_request(
            conn, request_key, customer_id, verification_ref, verified_by,
            list(dict.fromkeys(scope)))
