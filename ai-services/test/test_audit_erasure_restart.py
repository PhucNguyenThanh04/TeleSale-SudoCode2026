import asyncio
from contextlib import asynccontextmanager

from langchain_core.messages import AIMessage
from unittest.mock import patch

from app.agent.harness.runtime import DeepHarnessRuntime
from app.mcp_servers.mcp_memory.services.memory import read
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn
from test_deep_memory import FakeStreamAgent


def test_completed_erasure_returns_a_distinct_signal_without_removing_write_barrier():
    class Repo:
        supports_erasure_state = True

        @asynccontextmanager
        async def transaction(self):
            yield object()

        async def lock_key(self, *args):
            pass

        async def is_erasure_blocked(self, *args):
            return True

        async def erasure_state(self, *args):
            return 'completed'

    assert asyncio.run(read(Repo(), 'C001', str(turn('Dạ').session_id))) == {'error': 'customer_erased'}


def test_completed_erasure_clears_owner_caches_and_serves_new_anonymous_contact():
    class Memory(FakeMemory):
        erased = False

        async def read_context(self, session_id, customer_id):
            if self.erased and customer_id:
                return {'error': 'customer_erased'}
            return await super().read_context(session_id, customer_id)

    async def run():
        memory = Memory()
        model = FakeToolModel(replies=[AIMessage(content='Dạ, em ghi nhận.'),
                                      AIMessage(content='Em có thể giúp mình chọn sản phẩm ạ.')])
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        first = turn('Tôi cần tư vấn.')
        try:
            await runtime.run(first)
            key = (str(first.session_id), str(first.client_msg_id))
            runtime._preparations[str(first.session_id)] = (first.on, 0, 'C001', [])
            memory.erased = True
            memory.turns.clear()
            second = turn('Xin tư vấn sản phẩm mới.', first.session_id)
            response = await runtime.run(second)
            assert response.agent_text
            assert runtime.state_for(second)['customer_id'] is None
            assert runtime.state_for(second)['crm_orders'] == []
            assert key not in runtime._states and key not in runtime._responses
            assert not runtime._preparations
            assert response.memory_update.status == 'not_applicable'
            assert runtime._session_identities[str(first.session_id)][1]['customer_id'] is None
        finally:
            await runtime.close()
    asyncio.run(run())


def test_erasure_cancels_another_inflight_answer_before_it_can_publish_old_context():
    class Memory(FakeMemory):
        erased = False

        async def read_context(self, sid, cid):
            if self.erased and cid:
                return {'error': 'customer_erased'}
            return await super().read_context(sid, cid)

    async def run():
        memory = Memory()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), FakeGateway(), memory)
        entered = asyncio.Event()

        async def respond(inputs, **kwargs):
            if inputs['messages'][-1].content == 'Giữ phiên cũ':
                entered.set()
                await asyncio.Event().wait()
            return {'messages': [AIMessage(content='Mình cần tư vấn gì ạ?')]}

        try:
            with patch('app.agent.harness.agent_nodes.build_agent',
                       return_value=FakeStreamAgent(side_effect=respond)):
                pending = asyncio.create_task(runtime.run(turn('Giữ phiên cũ')))
                await asyncio.wait_for(entered.wait(), 2)
                memory.erased = True
                await runtime.run(turn('Xin chào'))
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError('Old answer was not cancelled')
                assert not runtime._turn_progress
        finally:
            await runtime.close()
    asyncio.run(run())


def test_erasure_purges_other_sessions_and_cancels_uncommitted_playback():
    class Memory(FakeMemory):
        erased = False

        async def read_context(self, session_id, customer_id):
            if self.erased and customer_id:
                return {'error': 'customer_erased'}
            return await super().read_context(session_id, customer_id)

    async def run():
        memory = Memory()
        model = FakeToolModel(replies=[AIMessage(content='Dạ, em ghi nhận.') for _ in range(3)])
        runtime = DeepHarnessRuntime(model, FakeGateway(), memory)
        first = turn('Xin tư vấn')
        voice = turn('Xin tư vấn').model_copy(update={'delivery_mode': 'voice'})
        try:
            await runtime.run(first)
            await runtime.run(voice)
            assert runtime._playback_tasks
            memory.erased = True
            memory.turns.clear()
            await runtime.run(turn('Chào bạn'))
            assert not runtime._playback_tasks and not runtime._playback_receipts
            assert runtime.state_for(first) is None and runtime.state_for(voice) is None
            assert str(voice.session_id) not in memory.turns
        finally:
            await runtime.close()
    asyncio.run(run())
