import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from app.agent.harness.agent_nodes import AgentNodes, _task_answer_complete
from test_commerce_evidence import state
from test_november_pricing import reference


SHIPPING_QUESTION = ('Chị chưa nhận được mã vận đơn, em báo giúp chị mã vận đơn, đơn vị giao hàng '
                     'và quy định giao lại nếu lúc shipper gọi chị vắng nhà nhé.')




def test_tracking_and_redelivery_are_answered_together_without_model(reference):
    from test_m1_round2_runtime import runtime_for, turns
    from test_consultation_followup import policy_result
    seed = {'order_id':'OD-TRACK', 'sku':'SKU-MB-PUMP1', 'price_vnd':4290000, 'qty':1,
            'customer_phone':'0900000000', 'status':'shipping', 'date':'2026-10-03', 'tracking':'GHN7781234'}
    runtime, _ = runtime_for(reference, [], old_orders=[seed])
    original = runtime.tools.invoke_trusted
    async def invoke(name, args, *context, **kwargs):
        if name == 'policy.search':
            result = policy_result()
            result['evidence'][0]['content'] = ('Giao không thành công\nĐơn vị vận chuyển giao tối đa 3 lần. '
                'Sau 3 lần không thành công, hàng hoàn về kho; khách muốn giao lại phải đặt đơn mới.')
            return result
        return await original(name, args, *context, **kwargs)
    runtime.tools.invoke_trusted = invoke
    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model')):
                replies, states = await turns(runtime, [SHIPPING_QUESTION], '2026-10-23')
            answer = replies[0].agent_text
            assert 'GHN7781234' in answer and '3 lần' in answer and 'đặt đơn mới' in answer, answer
            assert 'đơn vị giao hàng' in answer.lower(), answer
            assert 'chưa' in answer.lower(), answer
            assert {c['name'] for c in states[0]['tool_calls']} >= {'order.status','policy.search'}
        finally:
            await runtime.close()
    asyncio.run(run())






def test_short_action_confirmation_does_not_publish_a_generic_acknowledgement():
    from app.agent.harness.streaming import GuardedStream
    async def run():
        current = state('Ok em làm đi nhé.')
        current['history'] = [{'customer':'Anh muốn đổi sang size lớn hơn.',
                              'agent':'Mình đồng ý để em cập nhật yêu cầu đổi hàng không ạ?'}]
        sink = AsyncMock(return_value=True)
        stream = GuardedStream(sink)
        await stream.feed(AIMessageChunk(content='Dạ, em sẽ hỗ trợ mình. ', id='confirmation'), current)
        assert not sink.called
    asyncio.run(run())


def test_named_shoe_stock_variant_is_prepared_without_model_loops(reference):
    from test_m1_round2_runtime import runtime_for, turns
    runtime, repo = runtime_for(reference, [])
    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model')):
                replies, states = await turns(runtime, [
                    'Em ơi Giày sneaker Urban Classic còn size 39 màu den không?',
                ], '2026-10-15')
            checks = [c for c in states[0]['tool_calls'] if c['name']=='inventory.check']
            assert checks and checks[-1]['args']['sku'] == 'SKU-SN-CAS-39-DEN'
            assert 'còn hàng' in replies[0].agent_text
            assert not repo.orders
        finally:
            await runtime.close()
    asyncio.run(run())


def test_budget_search_returns_verified_shortlist_without_model_roundtrip(reference):
    from test_m1_round2_runtime import runtime_for, turns
    runtime, repo = runtime_for(reference, [])
    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model')):
                replies, states = await turns(runtime, [
                    'Chào em, anh đang tìm máy lọc không khí cho phòng ngủ 25 mét vuông '
                    'trong tầm giá 3 triệu đổ lại, bên em có mẫu nào phù hợp?',
                ], '2026-11-05')
            answer = replies[0].agent_text
            assert 'Xiaomi Smart 4 Lite' in answer and '2.990.000' in answer, answer
            assert '25 m²' in answer
            assert any(c['name'] == 'pricing.get_quote' for c in states[0]['tool_calls'])
            assert not repo.orders
        finally:
            await runtime.close()
    asyncio.run(run())


def test_prepared_price_objection_does_not_wait_for_model_to_repeat_evidence():
    from test_consultation_followup import consultation_state, quoted, FollowupGateway
    current = quoted(consultation_state('Aster Air bên kia bán 4590k, sao bên em đắt hơn?'),
                     promos=[{'type':'freecod','promo_code':'COD-ZERO','discount_vnd':0}])
    async def run():
        node = AgentNodes(None, FollowupGateway(), None, 6, 6)
        with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model')):
            result = await node.run_agent(current)
        assert '5.200.000' in result['agent_draft'] and 'COD' in result['agent_draft']
        assert result['followup_kind'] == 'price_objection'
        assert not any(c['name'].startswith('order.') for c in result['tool_calls'])
    asyncio.run(run())


def test_complete_published_answer_does_not_spin_on_later_tool_requests():
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.harness.observability import capture_diagnostic_events
    from test_deep_memory import FakeToolModel, FakeMemory, FakeGateway, turn
    class ToolAfterAnswer(FakeToolModel):
        calls: int = 0
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            yield ChatGenerationChunk(message=AIMessageChunk(content='Em có thể tư vấn sản phẩm trong danh mục. '))
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[{
                'name':'catalog_search', 'args':'{"query":"AirPure X"}', 'id':f'tool-{self.calls}', 'index':0}]))
    async def run():
        model, gateway = ToolAfterAnswer(replies=[]), FakeGateway()
        runtime = AgentHarnessRuntime(model, gateway, FakeMemory())
        try:
            with capture_diagnostic_events() as events:
                result = [e async for e in runtime.stream(turn('Em có thể hỗ trợ gì?'))]
            assert result[-1]['event']=='done'
            assert model.calls == 1
            assert not any(e.get('status')=='failed' for e in events)
            assert not any(name=='catalog.search' for name, _ in gateway.calls)
        finally:
            await runtime.close()
    asyncio.run(run())
