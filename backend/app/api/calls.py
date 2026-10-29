"""Owner-scoped call list and detail for the web console."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId
from app.database.pg_session import get_pg_session


router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.get("")
async def list_calls(user_id: CurrentUserId, db: AsyncSession = Depends(get_pg_session)) -> dict:
    result = await db.execute(text("""SELECT s.id,s.channel,s.call_date,s.identity_status,s.status,
        s.created_at,s.updated_at,s.customer_id,
        (SELECT count(*) FROM app_runtime.chat_messages m WHERE m.session_id=s.id AND m.role='customer') AS turns,
        (SELECT left(m.content,160) FROM app_runtime.chat_messages m
         WHERE m.session_id=s.id AND m.role='customer' ORDER BY m.id DESC LIMIT 1) AS last_customer_text
        FROM app_runtime.chat_sessions s WHERE s.created_by=:owner
        ORDER BY s.updated_at DESC LIMIT 50"""), {"owner": user_id})
    return {"calls": [{**dict(row._mapping), "id": str(row.id), "created_at": row.created_at.isoformat(),
                       "updated_at": row.updated_at.isoformat(), "call_date": row.call_date.isoformat(),
                       "customer_id": row.customer_id if not user_id.startswith("web-visitor:") else None}
                      for row in result]}


@router.get("/{session_id}")
async def get_call(session_id: UUID, user_id: CurrentUserId,
                   db: AsyncSession = Depends(get_pg_session)) -> dict:
    session = (await db.execute(text("""SELECT id,channel,call_date,identity_status,status,created_at,
        customer_id FROM app_runtime.chat_sessions WHERE id=:id AND created_by=:owner"""),
        {"id": str(session_id), "owner": user_id})).one_or_none()
    if session is None:
        raise HTTPException(404, "Call not found")
    rows = await db.execute(text("""SELECT turn_no,role,content,created_at
        FROM app_runtime.chat_messages WHERE session_id=:id ORDER BY turn_no,id LIMIT 200"""),
        {"id": str(session_id)})
    return {"session_id": str(session_id), "channel": session.channel,
            "call_date": session.call_date.isoformat(), "identity_status": session.identity_status,
            "status": session.status, "created_at": session.created_at.isoformat(),
            "customer_id": session.customer_id if not user_id.startswith("web-visitor:") else None,
            "messages": [{"turn_no": row.turn_no, "role": row.role, "content": row.content,
                          "created_at": row.created_at.isoformat()} for row in rows]}


@router.post("/{session_id}/close")
async def close_call(session_id: UUID, user_id: CurrentUserId,
                     db: AsyncSession = Depends(get_pg_session)) -> dict:
    async with db.begin():
        result = await db.execute(text("""UPDATE app_runtime.chat_sessions SET status='closed',updated_at=now()
            WHERE id=:id AND created_by=:owner AND status='open' RETURNING id"""),
            {"id": str(session_id), "owner": user_id})
        if result.one_or_none() is None:
            raise HTTPException(404, "Open call not found")
    return {"session_id": str(session_id), "status": "closed"}
