"""Isolated speech API and demo, served only on a chosen loopback port."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .models import Models, read_wav
from .text_segments import split_tts_text


app = FastAPI(
    title="TeleSale Speech API",
    description="CPU speech service: Silero VAD, Gipformer STT, KorvaTTS and VieNeu. Public demo API; no authentication required.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://telesale.ktoxz.id.vn", "http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-TTS-Milliseconds", "X-Audio-Seconds"],
)
models: Models | None = None
inference_lock = asyncio.Lock()
MAX_AUDIO_BYTES = 10 * 1024 * 1024
requests_by_ip: dict[str, deque[float]] = defaultdict(deque)
logger = logging.getLogger(__name__)
VOICES = {"bao_kim", "gia_bao", "khanh_vy", "hoang_nam", "ngoc_huyen", "huu_dat", "phuong_linh", "quang_huy", "quynh_nhu", "thanh_phong"}
VIENEU_URL = "http://127.0.0.1:18111"


def check_rate(request: Request):
    address = request.headers.get("cf-connecting-ip") or request.client.host
    now = time.monotonic()
    history = requests_by_ip[address]
    while history and now - history[0] > 60:
        history.popleft()
    if len(history) >= 20:
        raise HTTPException(429, "Too many speech requests; retry in one minute")
    history.append(now)
    if len(requests_by_ip) > 10000:
        for key in list(requests_by_ip):
            if not requests_by_ip[key] or now - requests_by_ip[key][-1] > 60:
                del requests_by_ip[key]


class Synthesis(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="Vietnamese text to speak. The sequence endpoint splits at each period or after 20 words.")
    voice: str = Field(default="khanh_vy", description="One of: bao_kim, gia_bao, khanh_vy, hoang_nam, ngoc_huyen, huu_dat, phuong_linh, quang_huy, quynh_nhu, thanh_phong.")


class VieNeuSynthesis(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="Vietnamese text. Streaming splits at each period or after 20 words.")
    voice: str = Field(default="Trúc Ly", description="Preset voice ID from GET /v1/speech/vieneu/voices.")


class VieNeuStream(VieNeuSynthesis):
    text: str = Field(min_length=1, max_length=8000, description="Vietnamese text. Streaming splits at each period or after 20 words.")


class SpeechSegment(BaseModel):
    start_s: float
    end_s: float
    text: str


class TranscriptionDebug(BaseModel):
    vad_ms: int
    stt_ms: int
    audio_s: float
    streaming_stt: bool


class Transcription(BaseModel):
    text: str
    segments: list[SpeechSegment]
    debug: TranscriptionDebug


class AudioSegment(BaseModel):
    index: int
    text: str
    audio_base64: str = Field(description="Base64-encoded PCM WAV for this segment.")
    tts_ms: int
    audio_s: float


class AudioSequence(BaseModel):
    segments: list[AudioSegment]
    pause_ms: int = Field(description="Recommended pause after each segment ends before playing the next one.")


@app.on_event("startup")
async def startup():
    global models
    models = await asyncio.to_thread(Models, Path(os.getenv("SPEECH_MODEL_DIR", "models")))


@app.get("/health", tags=["Status"], summary="Model readiness")
def health():
    return {"status": "ready" if models else "loading", "vad": "silero", "stt": "gipformer1.5-68M-rnnt-int8", "tts": "korvatts", "additional_tts": "vieneu-v3turbo-onnx-fp32 (separate sidecar)", "stt_streaming": False}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).with_name("index.html"), headers={"Cache-Control": "no-store"})


@app.get("/tts.js", include_in_schema=False)
def tts_script():
    return FileResponse(Path(__file__).with_name("tts.js"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.post(
    "/v1/speech/transcribe",
    tags=["Speech"],
    summary="Silero VAD and Gipformer STT for a WAV recording",
    description="Send raw WAV bytes in the request body. Audio may be mono or stereo, 8–96 kHz, at most 30 seconds and 10 MiB. Recognition is offline per VAD segment, not true streaming.",
    response_model=Transcription,
    openapi_extra={"requestBody": {"required": True, "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}},
    responses={400: {"description": "Invalid WAV or duration over 30 seconds"}, 413: {"description": "Body over 10 MiB"}, 415: {"description": "Unsupported Content-Type"}, 429: {"description": "Rate limit reached"}, 503: {"description": "Models still loading"}},
)
async def transcribe(request: Request, response: Response):
    check_rate(request)
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("content-type", "").split(";")[0] not in ("audio/wav", "audio/x-wav", "application/octet-stream"):
        raise HTTPException(415, "Send WAV audio in the request body")
    if int(request.headers.get("content-length", "0")) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio file too large")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio file too large")
    try:
        samples = read_wav(bytes(payload))
    except Exception as exc:
        raise HTTPException(400, f"Invalid WAV audio: {exc}") from exc
    if models is None:
        raise HTTPException(503, "Models are loading")
    async with inference_lock:
        result = await asyncio.to_thread(models.transcribe, samples)
    return result


@app.post(
    "/v1/speech/synthesize",
    tags=["Speech"],
    summary="Synthesize one WAV with KorvaTTS",
    response_class=Response,
    responses={200: {"description": "PCM WAV; X-TTS-Milliseconds and X-Audio-Seconds report generation time and audio length.", "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}, 400: {"description": "Unknown voice"}, 429: {"description": "Rate limit reached"}, 503: {"description": "Models still loading"}},
)
async def synthesize(body: Synthesis, request: Request):
    check_rate(request)
    if models is None:
        raise HTTPException(503, "Models are loading")
    if body.voice not in VOICES:
        raise HTTPException(400, "Unknown voice")
    async with inference_lock:
        audio, debug = await asyncio.to_thread(models.synthesize, body.text, body.voice)
    return Response(audio, media_type="audio/wav", headers={"X-TTS-Milliseconds": str(debug["tts_ms"]), "X-Audio-Seconds": str(debug["audio_s"]), "Cache-Control": "no-store"})


@app.post(
    "/v1/speech/synthesize/sequence",
    tags=["Speech"],
    summary="Split text and synthesize WAV segments",
    description="The complete JSON response is returned after all chunks are synthesized. The browser then plays them in order, waiting 200 ms after each segment ends. This endpoint does not stream or enqueue chunks as they become ready.",
    response_model=AudioSequence,
    responses={400: {"description": "Unknown voice or no spoken words"}, 429: {"description": "Rate limit reached"}, 503: {"description": "Models still loading"}},
)
async def synthesize_sequence(body: Synthesis, request: Request, response: Response):
    check_rate(request)
    if models is None:
        raise HTTPException(503, "Models are loading")
    if body.voice not in VOICES:
        raise HTTPException(400, "Unknown voice")
    chunks = split_tts_text(body.text)
    if not chunks:
        raise HTTPException(400, "Text must contain spoken words")
    response.headers["Cache-Control"] = "no-store"
    segments = []
    async with inference_lock:
        for index, chunk in enumerate(chunks):
            audio, debug = await asyncio.to_thread(models.synthesize, chunk, body.voice)
            segments.append({"index": index, "text": chunk, "audio_base64": base64.b64encode(audio).decode("ascii"), **debug})
    return {"segments": segments, "pause_ms": 200}


def sse_event(name: str, data: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


@app.post(
    "/v1/speech/synthesize/stream",
    tags=["Speech"],
    summary="Stream each TTS sentence as soon as its WAV is ready",
    description="SSE over POST. Events: `start` (segment count and 200 ms pause), `segment` (index, text, WAV base64, timing), `done`, or `error`. The first segment is sent before later segments are synthesized. The client queues WAVs and begins playback as soon as the first one arrives.",
    response_class=StreamingResponse,
    responses={200: {"description": "Server-Sent Events with one WAV per segment.", "content": {"text/event-stream": {"schema": {"type": "string"}}}}, 400: {"description": "Unknown voice or no spoken words"}, 429: {"description": "Rate limit reached"}, 503: {"description": "Models still loading"}},
)
async def synthesize_stream(body: Synthesis, request: Request):
    check_rate(request)
    if models is None:
        raise HTTPException(503, "Models are loading")
    if body.voice not in VOICES:
        raise HTTPException(400, "Unknown voice")
    chunks = split_tts_text(body.text)
    if not chunks:
        raise HTTPException(400, "Text must contain spoken words")

    async def events():
        yield sse_event("start", {"segments_total": len(chunks), "pause_ms": 200})
        try:
            async with inference_lock:
                for index, chunk in enumerate(chunks):
                    if await request.is_disconnected():
                        return
                    audio, debug = await asyncio.to_thread(models.synthesize, chunk, body.voice)
                    yield sse_event("segment", {"index": index, "text": chunk, "audio_base64": base64.b64encode(audio).decode("ascii"), **debug})
            yield sse_event("done", {"segments_total": len(chunks)})
        except Exception:
            logger.exception("TTS stream failed")
            yield sse_event("error", {"message": "TTS generation failed"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get(
    "/v1/speech/vieneu/voices",
    tags=["VieNeu"],
    summary="List VieNeu preset voices",
    responses={503: {"description": "VieNeu sidecar unavailable"}},
)
async def vieneu_voices():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            upstream = await client.get(f"{VIENEU_URL}/voices")
            upstream.raise_for_status()
            return upstream.json()
    except httpx.HTTPError as exc:
        logger.warning("VieNeu voices unavailable: %s", exc)
        raise HTTPException(503, "VieNeu is unavailable") from exc


@app.post(
    "/v1/speech/vieneu/synthesize",
    tags=["VieNeu"],
    summary="Synthesize a complete VieNeu WAV",
    responses={200: {"description": "PCM WAV", "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}, 400: {"description": "Unknown voice"}, 429: {"description": "Rate limit reached"}, 503: {"description": "VieNeu unavailable"}},
)
async def vieneu_synthesize(body: VieNeuSynthesis, request: Request):
    check_rate(request)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            upstream = await client.post(f"{VIENEU_URL}/synthesize", json=body.model_dump())
    except httpx.HTTPError as exc:
        logger.warning("VieNeu synthesis unavailable: %s", exc)
        raise HTTPException(503, "VieNeu is unavailable") from exc
    if upstream.status_code != 200:
        raise HTTPException(upstream.status_code, upstream.json().get("detail", "VieNeu error"))
    return Response(upstream.content, media_type="audio/wav", headers={"Cache-Control": "no-store", "X-TTS-Milliseconds": upstream.headers.get("x-tts-milliseconds", ""), "X-Audio-Seconds": upstream.headers.get("x-audio-seconds", "")})


@app.post(
    "/v1/speech/vieneu/stream",
    tags=["VieNeu"],
    summary="Stream VieNeu PCM frames as they are generated",
    description="POST JSON and read SSE. Events: start, segment_start, audio_chunk (base64 PCM16 mono at 48 kHz), segment_end, done, error. Pause 200 ms between sentences during playback.",
    response_class=StreamingResponse,
    responses={200: {"description": "Server-Sent Events with PCM frames", "content": {"text/event-stream": {"schema": {"type": "string"}}}}, 400: {"description": "Unknown voice"}, 429: {"description": "Rate limit reached"}, 503: {"description": "VieNeu unavailable"}},
)
async def vieneu_stream(body: VieNeuStream, request: Request):
    check_rate(request)
    client = httpx.AsyncClient(timeout=None)
    try:
        upstream_request = client.build_request("POST", f"{VIENEU_URL}/stream", json=body.model_dump())
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("VieNeu stream unavailable: %s", exc)
        raise HTTPException(503, "VieNeu is unavailable") from exc
    if upstream.status_code != 200:
        detail = (await upstream.aread()).decode("utf-8", errors="replace")
        await upstream.aclose()
        await client.aclose()
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise HTTPException(upstream.status_code, detail)

    async def events():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})
