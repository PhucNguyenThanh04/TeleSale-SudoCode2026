"""Continuous PCM input and per-connection turn detection; no agent orchestration."""
from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

SAMPLE_RATE = 16000
MAX_SAMPLES = 30 * SAMPLE_RATE
MIN_SAMPLES = SAMPLE_RATE // 5
MAX_MESSAGE_BYTES = 32000
logger = logging.getLogger(__name__)


class ListenSession:
    def __init__(self, session_id, vad, window):
        self.session_id = session_id
        self.vad = vad
        self.window = window
        self.pending = bytearray()
        self.turn = 0
        self.turn_id = None
        self.active_samples = 0
        self.total_samples = 0
        self.completed = []
        self.carry = np.empty(0, dtype=np.float32)

    def event(self, name, **fields):
        return {'event': name, 'session_id': self.session_id, **fields}

    def _start(self, events):
        if self.turn_id is None:
            self.turn += 1
            self.turn_id = f'turn-{self.turn}'
            events.append(self.event('speech_started', turn_id=self.turn_id))

    def _drain(self, events, forced=False):
        while not self.vad.empty():
            audio = np.asarray(self.vad.front.samples, dtype=np.float32).copy()
            self.vad.pop()
            if len(self.carry):
                audio = np.concatenate((self.carry, audio))
                self.carry = np.empty(0, dtype=np.float32)
            if len(audio) < MIN_SAMPLES:
                # A detected short turn still gets an end event, but no STT job.
                if self.turn_id is not None:
                    events.append(self.event('speech_ended', turn_id=self.turn_id, reason='silence'))
                    self.turn_id = None
                self.active_samples = 0
                continue
            for offset in range(0, len(audio), MAX_SAMPLES):
                piece = audio[offset:offset + MAX_SAMPLES]
                if forced and offset and len(piece) < MIN_SAMPLES:
                    self.carry = piece.copy()
                    break
                self._start(events)
                reason = 'max_duration' if forced or len(piece) == MAX_SAMPLES else 'silence'
                events.append(self.event('speech_ended', turn_id=self.turn_id, reason=reason))
                if len(piece) >= MIN_SAMPLES:
                    self.completed.append((self.turn_id, piece))
                self.turn_id = None
            self.active_samples = 0

    def feed_audio(self, data: bytes) -> list[dict]:
        self.pending.extend(data)
        frame_bytes = self.window * 2
        events = []
        while len(self.pending) >= frame_bytes:
            frame = np.frombuffer(bytes(self.pending[:frame_bytes]), dtype='<i2').astype(np.float32) / 32768
            del self.pending[:frame_bytes]
            self.vad.accept_waveform(frame)
            self.total_samples += self.window
            self._drain(events)
            if self.vad.is_speech_detected():
                self._start(events)
                self.active_samples = self.total_samples - self.vad.current_segment.start + len(self.carry)
                if self.active_samples >= MAX_SAMPLES:
                    self.vad.flush()
                    self._drain(events, forced=True)
        return events

    def take_segments(self):
        result, self.completed = self.completed, []
        return result

    def close(self):
        self.pending.clear()
        self.carry = np.empty(0, dtype=np.float32)
        self.completed.clear()
        self.turn_id = None
        self.active_samples = 0
        self.vad = None


async def serve_listen(websocket: WebSocket, models, inference_lock: asyncio.Lock) -> None:
    await websocket.accept()
    session_id = str(uuid4())
    send_lock = asyncio.Lock()

    async def send(event):
        async with send_lock:
            await websocket.send_json(event)

    async def error(code, fatal, turn_id=None):
        event = {'event': 'error', 'session_id': session_id, 'code': code,
                 'message': code.replace('_', ' '), 'fatal': fatal}
        if turn_id is not None:
            event['turn_id'] = turn_id
        await send(event)

    if models is None:
        await error('service_unavailable', True)
        await websocket.close(code=1013)
        return

    vad, window = models.create_vad()
    session = ListenSession(session_id, vad, window)
    jobs = asyncio.Queue(maxsize=2)
    closed = False

    async def recognize(audio):
        # A cancelled socket must not release the shared lock while the native
        # recognizer thread is still running.
        async with inference_lock:
            task = asyncio.create_task(asyncio.to_thread(models.transcribe_segment, audio))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.gather(task, return_exceptions=True)
                raise

    async def worker():
        while True:
            turn_id, audio = await jobs.get()
            try:
                text = await recognize(audio)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Streaming STT failed for %s', turn_id)
                if not closed:
                    await error('transcription_failed', False, turn_id)
            else:
                if not closed:
                    await send(session.event('transcript_final', turn_id=turn_id, text=text))

    async def receive():
        while True:
            message = await websocket.receive()
            if message['type'] == 'websocket.disconnect':
                return
            audio = message.get('bytes')
            if audio is None:
                await error('invalid_message', True)
                await websocket.close(code=1003)
                return
            if len(audio) > MAX_MESSAGE_BYTES:
                await error('audio_too_large', True)
                await websocket.close(code=1009)
                return
            # VAD runs separately from STT; each session feeds its VAD serially.
            vad_task = asyncio.create_task(asyncio.to_thread(session.feed_audio, audio))
            try:
                events = await asyncio.shield(vad_task)
            except asyncio.CancelledError:
                await asyncio.gather(vad_task, return_exceptions=True)
                raise
            for event in events:
                await send(event)
            for job in session.take_segments():
                try:
                    jobs.put_nowait(job)
                except asyncio.QueueFull:
                    await error('overloaded', True)
                    await websocket.close(code=1013)
                    return

    await send(session.event('ready', audio={'encoding': 'pcm_s16le', 'sample_rate': SAMPLE_RATE, 'channels': 1}))
    worker_task = asyncio.create_task(worker())
    receive_task = asyncio.create_task(receive())
    try:
        done, _ = await asyncio.wait((worker_task, receive_task), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    finally:
        closed = True
        receive_task.cancel()
        worker_task.cancel()
        await asyncio.gather(receive_task, worker_task, return_exceptions=True)
        while not jobs.empty():
            jobs.get_nowait()
        session.close()
