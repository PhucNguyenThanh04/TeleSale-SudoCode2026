"""Smoke test the published speech API: TTS output is fed to VAD + STT."""

import json
import base64
from urllib.request import Request, build_opener, ProxyHandler


API = "https://sudoapi.ktoxz.id.vn"


def call(path, data=None, content_type=None):
    headers = {"User-Agent": "TeleSaleSpeechHealth/0.1"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(API + path, data=data, headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=45) as response:
        return response.read(), response.headers


if __name__ == "__main__":
    health = json.loads(call("/health")[0])
    assert health["status"] == "ready", health
    wav, headers = call("/v1/speech/synthesize", json.dumps({"text": "Xin chào chị, em tư vấn máy lọc không khí ạ.", "voice": "khanh_vy"}).encode(), "application/json")
    assert wav[:4] == b"RIFF", "TTS did not return WAV"
    result = json.loads(call("/v1/speech/transcribe", wav, "audio/wav")[0])
    assert result["segments"] and result["text"], result
    sequence = json.loads(call("/v1/speech/synthesize/sequence", json.dumps({"text": "Xin chào chị. Em tư vấn AirPure X cho phòng ngủ của chị ạ.", "voice": "khanh_vy"}).encode(), "application/json")[0])
    assert sequence["pause_ms"] == 200, sequence
    assert [part["text"] for part in sequence["segments"]] == ["Xin chào chị.", "Em tư vấn AirPure X cho phòng ngủ của chị ạ."], sequence
    assert all(base64.b64decode(part["audio_base64"])[:4] == b"RIFF" for part in sequence["segments"]), sequence
    print(json.dumps({"health": health, "tts_ms": headers.get("X-TTS-Milliseconds"), "stt": result, "sequence": [{"text": part["text"], "tts_ms": part["tts_ms"], "audio_s": part["audio_s"]} for part in sequence["segments"]], "pause_ms": sequence["pause_ms"]}, ensure_ascii=True))
