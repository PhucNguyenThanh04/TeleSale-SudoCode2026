"""HTTP boundary for the text-turn harness."""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.chat import chat
from app.agent.harness.runtime import AgentHarnessRuntime
from app.configs import get_settings
from app.schemas.agent import (ChatRequest, ChatResponse, PrepareSessionRequest,
                               PrepareSessionResponse, TurnMemoryRequest, TurnMemoryResponse,
                               VoicePlaybackRequest)
from app.schemas.timeline import TimelineRequest, TimelineResponse

router = APIRouter(prefix="/v1/chat", tags=["chat"])


async def get_harness(request: Request) -> AgentHarnessRuntime:
    return request.app.state.harness


@router.post("/sessions/prepare", response_model=PrepareSessionResponse)
async def prepare_session(
    session: PrepareSessionRequest, request: Request,
    harness: AgentHarnessRuntime = Depends(get_harness),
) -> PrepareSessionResponse:
    expected = get_settings().ai_internal_token
    if not expected or not hmac.compare_digest(
        request.headers.get("X-AI-Internal-Token", ""), expected.get_secret_value()
    ):
        raise HTTPException(401, "Unauthorized AI caller")
    try:
        return await harness.prepare_session(session)
    except ValueError:
        raise HTTPException(409, "Session identity conflict") from None
    except RuntimeError:
        raise HTTPException(503, "Session preparation unavailable") from None


@router.post("/turns", response_model=ChatResponse)
async def create_text_turn(
    turn: ChatRequest, request: Request, harness: AgentHarnessRuntime = Depends(get_harness)
) -> ChatResponse:
    expected = get_settings().ai_internal_token
    if ((turn.verified_customer_id or turn.verified_phone) and not expected):
        raise HTTPException(401, "Verified identity requires the internal token")
    if expected and not hmac.compare_digest(
        request.headers.get("X-AI-Internal-Token", ""), expected.get_secret_value()
    ):
        raise HTTPException(401, "Unauthorized AI caller")
    return await chat(turn, runtime=harness)


@router.post('/sessions/timeline', response_model=TimelineResponse)
async def memory_timeline(
    query: TimelineRequest, request: Request,
    harness: AgentHarnessRuntime = Depends(get_harness),
) -> TimelineResponse:
    expected = get_settings().ai_internal_token
    if not expected or not hmac.compare_digest(
        request.headers.get('X-AI-Internal-Token', ''), expected.get_secret_value()
    ):
        raise HTTPException(401, 'Unauthorized AI caller')
    try:
        page = await harness.memory_timeline(query)
    except ValueError:
        raise HTTPException(409, 'Session identity conflict') from None
    except RuntimeError:
        raise HTTPException(503, 'Memory timeline unavailable') from None
    return TimelineResponse(session_id=str(query.session_id), timeline=page)


@router.post("/turns/memory", response_model=TurnMemoryResponse)
async def turn_memory(
    turn: TurnMemoryRequest, request: Request,
    harness: AgentHarnessRuntime = Depends(get_harness),
) -> TurnMemoryResponse:
    expected = get_settings().ai_internal_token
    if not expected or not hmac.compare_digest(
        request.headers.get("X-AI-Internal-Token", ""), expected.get_secret_value()
    ):
        raise HTTPException(401, "Unauthorized AI caller")
    try:
        update = await harness.memory_update(turn)
    except ValueError:
        raise HTTPException(409, "Session identity conflict") from None
    except RuntimeError:
        raise HTTPException(503, "Memory status unavailable") from None
    return TurnMemoryResponse(session_id=turn.session_id, client_msg_id=turn.client_msg_id,
                              memory_update=update)


@router.post("/turns/playback", response_model=TurnMemoryResponse)
async def voice_playback(
    playback: VoicePlaybackRequest, request: Request,
    harness: AgentHarnessRuntime = Depends(get_harness),
) -> TurnMemoryResponse:
    expected = get_settings().ai_internal_token
    if not expected or not hmac.compare_digest(
        request.headers.get("X-AI-Internal-Token", ""), expected.get_secret_value()
    ):
        raise HTTPException(401, "Unauthorized AI caller")
    try:
        update = await harness.record_playback(playback)
    except ValueError:
        raise HTTPException(409, "Playback identity or receipt conflict") from None
    except RuntimeError:
        raise HTTPException(503, "Playback persistence unavailable") from None
    return TurnMemoryResponse(session_id=playback.session_id,
                              client_msg_id=playback.client_msg_id, memory_update=update)
