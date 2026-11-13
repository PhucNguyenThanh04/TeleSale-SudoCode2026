"""Authenticated demo WebSocket with a server-bound BTC profile."""

from fastapi import APIRouter, Depends, WebSocket

from app.auth import authenticated_socket, current_user
from app.services.voice_call import VoiceCall

router = APIRouter()


@router.websocket("/api/calls/stream")
async def stream_call(websocket: WebSocket, user=Depends(current_user)):
    await websocket.accept()
    call = VoiceCall(
        websocket, websocket.app.state.voice_speech, websocket.app.state.ai_http,
        start_timeout=websocket.app.state.voice_settings.voice_start_timeout_seconds,
        authenticated_user=user,
    )
    await authenticated_socket(websocket, call.run)
