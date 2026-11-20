
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import queue
import threading
import time

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from speech.text.tts import prepare_tts_text

from .text_segments import prepare_tts_segments


app = FastAPI(title="TeleSale VieNeu Sidecar", docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger("uvicorn.error")
model = None
voices: list[dict[str, str]] = []
model_lock = threading.Lock()
SAMPLE_RATE = 48_000
tts_provider = None
tts_warmup_runs = 0


class Speech(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    voice: str = "Trúc Ly"


class StreamingSpeech(Speech):
    text: str = Field(min_length=1, max_length=8000)


@app.on_event("startup")
def load_model():
    global model, voices, tts_provider, tts_warmup_runs
    from vieneu import Vieneu

    provider = os.getenv("SPEECH_TTS_PROVIDER", "cuda").strip().lower()
    if provider not in {"cuda", "cpu"}:
        raise ValueError("SPEECH_TTS_PROVIDER must be cuda or cpu")
    if provider == "cuda":
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("VieNeu CUDA requested but PyTorch CUDA is unavailable")
        candidate = Vieneu(mode="v3turbo", backend="pytorch", device="cuda", dtype="auto",
                           max_batch_size=1, max_streams=1)
        if candidate.backend != "pytorch" or candidate.engine.device.type != "cuda":
            raise RuntimeError("VieNeu did not initialize on CUDA")
    else:
        candidate = Vieneu(mode="v3turbo", backend="onnx", device="cpu", precision="fp32")
    presets = [{"label": label, "id": voice_id} for label, voice_id in candidate.list_preset_voices()]
    for index in range(3):
        has_audio = False
        for frame in candidate.infer_stream(prepare_tts_text("Xin chào."), voice="Trúc Ly"):
            has_audio |= np.asarray(frame).size > 0
        if not has_audio:
            raise RuntimeError("VieNeu warmup returned no audio")
        logger.info("VieNeu TTS warmup %d/3 complete (provider=%s)", index + 1, provider)
    model, voices, tts_provider, tts_warmup_runs = candidate, presets, provider, 3


@app.get("/health")
def health():
    return {"status": "ready" if model else "loading", "engine": "vieneu-v3turbo-pytorch" if tts_provider == "cuda" else "vieneu-v3turbo-onnx-fp32", "tts_provider": tts_provider, "tts_warmup_runs": tts_warmup_runs, "voices": len(voices), "frame_streaming": True}


@app.get("/voices")
def list_voices():
    return {"voices": voices}


def validate(body: Speech):
    if model is None:
        raise HTTPException(503, "VieNeu is loading")
    if body.voice not in {item["id"] for item in voices}:
        raise HTTPException(400, "Unknown VieNeu voice")
    chunks = prepare_tts_segments(body.text)
    if not chunks:
        raise HTTPException(400, "Text must contain spoken words")
    return chunks


def wav_synthesis(body: Speech):
    started = time.perf_counter()
    with model_lock:
        audio = np.asarray(model.infer(prepare_tts_text(body.text), voice=body.voice), dtype=np.float32).reshape(-1)
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
