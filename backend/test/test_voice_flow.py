import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.services.voice_call import VoiceCall


START = {"event": "start", "channel": "zalo_oa",
         "channel_identity": "zalo_dung99", "on": "2026-10-15"}


class Browser:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.closed = False

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, event):
        await self.outgoing.put(event)

    async def close(self, code=1000):
        self.closed = True

    async def command(self, payload):
        await self.incoming.put({"type": "websocket.receive", "text": json.dumps(payload)})

    async def audio(self, payload=b"voice"):
        await self.incoming.put({"type": "websocket.receive", "bytes": payload})

    async def until(self, name, **fields):
        async with asyncio.timeout(2):
            while True:
                event = await self.outgoing.get()
                if event["event"] == name and all(event.get(k) == v for k, v in fields.items()):
                    return event


class ListenSocket:
    def __init__(self):
        self.events = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def send(self, audio):
        self.sent.append(audio)

    async def recv(self):
        event = await self.events.get()
        if isinstance(event, Exception):
            raise event
        return json.dumps(event)

    async def close(self):
        self.closed = True

    async def event(self, name, **fields):
        await self.events.put({"event": name, "session_id": "speech-session",
                               "turn_id": "turn-1", **fields})


class Speech:
    def __init__(self):
        self.sockets = []
        self.tts_error = False
        self.tts_wait = None

    async def connect_listen(self):
        socket = ListenSocket()
        self.sockets.append(socket)
        return socket

    async def stream_tts(self, text):
        assert text == "Xin chào"
        if self.tts_wait:
            await self.tts_wait.wait()
        yield {"event": "start", "sample_rate": 48000, "pause_ms": 200}
        yield {"event": "audio_chunk", "index": 0, "frame": 0,
               "sample_rate": 48000, "pcm16_base64": "AAA="}
        yield {"event": "segment_end", "index": 0}
        if self.tts_error:
            raise RuntimeError("upstream private detail")


async def setup_call(handler=None, prepare_handler=None, memory_handler=None, playback_handler=None):
    browser, speech, requests = Browser(), Speech(), []
    turn_updates = {}
    async def respond(request):
        payload = json.loads(request.content)
        if request.url.path == "/v1/chat/sessions/prepare":
            if prepare_handler:
                return await prepare_handler(request, payload)
            return httpx.Response(200, json={"session_id": payload["session_id"],
                                            "call_brief": None})
        if request.url.path == "/v1/chat/turns/memory":
            return await memory_handler(request, payload)
        if request.url.path == "/v1/chat/turns/playback":
            if playback_handler:
                return await playback_handler(request, payload)
            return httpx.Response(200, json={"session_id": payload["session_id"],
                "client_msg_id": payload["client_msg_id"], "memory_update": {
                    "turn_saved": True, "status": "not_applicable", "changes": []} | turn_updates.get(payload["client_msg_id"], {})})
        requests.append(payload)
        if handler:
            response = await handler(request, payload)
            if response.status_code == 200:
                turn_updates[payload["client_msg_id"]] = response.json().get("memory_update", {})
            return response
        return httpx.Response(200, json={"client_msg_id": payload["client_msg_id"],
            "session_id": payload["session_id"], "agent_text": "Xin chào", "call_brief": {"summary": "old"},
            "needs_handoff": False, "handoff_ticket_id": None})

    http = httpx.AsyncClient(base_url="http://agent", transport=httpx.MockTransport(respond))
    call = VoiceCall(browser, speech, http)
    task = asyncio.create_task(call.run())
    await browser.command(START)
    await browser.until("state", state="listening")
    return browser, speech, requests, http, task


async def end_call(browser, http, task):
    await browser.command({"event": "end"})
    await asyncio.wait_for(task, 2)
    await http.aclose()


@pytest.mark.asyncio
async def test_two_turns_keep_session_and_reject_duplicate_transcripts():
    browser, speech, requests, http, task = await setup_call()
    await browser.audio(b"raw-pcm")
    first = speech.sockets[0]
    await first.event("speech_started")
    started = await browser.until("speech_started")
    await first.event("speech_ended", reason="silence")
    await first.event("transcript_final", text="giá bao nhiêu")
    reply = await browser.until("agent_reply")
    assert reply["call_brief"] == {"summary": "old"}
    assert reply["turn_id"] == started["turn_id"]
    await browser.until("audio_complete")
    assert not first.closed and first.sent == [b"raw-pcm"]
    assert requests[0]["text"] == "giá bao nhiêu"
    assert requests[0]["input_mode"] == "asr_transcript"
    assert requests[0]["on"] == "2026-10-15"
    assert requests[0]["channel_identity"] == "zalo_dung99"
    assert requests[0]["session_id"] == reply["session_id"]
    UUID(requests[0]["client_msg_id"])
    await browser.audio(b"echo")
    await browser.command({"event": "playback_finished", "turn_id": "wrong"})
    await browser.until("error", code="unexpected_playback")
    await first.event("transcript_final", text="late old audio")
    await browser.command({"event": "playback_finished", "turn_id": reply["turn_id"]})
    await browser.until("state", state="listening")
    second = first
    assert len(speech.sockets) == 1
    await browser.command({"event": "playback_finished", "turn_id": reply["turn_id"]})
    await browser.until("error", code="unexpected_playback")
    await second.event("transcript_final", turn_id="turn-2", text="mua nhé")
    reply2 = await browser.until("agent_reply")
    await browser.until("audio_complete")
    assert reply2["turn_id"] != reply["turn_id"]
    assert len(requests) == 2
    assert requests[1]["session_id"] == reply["session_id"]
    assert requests[1]["client_msg_id"] != requests[0]["client_msg_id"]
    assert b"echo" in first.sent
    await end_call(browser, http, task)
    assert browser.closed and all(s.closed for s in speech.sockets)


@pytest.mark.asyncio
async def test_empty_transcript_and_nonfatal_stt_error_do_not_call_agent():
    browser, speech, requests, http, task = await setup_call()
    socket = speech.sockets[0]
    await socket.event("transcript_final", text=" ")
    await socket.event("error", code="transcription_failed", fatal=False)
    await browser.until("error", code="transcription_failed")
    assert requests == []
    await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_stt_error_identifies_failed_turn_for_frontend():
    browser, speech, requests, http, task = await setup_call()
    socket = speech.sockets[0]
    await socket.event("speech_started")
    started = await browser.until("speech_started")
    await socket.event("speech_ended", reason="silence")
    await socket.event("error", code="transcription_failed", fatal=False)
    error = await browser.until("error", code="transcription_failed")
    try:
        assert error["turn_id"] == started["turn_id"]
        assert requests == []
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_tts_error_preserves_text_and_allows_playback_ack():
    browser, speech, requests, http, task = await setup_call()
    speech.tts_error = True
    await speech.sockets[0].event("transcript_final", text="hi")
    reply = await browser.until("agent_reply")
    error = await browser.until("error", stage="tts")
    assert error["fatal"] is False and "private" not in json.dumps(error)
    await browser.command({"event": "playback_finished", "turn_id": reply["turn_id"]})
    await browser.until("state", state="listening")
    assert len(requests) == 1
    await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_harness_failure_closes_without_retry():
    async def fail(request, payload):
        return httpx.Response(500, text="private data")
    browser, speech, requests, http, task = await setup_call(fail)
    await speech.sockets[0].event("transcript_final", text="hi")
    error = await browser.until("error", stage="harness")
    await asyncio.wait_for(task, 2)
    assert error["fatal"] and browser.closed and len(requests) == 1
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["listening", "harness", "tts", "playback"])
async def test_disconnect_cleans_up_at_each_stage(stage):
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def wait_harness(request, payload):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx.Response(200, json={"session_id": payload["session_id"], "agent_text": "Xin chào"})
    browser, speech, requests, http, task = await setup_call(wait_harness if stage == "harness" else None)
    if stage == "tts":
        speech.tts_wait = asyncio.Event()
    if stage != "listening":
        await speech.sockets[0].event("transcript_final", text="hi")
        if stage == "harness":
            await asyncio.wait_for(entered.wait(), 2)
        else:
            await browser.until("state", state="speaking")
            if stage == "playback":
                await browser.until("audio_complete")
    await browser.incoming.put({"type": "websocket.disconnect"})
    release.set()
    await asyncio.wait_for(task, 2)
    assert all(s.closed for s in speech.sockets)
    if stage == "harness":
        assert not cancelled.is_set()
    await http.aclose()


@pytest.mark.asyncio
async def test_early_playback_ack_is_rejected_while_microphone_stays_live():
    browser, speech, requests, http, task = await setup_call()
    speech.tts_wait = asyncio.Event()
    await speech.sockets[0].event("transcript_final", text="hi")
    reply = await browser.until("agent_reply")
    await browser.until("state", state="speaking")
    await browser.command({"event": "playback_finished", "turn_id": reply["turn_id"]})
    await browser.until("error", code="unexpected_playback")
    await browser.audio(b"echo")
    speech.tts_wait.set()
    await browser.until("audio_complete")
    assert len(speech.sockets) == 1 and len(requests) == 1
    await end_call(browser, http, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnect", "fatal", "invalid"])
async def test_speech_failure_is_fatal_and_does_not_call_harness(failure):
    browser, speech, requests, http, task = await setup_call()
    socket = speech.sockets[0]
    if failure == "disconnect":
        await socket.events.put(ConnectionError("private details"))
    elif failure == "fatal":
        await socket.event("error", code="overloaded", fatal=True)
    else:
        await socket.events.put({"event": "transcript_final"})
    error = await browser.until("error")
    await asyncio.wait_for(task, 2)
    assert error["fatal"] and requests == [] and socket.closed
    await http.aclose()


@pytest.mark.asyncio
async def test_start_timeout_closes():
    browser = Browser()
    async with httpx.AsyncClient() as http:
        await asyncio.wait_for(VoiceCall(browser, Speech(), http, start_timeout=0.01).run(), 1)
    error = await browser.until("error")
    assert error["code"] == "start_timeout" and error["fatal"]
    assert browser.closed


@pytest.mark.asyncio
async def test_calls_have_independent_harness_sessions():
    first = await setup_call()
    second = await setup_call()
    for browser, speech, requests, http, task in (first, second):
        await speech.sockets[0].event("transcript_final", text="hi")
    reply1 = await first[0].until("agent_reply")
    reply2 = await second[0].until("agent_reply")
    assert reply1["session_id"] != reply2["session_id"]
    for browser, speech, requests, http, task in (first, second):
        await browser.until("audio_complete")
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_preparation_overlaps_listening_and_first_turn_waits_for_it():
    entered, release = asyncio.Event(), asyncio.Event()
    prepared = []

    async def prepare(request, payload):
        prepared.append(payload)
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"session_id": payload["session_id"],
                                        "call_brief": {"summary": "prepared"}})

    browser, speech, requests, http, task = await setup_call(prepare_handler=prepare)
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert prepared[0]["channel_identity"] == START["channel_identity"]
        assert "text" not in prepared[0] and "client_msg_id" not in prepared[0]
        await speech.sockets[0].event("transcript_final", text="hỏi đơn hàng")
        await browser.until("state", state="processing")
        assert requests == []
        release.set()
        reply = await browser.until("agent_reply")
        assert reply["session_id"] == prepared[0]["session_id"]
        assert requests[0]["session_id"] == prepared[0]["session_id"]
        assert reply["call_brief"] == {"summary": "old"}
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_disconnect_cancels_preparation_without_calling_agent():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def prepare(request, payload):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    browser, speech, requests, http, task = await setup_call(prepare_handler=prepare)
    await asyncio.wait_for(entered.wait(), 2)
    await browser.incoming.put({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)
    assert cancelled.is_set() and requests == []
    assert all(socket.closed for socket in speech.sockets)
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "session"])
async def test_failed_preparation_closes_without_agent_or_private_error(failure):
    async def prepare(request, payload):
        if failure == "http":
            return httpx.Response(503, text="private upstream details")
        return httpx.Response(200, json={"session_id": str(uuid4())})

    browser, speech, requests, http, task = await setup_call(prepare_handler=prepare)
    error = await browser.until("error", stage="harness")
    await asyncio.wait_for(task, 2)
    assert error["fatal"] and "private" not in json.dumps(error)
    assert requests == [] and browser.closed
    await http.aclose()
