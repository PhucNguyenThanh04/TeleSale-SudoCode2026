"""HTTP boundary for the text-turn harness."""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.chat import chat
from app.agent.runtime import HarnessRuntime
from app.configs import get_settings
from app.schemas.agent import ChatRequest, ChatResponse

router = APIRouter(prefix="/v1/chat", tags=["chat"])


async def get_harness(request: Request) -> HarnessRuntime:
    return request.app.state.harness


@router.post("/turns", response_model=ChatResponse)
async def create_text_turn(
    turn: ChatRequest, request: Request, harness: HarnessRuntime = Depends(get_harness)
) -> ChatResponse:
    expected = get_settings().ai_internal_token
    if expected and not hmac.compare_digest(
        request.headers.get("X-AI-Internal-Token", ""), expected.get_secret_value()
    ):
        raise HTTPException(401, "Unauthorized AI caller")
    return await chat(turn, runtime=harness)
