"""Trusted operator chat boundary and backend-to-harness contract."""

import re
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import AITextTurnResponse, ChatRequest, ChatResponse, VerifyIdentityRequest


_PHONE = re.compile(r"(?<!\d)0\d{9}(?!\d)")


def _mask(text_value: str) -> str:
    return _PHONE.sub(lambda match: f"***{match.group()[-4:]}", text_value)


async def handle_chat_turn(db: AsyncSession, ai_http: httpx.AsyncClient,
                           operator_id: str, request: ChatRequest) -> ChatResponse:
    async with db.begin():
        if request.session_id is None:
            session_id = uuid4()
            channel = request.channel
            identity_key = {"hotline": "phone", "chat_fanpage": "fb_id", "zalo_oa": "zalo_id"}.get(channel)
            channel_identity = request.channel_identity or request.caller_phone
            if identity_key:
                # Column names are fixed by the trusted channel enum, never interpolated from user text.
                result = await db.execute(text(f"""SELECT btc_source.customers.customer_id,
                    (suppressed.customer_id IS NOT NULL) AS suppressed
                    FROM btc_source.customers
                    LEFT JOIN app_runtime.erasure_suppressions AS suppressed
                      ON suppressed.customer_id=btc_source.customers.customer_id
                    WHERE {identity_key}=:identity"""), {"identity": channel_identity})
            else:
                result = []
            matches = list(result)
            if matches and all(getattr(row, "suppressed", False) for row in matches):
                raise HTTPException(410, "Customer record unavailable")
            customers = [row.customer_id for row in matches]
            identity_status = "ambiguous" if len(customers) > 1 else ("known" if customers else "unknown")
            customer_id = customers[0] if len(customers) == 1 else None
            call_date = request.call_date
            caller_phone = request.caller_phone or (channel_identity if channel == "hotline" else None)
            await db.execute(text("""INSERT INTO app_runtime.chat_sessions
                (id,created_by,caller_phone,channel_identity,channel,call_date,customer_id,identity_status)
                VALUES (:id,:operator_id,:caller_phone,:channel_identity,:channel,:call_date,:customer_id,:identity_status)"""),
                {"id": str(session_id), "operator_id": operator_id, "caller_phone": caller_phone,
                 "channel_identity": channel_identity,
                 "channel": channel, "call_date": call_date, "customer_id": customer_id,
                 "identity_status": identity_status})
        else:
            session_id = request.session_id
            result = await db.execute(text("""SELECT id, created_by, caller_phone, channel_identity, channel, call_date,
                customer_id, identity_status, status FROM app_runtime.chat_sessions WHERE id=:id
                FOR UPDATE"""), {"id": str(session_id)})
            row = result.one_or_none()
            if row is None or row.created_by != operator_id or row.status != "open":
                raise HTTPException(404, "Session not found")
            caller_phone, channel, call_date = row.caller_phone, row.channel, row.call_date
            channel_identity = row.channel_identity or caller_phone
            customer_id, identity_status = row.customer_id, row.identity_status
        next_turn = await db.execute(text("""SELECT COALESCE(MAX(turn_no),0)+1
            FROM app_runtime.chat_messages WHERE session_id=:id"""), {"id": str(session_id)})
        turn_no = next_turn.scalar_one()
        safe_text = _mask(request.text)
        client_msg_id = request.client_msg_id or uuid4()
        try:
            ai_response = await ai_http.post("/v1/chat/turns", json={
                "client_msg_id": str(client_msg_id), "session_id": str(session_id),
                "channel": channel, "channel_identity": channel_identity,
                "on": call_date.isoformat(), "text": safe_text,
                "input_mode": request.customer_input_mode,
                "verified_customer_id": customer_id if identity_status == "known" else None,
                "verified_phone": caller_phone if identity_status == "known" else None,
            })
            ai_response.raise_for_status()
            parsed = AITextTurnResponse.model_validate(ai_response.json())
            if parsed.session_id != session_id or parsed.client_msg_id != client_msg_id:
                raise ValueError("AI response identifier mismatch")
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "AI service unavailable") from exc
        agent_text = parsed.agent_text
        needs_handoff, handoff_ticket_id = parsed.needs_handoff, parsed.handoff_ticket_id
        call_brief = parsed.call_brief
        for role, content in (("customer", safe_text), ("agent", _mask(agent_text))):
            await db.execute(text("""INSERT INTO app_runtime.chat_messages
                (session_id,turn_no,role,content) VALUES (:session_id,:turn_no,:role,:content)"""),
                {"session_id": str(session_id), "turn_no": turn_no, "role": role,
                 "content": content})
        await db.execute(text("UPDATE app_runtime.chat_sessions SET updated_at=now() WHERE id=:id"),
                         {"id": str(session_id)})
        return ChatResponse(client_msg_id=client_msg_id, session_id=session_id, agent_text=agent_text,
                            identity_status=identity_status, needs_handoff=needs_handoff,
                            handoff_ticket_id=handoff_ticket_id, call_brief=call_brief)


async def verify_session_identity(db: AsyncSession, operator_id: str, session_id: UUID,
                                  payload: VerifyIdentityRequest) -> dict:
    """Bind an open session after the operator has verified the caller separately."""
    async with db.begin():
        result = await db.execute(text("""SELECT created_by,customer_id,status FROM
            app_runtime.chat_sessions WHERE id=:id FOR UPDATE"""), {"id": str(session_id)})
        row = result.one_or_none()
        if row is None or row.created_by != operator_id or row.status != "open":
            raise HTTPException(404, "Session not found")
        if row.customer_id and row.customer_id != payload.customer_id:
            raise HTTPException(409, "Session is bound to another customer")
        matches = await db.execute(text("""SELECT customer_id FROM btc_source.customers
            WHERE customer_id=:customer_id AND phone=:phone
            AND NOT EXISTS (SELECT 1 FROM app_runtime.erasure_suppressions
                WHERE erasure_suppressions.customer_id=:customer_id)"""),
            {"customer_id": payload.customer_id, "phone": payload.phone})
        if matches.one_or_none() is None:
            raise HTTPException(422, "Customer and phone do not match CRM")
        await db.execute(text("""UPDATE app_runtime.chat_sessions
            SET customer_id=:customer_id, caller_phone=:phone, identity_status='known',
                updated_at=now() WHERE id=:id"""),
            {"id": str(session_id), "customer_id": payload.customer_id,
             "phone": payload.phone})
    return {"session_id": session_id, "identity_status": "known"}
