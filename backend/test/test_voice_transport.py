"""Real loopback speech WebSocket, with offline HTTP harness/TTS stubs."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from websockets.asyncio.server import serve

from app.services.voice_call import VoiceCall
from app.services.voice_speech import INPUT_AUDIO, SpeechClient
from test_voice_flow import Browser, START
from test_voice_speech import FragmentedSSE


@pytest.mark.asyncio
async def test_real_speech_websocket_and_tts_adapter_for_two_turns():
    received_audio, requests, speech_connections = [], [], []

    async def listen(socket):
        speech_connections.append(socket)
        await socket.send(json.dumps({"event": "ready", "session_id": str(uuid4()), "audio": INPUT_AUDIO}))
        received_audio.append(await socket.recv())
        # Speech IDs repeat when the backend opens the next listening window.
        for name, fields in [("speech_started", {}), ("speech_ended", {"reason": "silence"}),
                             ("transcript_final", {"text": "Khách nói"})]:
            await socket.send(json.dumps({"event": name, "turn_id": "turn-1", **fields}))
        await socket.wait_closed()

    def harness(request):
        payload = json.loads(request.content)
        if request.url.path == "/v1/chat/sessions/prepare":
            return httpx.Response(200, json={"session_id": payload["session_id"]})
        requests.append(payload)
        return httpx.Response(200, json={"session_id": payload["session_id"], "agent_text": "Trả lời"})

    def tts(request):
        assert json.loads(request.content) == {"text": "Trả lời", "voice": "Trúc Ly"}
        return httpx.Response(200, stream=FragmentedSSE([
            ("start", {"segments_total": 1, "pause_ms": 200, "sample_rate": 48000}),
            ("segment_start", {"index": 0, "text": "Trả lời"}),
            ("audio_chunk", {"index": 0, "frame": 0, "sample_rate": 48000, "pcm16_base64": "AAA="}),
            ("segment_end", {"index": 0, "frames": 1}),
            ("done", {"segments_total": 1}),
        ]))

    async with serve(listen, "127.0.0.1", 0) as server, httpx.AsyncClient(
        base_url="http://agent", transport=httpx.MockTransport(harness)
    ) as ai_http, httpx.AsyncClient(
        base_url="http://speech", transport=httpx.MockTransport(tts)
    ) as speech_http:
        port = server.sockets[0].getsockname()[1]
        speech = SpeechClient(f"ws://127.0.0.1:{port}/v1/speech/listen", speech_http, "Trúc Ly")
        browser = Browser()
        task = asyncio.create_task(VoiceCall(browser, speech, ai_http).run())
        replies = []
        try:
            await browser.command(START)
            for i in range(2):
                await browser.until("state", state="listening")
                await browser.audio(b"\x00\x01" * 320)
                replies.append(await browser.until("agent_reply"))
                audio = await browser.until("audio")
                assert audio["format"]["sample_rate"] == 48000
                assert audio["audio_base64"] == "AAA="
                assert (await browser.until("audio_segment_end"))["pause_ms"] == 200
                await browser.until("audio_complete")
                if i == 0:
                    await browser.command({"event": "playback_finished", "turn_id": replies[-1]["turn_id"]})
            await browser.command({"event": "end"})
            await asyncio.wait_for(task, 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert received_audio == [b"\x00\x01" * 320] * 2
    assert len(speech_connections) == 2
    assert len(requests) == 2
    assert requests[1]["session_id"] == requests[0]["session_id"]
    assert replies[0]["turn_id"] != replies[1]["turn_id"]
