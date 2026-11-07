import json

import httpx
import pytest

from app.services.voice_speech import SpeechClient, SpeechError


class FragmentedSSE(httpx.AsyncByteStream):
    def __init__(self, events):
        self.payload = "".join(f"event: {name}\r\ndata: {json.dumps(data)}\r\n\r\n"
                               for name, data in events).encode()

    async def __aiter__(self):
        for i in range(0, len(self.payload), 7):
            yield self.payload[i:i + 7]


@pytest.mark.asyncio
async def test_fragmented_tts_and_request():
    def handler(request):
        assert request.url.path == "/v1/speech/vieneu/stream"
        assert json.loads(request.content) == {"text": "Xin chào", "voice": "Trúc Ly"}
        return httpx.Response(200, stream=FragmentedSSE([
            ("start", {"sample_rate": 48000}),
            ("audio_chunk", {"index": 0, "pcm16_base64": "AAA="}),
            ("done", {}),
        ]))
    async with httpx.AsyncClient(base_url="http://speech", transport=httpx.MockTransport(handler)) as http:
        client = SpeechClient("ws://speech/listen", http, "Trúc Ly")
        events = [event async for event in client.stream_tts("Xin chào")]
    assert [event["event"] for event in events] == ["start", "audio_chunk"]


@pytest.mark.asyncio
@pytest.mark.parametrize("last", [None, ("error", {"message": "private upstream detail"})])
async def test_tts_incomplete_or_error_is_not_success(last):
    events = [("audio_chunk", {"pcm16_base64": "AAA="})]
    if last:
        events.append(last)
    async with httpx.AsyncClient(base_url="http://speech", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=FragmentedSSE(events))
    )) as http:
        client = SpeechClient("ws://speech/listen", http, "Trúc Ly")
        with pytest.raises(SpeechError):
            async for _ in client.stream_tts("hello"):
                pass


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", [
    {"event": "ready", "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1}},
    {"event": "error", "code": "service_unavailable", "fatal": True},
])
async def test_listen_handshake_and_cleanup(monkeypatch, ready):
    class Socket:
        closed = False
        async def recv(self):
            return json.dumps(ready)
        async def close(self):
            self.closed = True
    socket = Socket()
    async def connect(url, **kwargs):
        assert url == "ws://speech/listen"
        return socket
    monkeypatch.setattr("app.services.voice_speech.connect", connect)
    async with httpx.AsyncClient() as http:
        client = SpeechClient("ws://speech/listen", http, "Trúc Ly")
        if ready["event"] == "ready":
            assert await client.connect_listen() is socket
        else:
            with pytest.raises(SpeechError):
                await client.connect_listen()
            assert socket.closed
