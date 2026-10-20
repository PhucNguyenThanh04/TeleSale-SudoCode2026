"""Internal backend chat erasure for a separately verified customer request."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def erase_verified_customer_chats(db: AsyncSession, customer_id: str,
                                        request_key: str) -> dict:
    """Suppress the verified customer and delete only sessions owned by that ID."""
    if not isinstance(customer_id, str) or not customer_id.strip():
        return {"error": "customer_id_required"}
    try:
        UUID(request_key)
    except (TypeError, ValueError):
        return {"error": "invalid_request_key"}
    async with db.begin():
        await db.execute(text("""INSERT INTO app_runtime.erasure_suppressions
            (customer_id,request_key) VALUES(:customer_id,:request_key)
            ON CONFLICT(customer_id) DO NOTHING"""),
            {"customer_id": customer_id, "request_key": request_key})
        row = (await db.execute(text("""SELECT request_key
            FROM app_runtime.erasure_suppressions WHERE customer_id=:customer_id
            FOR UPDATE"""), {"customer_id": customer_id})).one()
        if str(row.request_key) != request_key:
            return {"error": "request_key_conflict"}
        deleted = (await db.execute(text("""DELETE FROM app_runtime.chat_sessions
            WHERE customer_id=:customer_id AND identity_status='known'
            RETURNING id"""), {"customer_id": customer_id})).all()
    return {"status": "completed", "deleted_sessions": len(deleted)}
