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
        await asyncio.wait_for(entered.wait(), 2)
        await browser.until("audio_complete")  # Worker remains blocked.
        await browser.command({"event": "playback_finished", "turn_id": first["turn_id"]})
        await browser.until("state", state="listening")
        await speech.sockets[1].event("transcript_final", text="cảm ơn")
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
    await browser.until("audio_complete")
    await asyncio.wait_for(entered.wait(), 2)
    await end_call(browser, http, task)
    assert cancelled.is_set()
