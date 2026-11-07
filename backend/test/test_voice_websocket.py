import json

import httpx
from fastapi.testclient import TestClient

from app.configs import VoiceSettings
from app.voice_main import create_app


def test_entrypoint_starts_without_database_or_login(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    settings = VoiceSettings(_env_file=None)
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/api/calls/stream") as socket:
            socket.send_bytes(b"audio-before-start")
            error = socket.receive_json()
            assert error["code"] == "start_required" and error["fatal"]
            assert socket.receive_json() == {"event": "state", "state": "closed"}


def test_route_runs_a_turn_without_auth_and_preserves_internal_token():
    from test_voice_flow import Speech, START

    settings = VoiceSettings(_env_file=None, ai_internal_token="internal-only")
    class AutoSpeech(Speech):
        async def connect_listen(self):
            socket = await super().connect_listen()
            original_send = socket.send
            async def send(audio):
                await original_send(audio)
                await socket.event("transcript_final", text="Xin chào")
            socket.send = send
            return socket

    requests = []
    def handler(request):
        assert request.headers["X-AI-Internal-Token"] == "internal-only"
        payload = json.loads(request.content)
        if request.url.path == "/v1/chat/sessions/prepare":
            return httpx.Response(200, json={"session_id": payload["session_id"]})
        if request.url.path == "/v1/chat/turns/playback":
            return httpx.Response(200, json={"session_id": payload["session_id"],
                "client_msg_id": payload["client_msg_id"], "memory_update": {
                    "turn_saved": True, "status": "not_applicable", "changes": []}})
        assert request.url.path == "/v1/chat/turns"
        requests.append(payload)
        return httpx.Response(200, json={"session_id": payload["session_id"], "agent_text": "Xin chào"})

    with TestClient(create_app(settings)) as client:
        app = client.app
        app.state.voice_speech = AutoSpeech()
        original = app.state.ai_http
        app.state.ai_http = httpx.AsyncClient(base_url="http://agent", transport=httpx.MockTransport(handler),
            headers={"X-AI-Internal-Token": "internal-only"})
        with client.websocket_connect("/api/calls/stream") as socket:
            socket.send_json(START)
            assert socket.receive_json()["event"] == "ready"
            assert socket.receive_json()["state"] == "listening"
            socket.send_bytes(b"pcm")
            received = []
            while not received or received[-1]["event"] != "audio_complete":
                received.append(socket.receive_json())
            audio = next(e for e in received if e["event"] == "audio")
            assert audio["format"] == {"encoding": "pcm_s16le", "sample_rate": 48000, "channels": 1}
            assert audio["audio_base64"] == "AAA="
            socket.send_json({"event": "end"})
            assert socket.receive_json()["state"] == "closed"
        client.portal.call(app.state.ai_http.aclose)
        app.state.ai_http = original
    assert len(requests) == 1
