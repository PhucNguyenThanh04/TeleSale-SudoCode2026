"""Measure time to the first WAV over the public streaming TTS endpoint."""

import base64
import json
import time
from urllib.request import ProxyHandler, Request, build_opener


URL = "https://sudoapi.ktoxz.id.vn/v1/speech/synthesize/stream"
TEXT = "Xin chào chị. Em đang tư vấn mẫu AirPure X cho phòng ngủ của chị hôm nay ạ. Chị muốn nghe thêm không?"


if __name__ == "__main__":
    request = Request(
        URL,
        data=json.dumps({"text": TEXT, "voice": "khanh_vy"}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "TeleSaleSpeechHealth/0.1"},
    )
    started = time.perf_counter()
    events = []
    with build_opener(ProxyHandler({})).open(request, timeout=45) as response:
        assert response.headers.get_content_type() == "text/event-stream"
        current = {}
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith("event: "):
                current["type"] = line[7:]
            elif line.startswith("data: "):
                current["data"] = json.loads(line[6:])
            elif not line and current:
                current["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
                events.append(current)
                current = {}

    first = next(event for event in events if event["type"] == "segment")
    done = next(event for event in events if event["type"] == "done")
    segments = [event for event in events if event["type"] == "segment"]
    assert len(segments) == 3, [event["type"] for event in events]
    assert [event["data"]["index"] for event in segments] == [0, 1, 2]
    assert all(base64.b64decode(event["data"]["audio_base64"])[:4] == b"RIFF" for event in segments)
    assert first["elapsed_ms"] < done["elapsed_ms"]
    print(json.dumps({"first_audio_ms": first["elapsed_ms"], "all_done_ms": done["elapsed_ms"], "gap_ms": done["elapsed_ms"] - first["elapsed_ms"], "segments": len(segments)}))
