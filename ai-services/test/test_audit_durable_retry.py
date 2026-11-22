import asyncio
from unittest.mock import AsyncMock

import pytest
from types import SimpleNamespace
from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from test_deep_memory import FakeMemory, FakeGateway, FakeToolModel, turn


class Memory(FakeMemory):
    supports_durable_replay = True

    def __init__(self):
        super().__init__()
        self.replays = {}

    async def replay_turn(self, session_id, customer_id, client_msg_id, request_hash):
        saved = self.replays.get((session_id, client_msg_id))
        if saved is None:
            return {'found': False}
        if saved['request_hash'] != request_hash:
            return {'error': 'turn_retry_conflict'}
        return {'found': True, 'agent_text': saved['agent_text'], 'tool_observations': []}

    async def commit_turn(self, session_id, customer_id, customer_text, agent_text,
                          on, channel, client_msg_id, *, request_hash=None, **kwargs):
        self.replays[(session_id, client_msg_id)] = {'request_hash': request_hash, 'agent_text': agent_text}
        return await super().commit_turn(session_id, customer_id, customer_text, agent_text,
                                         on, channel, client_msg_id, **kwargs)


def test_restart_replays_committed_reply_without_model_or_business_write_and_rejects_conflict():
    async def run():
        memory = Memory()
        request = turn('Xin tư vấn')
        first = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content='Mình muốn chọn sản phẩm nào ạ?')]),
                                   FakeGateway(), memory)
        expected = await first.run(request)
        await first.close()
        model = FakeToolModel(replies=[])
        second = DeepHarnessRuntime(model, FakeGateway(), memory)
        try:
            response = await second.run(request)
            assert response.agent_text == expected.agent_text
            assert not model.seen
            with pytest.raises(ValueError, match='retry'):
                await second.run(request.model_copy(update={'text': 'Yêu cầu khác'}))
        finally:
            await second.close()
    asyncio.run(run())


def test_internal_mcp_replay_binds_the_committed_request_and_requires_recovery_for_uncommitted_reply():
    from app.agent.mcp.gateway import MCPGateway
    from app.agent.memory.store import MCPMemoryStore
    from app.mcp_servers.mcp_memory.tools.handlers import create_server
    from test_audit_delivery_context import Repo as DeliveryRepo

    class Repo(DeliveryRepo):
        written = False

        async def insert_turn(self, *args, request_hash=None, **kwargs):
            await super().insert_turn(*args, **kwargs)
            self.saved[-1]['request_hash'] = request_hash

        async def replay_turn(self, conn, session, tid):
            row = next((row for row in self.saved if row['client_msg_id'] == tid), None)
            return {**row, 'tool_observations': []} if row else None

        async def has_committed_writes(self, *args):
            return self.written

    async def run():
        repo = Repo()
        memory = MCPMemoryStore(MCPGateway(None, None, create_server(repo)))
        request = turn('Dạ')
        sid, tid = str(request.session_id), str(request.client_msg_id)
        assert await memory.replay_turn(sid, None, tid, 'a'*64) == {'found': False}
        await memory.commit_turn(sid, None, request.text, 'Dạ, em nghe.', request.on.isoformat(),
                                  request.channel, tid, request_hash='a'*64)
        assert (await memory.replay_turn(sid, None, tid, 'a'*64))['agent_text'] == 'Dạ, em nghe.'
        assert (await memory.replay_turn(sid, None, tid, 'b'*64))['error'] == 'turn_retry_conflict'
        repo.saved.clear()
        repo.written = True
        replay = await memory.replay_turn(sid, None, tid, 'a'*64)
        assert replay['found'] and not replay['agent_text']
    asyncio.run(run())


def test_recovery_checks_the_business_write_ledger():
    from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
    conn = SimpleNamespace(fetchval=AsyncMock(return_value=True))
    assert asyncio.run(object.__new__(MemoryRepo).has_committed_writes(conn, 'session', 'message'))
    assert 'runtime.tool_operations' in conn.fetchval.await_args.args[0]


def test_runtime_cache_prunes_idle_sessions_and_keeps_active_locks():
    async def run():
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), FakeGateway(), Memory())
        runtime._cache_max_sessions = 2
        runtime._session_access = {'old': 0, 'active': 0}
        runtime._session_tool_calls['old'] = [{'private': 'old'}]
        runtime._locks['old']
        await runtime._locks['active'].acquire()
        try:
            runtime._prune_cache('new')
            assert 'old' not in runtime._locks and 'old' not in runtime._session_tool_calls
            assert runtime._locks['active'].locked()
        finally:
            runtime._locks['active'].release()
            await runtime.close()
    asyncio.run(run())
