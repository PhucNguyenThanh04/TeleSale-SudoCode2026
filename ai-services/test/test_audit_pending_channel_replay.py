import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from test_basket_runtime import Memory, MemoryRepo
from test_deep_memory import FakeGateway, FakeToolModel, turn


def test_restarted_cross_channel_contact_retains_pending_sources_without_inventing_resolved_blocker():
    async def run():
        repo = MemoryRepo()
        first_request = turn('Ngân sách tổng 5 triệu; tôi còn phải hỏi chồng trước khi mua.')
        first = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content='Dạ, em ghi nhận.')]),
                                   FakeGateway(customer_id='C1'), Memory(repo))
        try:
            await first.run(first_request)
        finally:
            await first.close()
        model = FakeToolModel(replies=[AIMessage(content='Mình muốn hỏi thêm phần nào ạ?')])
        restored = DeepHarnessRuntime(model, FakeGateway(customer_id='C1'), Memory(repo))
        next_request = turn('Tôi nhắn tiếp từ Facebook, chồng tôi chưa đồng ý.').model_copy(update={
            'channel': 'chat_fanpage', 'channel_identity': 'linked-facebook', 'session_id': uuid4()})
        try:
            await restored.run(next_request)
            assert 'Ngân sách tổng 5 triệu' in model.seen[-1]
            assert str(first_request.client_msg_id) in model.seen[-1]
            state = restored.state_for(next_request)
            assert state['episodes'][0]['topics'] == []
            assert all(row['memory_status'] == 'pending' for session in repo.sessions.values()
                       for row in session['turns'])
        finally:
            await restored.close()
    asyncio.run(run())
