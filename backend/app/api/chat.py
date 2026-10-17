"""Authenticated operator chat endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId, get_ai_http
from app.database.pg_session import get_pg_session
from uuid import UUID

from app.schemas.chat import ChatRequest, ChatResponse, VerifyIdentityRequest
from app.services.chat_service import handle_chat_turn, verify_session_identity

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: CurrentUserId,
               db: AsyncSession = Depends(get_pg_session),
               ai_http=Depends(get_ai_http)) -> ChatResponse:
    return await handle_chat_turn(db, ai_http, user_id, request)


@router.post("/chat/{session_id}/verify-identity")
async def verify_identity(session_id: UUID, payload: VerifyIdentityRequest,
                          user_id: CurrentUserId,
                          db: AsyncSession = Depends(get_pg_session)) -> dict:
    return await verify_session_identity(db, user_id, session_id, payload)
