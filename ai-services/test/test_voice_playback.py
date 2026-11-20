
import unittest
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.runtime import AgentHarnessRuntime
from app.schemas.agent import VoicePlaybackRequest
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


class VoicePlaybackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('offline voice test'))
        blocker.start()
        self.addCleanup(blocker.stop)

    async def test_voice_commits_only_acknowledged_prefix_once(self):
        memory = FakeMemory()
        model = FakeToolModel(replies=[AIMessage(content="Xin chào. Em có thể giúp gì?")])
        gateway = FakeGateway()
        runtime = AgentHarnessRuntime(model, gateway, memory)
        request = turn("Xin chào").model_copy(update={"delivery_mode": "voice"})
        response = await runtime.run(request)
        calls = list(gateway.calls)
        assert not memory.turns.get(str(request.session_id))
        receipt = VoicePlaybackRequest(**{key: getattr(request, key) for key in
            ("session_id", "client_msg_id", "channel", "channel_identity", "on")},
            played_chars=len("Xin chào."), interrupted=True)
        await runtime.record_playback(receipt)
        await runtime.record_playback(receipt)
        saved = memory.turns[str(request.session_id)]
        assert len(saved) == 1
        assert saved[0]["agent"] == response.agent_text[:receipt.played_chars]
        assert saved[0]["customer"] == request.text
        assert gateway.calls == calls
        assert model.replies == []
        assert not runtime._playback_tasks

    async def test_unknown_or_wrong_identity_receipt_cannot_commit(self):
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Xin chào.")]),
                                      FakeGateway(), memory)
        request = turn("Xin chào").model_copy(update={"delivery_mode": "voice"})
        await runtime.run(request)
        payload = {key: getattr(request, key) for key in
                   ("session_id", "client_msg_id", "channel", "channel_identity", "on")}
        for update in ({"client_msg_id": uuid4()}, {"channel_identity": "someone-else"},
                       {"played_chars": 9000}):
            with pytest.raises(ValueError):
                await runtime.record_playback(VoicePlaybackRequest(**(payload | update)))
        await runtime.record_playback(VoicePlaybackRequest(**payload))
        assert memory.turns[str(request.session_id)][0]["agent"] == ""

    async def test_missing_receipt_is_conservative_before_next_turn(self):
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Xin chào."),
            AIMessage(content="Em đang nghe.")]), FakeGateway(), memory)
        request = turn("Xin chào").model_copy(update={"delivery_mode": "voice"})
        await runtime.run(request)
        await runtime.run(turn("Tiếp nhé", session_id=request.session_id))
        saved = memory.turns[str(request.session_id)]
        assert saved[0]["agent"] == ""
        assert saved[1]["agent"] == "Em đang nghe."
        assert not runtime._playback_tasks

    async def test_shutdown_commits_customer_and_omits_unconfirmed_speech(self):
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Xin chào.")]),
                                      FakeGateway(), memory)
        request = turn("Xin chào").model_copy(update={"delivery_mode": "voice"})
        await runtime.run(request)
        await runtime.close()
        assert memory.turns[str(request.session_id)] == [{"customer": "Xin chào", "agent": ""}]
        assert not runtime._playback_tasks

    async def test_conflicting_receipt_does_not_rewrite_saved_history(self):
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Xin chào.")]),
                                      FakeGateway(), memory)
        request = turn("Xin chào").model_copy(update={"delivery_mode": "voice"})
        await runtime.run(request)
        payload = {key: getattr(request, key) for key in
                   ("session_id", "client_msg_id", "channel", "channel_identity", "on")}
        await runtime.record_playback(VoicePlaybackRequest(**payload))
        with pytest.raises(ValueError):
            await runtime.record_playback(VoicePlaybackRequest(**payload, played_chars=9))
        assert memory.turns[str(request.session_id)][0]["agent"] == ""

    async def test_expired_receipt_commits_no_unconfirmed_assistant_text(self):
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[AIMessage(content="Xin chào.")]),
                                      FakeGateway(), memory)
        request = turn("Xin chào").model_copy(update={"delivery_mode": "voice"})
        await runtime.run(request)
        key = (str(request.session_id), str(request.client_msg_id))
        timer = runtime._playback_tasks[key]
        timer.cancel()
        import asyncio
        await asyncio.gather(timer, return_exceptions=True)
        with patch('app.agent.harness.runtime.asyncio.sleep') as sleep:
            await runtime._expire_playback(key)
            sleep.assert_awaited_once_with(300)
        assert memory.turns[str(request.session_id)][0]['agent'] == ''
        assert not runtime._playback_tasks
