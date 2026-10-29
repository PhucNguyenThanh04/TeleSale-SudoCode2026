"""Smoke-test VieNeu SSE and time the first playable frame."""

import json
import sys
import time
import urllib.error
import urllib.request


url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18111/stream"
payload = json.dumps({"text": "Dạ em chào chị. Mẫu máy lọc không khí này rất phù hợp ạ.", "voice": "Trúc Ly"}).encode()
request = urllib.request.Request(url, payload, {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 TeleSaleSpeechLab"}, method="POST")
started = time.perf_counter()
events = []
try:
    response = urllib.request.urlopen(request, timeout=120)
except urllib.error.HTTPError as exc:
    print(json.dumps({"http_status": exc.code, "headers": dict(exc.headers), "body": exc.read().decode("utf-8", errors="replace")[:1000]}))
    raise
with response:
    name = ""
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
            if name == "audio_chunk" and not any(item["event"] == "audio_chunk" for item in events):
                events.append({"event": name, "elapsed_ms": round((time.perf_counter() - started) * 1000), "pcm_bytes": len(__import__("base64").b64decode(data["pcm16_base64"]))})
            elif name in {"start", "segment_start", "segment_end", "done", "error"}:
                events.append({"event": name, "elapsed_ms": round((time.perf_counter() - started) * 1000)})
            if name in {"done", "error"}:
                break
print(json.dumps(events))
assert any(item["event"] == "audio_chunk" for item in events)
assert events[-1]["event"] == "done", events
wav_request = urllib.request.Request(url.removesuffix("/stream") + "/synthesize", payload, {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 TeleSaleSpeechLab"}, method="POST")
with urllib.request.urlopen(wav_request, timeout=120) as wav_response:
    wav = wav_response.read()
    assert wav[:4] == b"RIFF" and len(wav) > 44
print(json.dumps({"wav_bytes": len(wav), "content_type": wav_response.headers.get("Content-Type")}))
if "/v1/speech/" in url:
    base = url.split("/v1/speech/", 1)[0]
    transcript_request = urllib.request.Request(base + "/v1/speech/transcribe", wav, {"Content-Type": "audio/wav", "User-Agent": "Mozilla/5.0 TeleSaleSpeechLab"}, method="POST")
    with urllib.request.urlopen(transcript_request, timeout=120) as transcript_response:
        transcript = json.load(transcript_response)
    assert transcript["text"] and transcript["segments"], transcript
    print(json.dumps({"transcript": transcript["text"], "vad_ms": transcript["debug"]["vad_ms"], "stt_ms": transcript["debug"]["stt_ms"]}, ensure_ascii=True))
    preflight = urllib.request.Request(base + "/v1/speech/vieneu/stream", method="OPTIONS", headers={
        "Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type", "User-Agent": "Mozilla/5.0 TeleSaleSpeechLab",
    })
    with urllib.request.urlopen(preflight, timeout=20) as cors_response:
        assert cors_response.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8000"
    print(json.dumps({"cors_localhost": True}))
    long_payload = json.dumps({"text": "Dạ em chào chị." + " " * 500, "voice": "Trúc Ly"}).encode()
    long_request = urllib.request.Request(url, long_payload, {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 TeleSaleSpeechLab"}, method="POST")
    with urllib.request.urlopen(long_request, timeout=120) as long_response:
        long_stream = long_response.read().decode("utf-8")
    assert "event: audio_chunk" in long_stream and "event: done" in long_stream
    print(json.dumps({"long_agent_reply_stream": True}))
