"""Transport adapters for continuous speech input and VieNeu SSE output."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
from websockets.asyncio.client import connect

INPUT_AUDIO = {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1}


class SpeechError(Exception):
    pass


class SpeechClient:
    def __init__(self, listen_url: str, http: httpx.AsyncClient, voice: str,
                 connect_timeout: float = 10):
        self.listen_url = listen_url
        self.http = http
        self.voice = voice
        self.connect_timeout = connect_timeout

    async def connect_listen(self):
        socket = await connect(self.listen_url, open_timeout=self.connect_timeout,
                               close_timeout=3, max_size=1024 * 1024)
        try:
            async with asyncio.timeout(self.connect_timeout):
                ready = json.loads(await socket.recv())
            if ready.get("event") != "ready" or ready.get("audio") != INPUT_AUDIO:
                raise SpeechError("Speech input is not ready")
        except BaseException:
            await socket.close()
            raise
        return socket

    async def stream_tts(self, text: str) -> AsyncIterator[dict]:
        async with self.http.stream("POST", "/v1/speech/vieneu/stream",
                                    json={"text": text, "voice": self.voice}) as response:
            response.raise_for_status()
            name, data = "", []
            async for line in response.aiter_lines():
                if line == "":
                    if data:
                        payload = json.loads("\n".join(data))
                        if name == "error":
                            raise SpeechError("TTS generation failed")
                        if name == "done":
                            return
                        yield {"event": name, **payload}
                    name, data = "", []
                elif line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
            raise SpeechError("TTS stream ended without done")
