"""Memory polling must not delay audio or mix updates between voice turns."""

import asyncio

import httpx
import pytest

from test_voice_flow import setup_call, end_call


@pytest.mark.asyncio
async def test_memory_completes_for_original_turn_while_next_turn_is_active():
    entered, release = asyncio.Event(), asyncio.Event()
    lookups = []

    async def reply(request, payload):
        return httpx.Response(200, json={"session_id": payload["session_id"],
            "agent_text": "Xin chào", "memory_update": {"turn_saved": True,
                "status": "pending" if payload["text"] == "phòng 25m2" else "not_applicable",
                "changes": []}})

    async def memory(request, payload):
        lookups.append(payload)
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"session_id": payload["session_id"],
            "client_msg_id": payload["client_msg_id"], "memory_update": {
                "turn_saved": True, "status": "completed", "changes": [{
                    "field": "room_area_m2", "action": "added", "value": 25,
                    "source": "customer", "scope_type": "global", "scope_id": ""}]}})

    browser, speech, requests, http, task = await setup_call(reply, memory_handler=memory)
    try:
        await speech.sockets[0].event("transcript_final", text="phòng 25m2")
        first = await browser.until("agent_reply")
        assert first["memory_update"]["status"] == "pending"
        await browser.until("audio_complete")  # No persistence before playback.
        await browser.command({"event": "playback_finished", "turn_id": first["turn_id"]})
        await browser.until("state", state="listening")
        await asyncio.wait_for(entered.wait(), 2)
        await speech.sockets[0].event("transcript_final", turn_id="turn-2", text="cảm ơn")
        second = await browser.until("agent_reply")
        assert second["turn_id"] != first["turn_id"]
        release.set()
        update = await browser.until("memory_update")
        assert update["turn_id"] == first["turn_id"]
        assert update["memory_update"]["changes"][0]["value"] == 25
        assert lookups[0]["client_msg_id"] == requests[0]["client_msg_id"]
        assert "text" not in lookups[0]
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_end_cancels_pending_memory_poll():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def reply(request, payload):
        return httpx.Response(200, json={"session_id": payload["session_id"],
            "agent_text": "Xin chào", "memory_update": {"turn_saved": True,
                "status": "pending", "changes": []}})

    async def memory(request, payload):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    browser, speech, requests, http, task = await setup_call(reply, memory_handler=memory)
    await speech.sockets[0].event("transcript_final", text="phòng 25m2")
    reply_event = await browser.until("agent_reply")
    await browser.until("audio_complete")
    await browser.command({"event": "playback_finished", "turn_id": reply_event["turn_id"]})
    await asyncio.wait_for(entered.wait(), 2)
    await end_call(browser, http, task)
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "wrong_turn", "timeout"])
async def test_memory_lookup_failure_does_not_stop_audio_or_fake_completion(failure, monkeypatch):
    import app.services.voice_call as voice
    real_timeout = asyncio.timeout
    if failure == "timeout":
        monkeypatch.setattr(voice.asyncio, "timeout",
            lambda seconds: real_timeout(0.02 if seconds == 60 else seconds))

    async def reply(request, payload):
        return httpx.Response(200, json={"session_id": payload["session_id"],
            "agent_text": "Xin chào", "memory_update": {"turn_saved": True,
                "status": "pending", "changes": []}})

    async def memory(request, payload):
        if failure == "http":
            return httpx.Response(503, text="private error")
        if failure == "timeout":
            await asyncio.Event().wait()
        return httpx.Response(200, json={"session_id": payload["session_id"],
            "client_msg_id": "wrong", "memory_update": {"status": "completed", "changes": []}})

    browser, speech, requests, http, task = await setup_call(reply, memory_handler=memory)
    try:
        await speech.sockets[0].event("transcript_final", text="phòng 25m2")
        reply_event = await browser.until("agent_reply")
        await browser.until("audio_complete")
        await browser.command({"event": "playback_finished", "turn_id": reply_event["turn_id"]})
        event = await browser.until("memory_update", tracking_finished=True)
        assert event["memory_update"]["status"] == ("pending" if failure == "timeout" else "unavailable")
        assert event["memory_update"]["changes"] == []
        assert event["tracking_finished"] and not browser.closed
        assert "private" not in str(event)
    finally:
        await end_call(browser, http, task)
