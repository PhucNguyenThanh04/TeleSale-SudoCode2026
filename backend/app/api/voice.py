"""Public demo WebSocket: no operator authentication or persistence."""

from fastapi import APIRouter, WebSocket

from app.services.voice_call import VoiceCall

router = APIRouter()


@router.websocket("/api/calls/stream")
async def stream_call(websocket: WebSocket):
    await websocket.accept()
    await VoiceCall(
        websocket, websocket.app.state.voice_speech, websocket.app.state.ai_http,
        start_timeout=websocket.app.state.voice_settings.voice_start_timeout_seconds,
    ).run()
