"""Isolated VieNeu v3 Turbo CPU service on a loopback-only port."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import queue
import threading
import time

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .text_segments import split_tts_text


app = FastAPI(title="TeleSale VieNeu Sidecar", docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger(__name__)
model = None
voices: list[dict[str, str]] = []
model_lock = threading.Lock()
SAMPLE_RATE = 48_000


class Speech(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    voice: str = "Trúc Ly"


class StreamingSpeech(Speech):
    text: str = Field(min_length=1, max_length=8000)


@app.on_event("startup")
def load_model():
    global model, voices
    from vieneu import Vieneu

    model = Vieneu(mode="v3turbo", backend="onnx", precision="fp32")
    voices = [{"label": label, "id": voice_id} for label, voice_id in model.list_preset_voices()]


@app.get("/health")
def health():
    return {"status": "ready" if model else "loading", "engine": "vieneu-v3turbo-onnx-fp32", "voices": len(voices), "frame_streaming": True}


@app.get("/voices")
def list_voices():
    return {"voices": voices}


def validate(body: Speech):
    if model is None:
        raise HTTPException(503, "VieNeu is loading")
    if body.voice not in {item["id"] for item in voices}:
        raise HTTPException(400, "Unknown VieNeu voice")
    chunks = split_tts_text(body.text)
    if not chunks:
        raise HTTPException(400, "Text must contain spoken words")
    return chunks


def wav_synthesis(body: Speech):
    started = time.perf_counter()
    with model_lock:
        audio = np.asarray(model.infer(body.text, voice=body.voice), dtype=np.float32).reshape(-1)
    output = io.BytesIO()
    sf.write(output, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return output.getvalue(), round((time.perf_counter() - started) * 1000), round(len(audio) / SAMPLE_RATE, 3)


@app.post("/synthesize")
async def synthesize(body: Speech):
    validate(body)
    audio, elapsed_ms, duration_s = await asyncio.to_thread(wav_synthesis, body)
    return Response(audio, media_type="audio/wav", headers={"X-TTS-Milliseconds": str(elapsed_ms), "X-Audio-Seconds": str(duration_s), "Cache-Control": "no-store"})


def sse(name: str, data: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


@app.post("/stream")
async def stream(body: StreamingSpeech, request: Request):
    chunks = validate(body)
    output: queue.Queue[tuple[str, dict]] = queue.Queue(maxsize=8)
    stopped = threading.Event()

    def put(name: str, data: dict):
        while not stopped.is_set():
            try:
                output.put((name, data), timeout=0.2)
                return
            except queue.Full:
                continue

    def produce():
        try:
            with model_lock:
                for index, chunk_text in enumerate(chunks):
                    if stopped.is_set():
                        return
                    put("segment_start", {"index": index, "text": chunk_text})
                    frame_index = 0
                    for frame in model.infer_stream(chunk_text, voice=body.voice):
                        if stopped.is_set():
                            return
                        pcm = (np.clip(np.asarray(frame, dtype=np.float32).reshape(-1), -1, 1) * 32767).astype("<i2")
                        if pcm.size:
                            put("audio_chunk", {"index": index, "frame": frame_index, "sample_rate": SAMPLE_RATE, "pcm16_base64": base64.b64encode(pcm.tobytes()).decode("ascii")})
                            frame_index += 1
                    put("segment_end", {"index": index, "frames": frame_index})
            put("done", {"segments_total": len(chunks)})
        except Exception:
            logger.exception("VieNeu inference failed")
            put("error", {"message": "VieNeu generation failed"})

    async def events():
        yield sse("start", {"segments_total": len(chunks), "pause_ms": 200, "sample_rate": SAMPLE_RATE})
        worker = asyncio.create_task(asyncio.to_thread(produce))
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    name, data = await asyncio.to_thread(output.get, True, 0.25)
                except queue.Empty:
                    continue
                yield sse(name, data)
                if name in ("done", "error"):
                    break
        finally:
            stopped.set()
            if worker.done():
                await worker

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})
