import asyncio
import threading
import unittest
from collections import deque
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from speech.serving.listen import ListenSession, serve_listen


class FakeVad:
    def __init__(self):
        self.frames = []
        self.active = []
        self.finished = deque()
        self.silence = 0

    def accept_waveform(self, frame):
        self.frames.extend(frame.tolist())
        if np.any(frame):
            self.active.extend(frame)
            self.silence = 0
        elif self.active:
            self.silence += len(frame)
            if self.silence >= 11200:
                self.flush()

    def is_speech_detected(self):
        return bool(self.active)

    @property
    def current_segment(self):
        return SimpleNamespace(start=len(self.frames) - len(self.active) - self.silence)

    def flush(self):
        if self.active:
            self.finished.append(SimpleNamespace(samples=np.array(self.active)))
        self.active = []
        self.silence = 0

    def empty(self):
        return not self.finished

    @property
    def front(self):
        return self.finished[0]

    def pop(self):
        self.finished.popleft()


def pcm(count, value=1000):
    return np.full(count, value, dtype='<i2').tobytes()


def session():
    return ListenSession('s', FakeVad(), 320)


class SessionTests(unittest.TestCase):
    def test_chunk_boundaries_preserve_samples(self):
        raw = np.arange(-16000, 16000, dtype='<i2').tobytes()
        for size in (640, 3200, 777):
            current = session()
            for at in range(0, len(raw), size):
                current.feed_audio(raw[at:at + size])
            np.testing.assert_array_equal(current.vad.frames, np.arange(-16000, 16000) / 32768)

    def test_silence_two_turns_and_isolation(self):
        current = session()
        other = session()
        self.assertEqual(current.feed_audio(pcm(16000, 0)), [])
        for turn in ('turn-1', 'turn-2'):
            events = current.feed_audio(pcm(6400))
            events += current.feed_audio(pcm(11200, 0))
            self.assertEqual([e['event'] for e in events], ['speech_started', 'speech_ended'])
            self.assertEqual(events[-1]['turn_id'], turn)
            self.assertEqual(events[-1]['reason'], 'silence')
            jobs = current.take_segments()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(len(jobs[0][1]), 6400)
        self.assertEqual(other.feed_audio(pcm(320, 0)), [])
        self.assertEqual(other.take_segments(), [])

    def test_vad_frame_at_max_boundary_does_not_drop_tail(self):
        current = ListenSession('s', FakeVad(), 512)
        raw = pcm(480000 + 8448) + pcm(16384, 0)
        current.feed_audio(raw)
        self.assertEqual([len(audio) for _, audio in current.take_segments()], [480000, 8448])

    def test_short_segment_has_no_transcript_job(self):
        current = session()
        current.feed_audio(pcm(1600))
        current.feed_audio(pcm(11200, 0))
        self.assertEqual(current.take_segments(), [])

    def test_max_duration_keeps_remaining_samples(self):
        current = session()
        events = current.feed_audio(pcm(480000 + 6400))
        events += current.feed_audio(pcm(11200, 0))
        self.assertEqual([e['reason'] for e in events if e['event'] == 'speech_ended'], ['max_duration', 'silence'])
        self.assertEqual([len(audio) for _, audio in current.take_segments()], [480000, 6400])
        current.close()
        self.assertEqual(current.take_segments(), [])


class FakeModels:
    def __init__(self):
        self.calls = 0

    def create_vad(self):
        return FakeVad(), 320

    def transcribe_segment(self, audio):
        self.calls += 1
        return 'xin chào'


def client_for(models):
    app = FastAPI()
    lock = asyncio.Lock()
    @app.websocket('/listen')
    async def listen(ws: WebSocket):
        await serve_listen(ws, models, lock)
    return TestClient(app)


def send_turn(ws):
    ws.send_bytes(pcm(6400))
    ws.send_bytes(pcm(11200, 0))


class SocketTests(unittest.TestCase):
    def test_multiple_turns_and_empty_transcript(self):
        models = FakeModels()
        with client_for(models) as client, client.websocket_connect('/listen') as ws:
            ready = ws.receive_json()
            self.assertEqual(ready['event'], 'ready')
            for turn in ('turn-1', 'turn-2'):
                send_turn(ws)
                events = [ws.receive_json() for _ in range(3)]
                self.assertEqual([e['event'] for e in events], ['speech_started', 'speech_ended', 'transcript_final'])
                self.assertEqual(events[-1]['turn_id'], turn)
                self.assertEqual(events[-1]['session_id'], ready['session_id'])
                self.assertEqual(events[-1]['text'], 'xin chào')
            models.transcribe_segment = lambda _: ''
            send_turn(ws)
            events = [ws.receive_json() for _ in range(3)]
            self.assertEqual(events[-1]['text'], '')

    def test_invalid_messages_and_unavailable(self):
        for payload, code in [('text', 'invalid_message'), (b'x' * 32001, 'audio_too_large')]:
            with client_for(FakeModels()) as client, client.websocket_connect('/listen') as ws:
                ws.receive_json()
                ws.send_text(payload) if isinstance(payload, str) else ws.send_bytes(payload)
                self.assertEqual(ws.receive_json()['code'], code)
                self.assertEqual(ws.receive()['type'], 'websocket.close')
        with client_for(None) as client, client.websocket_connect('/listen') as ws:
            self.assertEqual(ws.receive_json()['code'], 'service_unavailable')

    def test_stt_error_does_not_stop_next_turn(self):
        models = FakeModels()
        def recognize(_):
            models.calls += 1
            if models.calls == 1:
                raise RuntimeError('fake failure')
            return 'next'
        models.transcribe_segment = recognize
        with client_for(models) as client, client.websocket_connect('/listen') as ws:
            ws.receive_json()
            for expected in ('error', 'transcript_final'):
                send_turn(ws)
                events = [ws.receive_json() for _ in range(3)]
                self.assertEqual(events[-1]['event'], expected)

    def test_receives_while_stt_waits_and_overload(self):
        started, release = threading.Event(), threading.Event()
        models = FakeModels()
        def recognize(_):
            started.set()
            release.wait(5)
            return 'done'
        models.transcribe_segment = recognize
        try:
            with client_for(models) as client, client.websocket_connect('/listen') as ws:
                ws.receive_json()
                send_turn(ws)
                self.assertEqual(ws.receive_json()['event'], 'speech_started')
                self.assertEqual(ws.receive_json()['event'], 'speech_ended')
                self.assertTrue(started.wait(2))
                for _ in range(2):
                    send_turn(ws)
                    self.assertEqual(ws.receive_json()['event'], 'speech_started')
                    self.assertEqual(ws.receive_json()['event'], 'speech_ended')
                send_turn(ws)
                self.assertEqual(ws.receive_json()['event'], 'speech_started')
                self.assertEqual(ws.receive_json()['event'], 'speech_ended')
                self.assertEqual(ws.receive_json()['code'], 'overloaded')
                release.set()
        finally:
            release.set()

    def test_disconnect_discards_unfinished_audio(self):
        models = FakeModels()
        with client_for(models) as client, client.websocket_connect('/listen') as ws:
            ws.receive_json()
            ws.send_bytes(pcm(6400))
            self.assertEqual(ws.receive_json()['event'], 'speech_started')
        self.assertEqual(models.calls, 0)

    def test_registered_route_without_loading_models(self):
        from unittest.mock import patch
        from speech.serving import app as module
        async def offline_startup():
            pass
        with patch.object(module.app.router, 'on_startup', [offline_startup]), patch.object(module, 'models', FakeModels()):
            with TestClient(module.app) as client, client.websocket_connect('/v1/speech/listen') as ws:
                self.assertEqual(ws.receive_json()['event'], 'ready')
                send_turn(ws)
                events = [ws.receive_json() for _ in range(3)]
                self.assertEqual(events[-1]['text'], 'xin chào')


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_keeps_inference_lock_until_thread_finishes(self):
        started, release = threading.Event(), threading.Event()
        models = FakeModels()
        def recognize(_):
            started.set()
            release.wait(5)
            return 'discarded'
        models.transcribe_segment = recognize
        class Socket:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.outgoing = asyncio.Queue()
            async def accept(self):
                pass
            async def receive(self):
                return await self.incoming.get()
            async def send_json(self, event):
                await self.outgoing.put(event)
        ws = Socket()
        lock = asyncio.Lock()
        task = asyncio.create_task(serve_listen(ws, models, lock))
        try:
            await ws.outgoing.get()
            for data in (pcm(6400), pcm(11200, 0)):
                await ws.incoming.put({'type': 'websocket.receive', 'bytes': data})
            await ws.outgoing.get()
            await ws.outgoing.get()
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            await ws.incoming.put({'type': 'websocket.disconnect'})
            for _ in range(10):
                await asyncio.sleep(0)
            self.assertTrue(lock.locked())
            release.set()
            await asyncio.wait_for(task, 2)
            self.assertFalse(lock.locked())
            self.assertTrue(ws.outgoing.empty())
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_disconnect_waits_for_vad_before_clearing_session(self):
        from unittest.mock import patch
        started, release = threading.Event(), threading.Event()
        original = ListenSession.feed_audio
        def slow_feed(current, data):
            started.set()
            release.wait(5)
            return original(current, data)
        class Socket:
            def __init__(self):
                self.messages = asyncio.Queue()
            async def accept(self):
                pass
            async def receive(self):
                return await self.messages.get()
            async def send_json(self, event):
                pass
        ws = Socket()
        with patch.object(ListenSession, 'feed_audio', slow_feed):
            task = asyncio.create_task(serve_listen(ws, FakeModels(), asyncio.Lock()))
            await ws.messages.put({'type': 'websocket.receive', 'bytes': pcm(6400)})
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                task.cancel()
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    async def test_disconnect_discards_jobs_waiting_for_shared_lock(self):
        models = FakeModels()
        class Socket:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.outgoing = asyncio.Queue()
            async def accept(self):
                pass
            async def receive(self):
                return await self.incoming.get()
            async def send_json(self, event):
                await self.outgoing.put(event)
        ws = Socket()
        lock = asyncio.Lock()
        await lock.acquire()
        task = asyncio.create_task(serve_listen(ws, models, lock))
        await ws.outgoing.get()
        for _ in range(2):
            for data in (pcm(6400), pcm(11200, 0)):
                await ws.incoming.put({'type': 'websocket.receive', 'bytes': data})
            self.assertEqual((await ws.outgoing.get())['event'], 'speech_started')
            self.assertEqual((await ws.outgoing.get())['event'], 'speech_ended')
        await ws.incoming.put({'type': 'websocket.disconnect'})
        await asyncio.wait_for(task, 2)
        lock.release()
        self.assertEqual(models.calls, 0)
        self.assertTrue(ws.outgoing.empty())
