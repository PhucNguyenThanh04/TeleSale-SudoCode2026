"""Authenticated operator and public BTC call-simulator chat endpoint."""

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId, get_ai_http
from app.database.pg_session import get_pg_session
from app.database.redis_session import get_redis
from uuid import UUID

from app.schemas.chat import ChatRequest, ChatResponse, VerifyIdentityRequest
from app.services.chat_service import handle_chat_turn, verify_session_identity

router = APIRouter(prefix="/api", tags=["chat"])
_DEMO_CHANNELS = {"hotline", "chat_fanpage", "zalo_oa"}
_PHONE = re.compile(r"0[0-9]{9}")


def validate_public_demo_turn(request: ChatRequest) -> None:
    """Validate metadata that the public BTC page simulates receiving from a channel.

    This is suitable only for the public seed-data demo. A production adapter must
    obtain the same metadata from the telephony or messaging platform itself.
    """
    if request.session_id is not None:
        return
    if request.channel not in _DEMO_CHANNELS:
        raise HTTPException(422, "Chế độ mô phỏng cần Hotline, Fanpage hoặc Zalo")
    if request.caller_phone is not None:
        raise HTTPException(422, "Chế độ mô phỏng nhận định danh qua channel_identity")
    identity = request.channel_identity or ""
    if request.channel == "hotline" and _PHONE.fullmatch(identity) is None:
        raise HTTPException(422, "Số hotline phải gồm 10 chữ số và bắt đầu bằng 0")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: CurrentUserId, response: Response,
               db: AsyncSession = Depends(get_pg_session),
               redis: Redis = Depends(get_redis),
               ai_http=Depends(get_ai_http)) -> ChatResponse:
    if user_id.startswith("web-visitor:"):
        key = f"web_chat_rate:{user_id}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)
        if count > 12:
            raise HTTPException(429, "Too many turns; retry in one minute")
        validate_public_demo_turn(request)
    timings: dict[str, float] = {}
    result = await handle_chat_turn(db, ai_http, user_id, request, timings)
    response.headers["Server-Timing"] = ", ".join(
        f"{name};dur={value}" for name, value in timings.items())
    return result


@router.post("/chat/{session_id}/verify-identity")
async def verify_identity(session_id: UUID, payload: VerifyIdentityRequest,
                          user_id: CurrentUserId,
                          db: AsyncSession = Depends(get_pg_session)) -> dict:
    if user_id.startswith("web-visitor:"):
        raise HTTPException(403, "Operator verification is required")
    return await verify_session_identity(db, user_id, session_id, payload)
