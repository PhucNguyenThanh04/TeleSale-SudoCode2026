import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from test_authorization_generalization import purchase


@pytest.mark.parametrize('case', ['confirmation', 'unanswered', 'denied', 'completed', 'negative', 'budget',
                                 'reviewer_accepts', 'price', 'promotion', 'colloquial'])
def test_one_model_continuation_preserves_authorization_receipts_and_budget(purchase, case):
    async def run():
        state, args, _ = purchase
        state['tool_count'] = 0
        if case == 'colloquial':
            state['safe_text'] = 'Đồng ý, chị lấy mẫu đó, giao trong tuần này nhé.'
            state['request'] = state['request'].model_copy(update={'text': state['safe_text']})
        if case == 'negative':
            state['safe_text'] = 'Chưa đặt hàng, chỉ tư vấn giúp tôi.'
        if case == 'budget':
            state['tool_count'] = 6
        gateway = SimpleNamespace(invoke_trusted=AsyncMock(return_value={
            'status': 'created', 'order_id': 'ORDER-INDEPENDENT-81'}))
        attempts = []
        instances = []
        allowed = case not in {'denied', 'negative'}
        authorize = AsyncMock(return_value=allowed)
        raw = {key: value for key, value in args.items() if key not in {'on', 'customer_phone'}}

        class Agent:
            def __init__(self, business):
                self.business = business
                self.invocations = 0

            async def astream(self, inputs, **kwargs):
                self.invocations += 1
                if self.invocations == 1:
                    if case == 'completed':
                        attempts.append(await self.business.invoke('order.create', raw))
                    answer = 'Mình xác nhận đặt hàng thêm lần nữa nhé?'
                    if case == 'price':
                        answer = 'Sản phẩm hiện có giá 9.999.000đ.'
                    elif case == 'promotion':
                        answer = 'Sản phẩm được tặng kèm một Xe đạp Solstice.'
                else:
                    attempts.append(await self.business.invoke('order.create', raw))
                    answer = ('Đơn hàng đã được tạo thành công.' if allowed else
                              'Em chưa tạo đơn hàng cho mình.')
                yield 'values', {'messages': [AIMessage(content=answer)]}

        def build(kind, llm, business, prompt):
            agent = Agent(business)
            instances.append(agent)
            return agent

        reason = 'unnecessary_clarification' if case == 'confirmation' else 'unanswered_request'
        reviewer = AsyncMock(side_effect=[reason, None])
        if case in {'reviewer_accepts', 'price', 'promotion', 'colloquial'}:
            reviewer = AsyncMock(return_value=None)
        nodes = AgentNodes(SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(
            content='Em chưa tạo đơn hàng cho mình.'))), gateway, None, 6, 6)
        from app.agent.harness.observability import capture_diagnostic_events
        with patch('app.agent.harness.agent_nodes.build_agent', side_effect=build), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='test'), \
             patch('app.agent.harness.agent_nodes.review_answer', reviewer), \
             patch('app.agent.harness.authorization.authorize_write', authorize), \
             capture_diagnostic_events() as events:
            from langgraph.graph import END, StateGraph
            from app.agent.harness.state import TurnState
            graph = StateGraph(TurnState)
            graph.add_node('run', nodes.run_agent)
            graph.add_node('verify', nodes.verify_agent)
            graph.set_entry_point('run')
            graph.add_edge('run', 'verify')
            graph.add_edge('verify', END)
            result = await graph.compile().ainvoke(state)
        assert len(instances) == 1
        assert result.get('agent_continuation') is None
        assert instances[0].invocations == (1 if case == 'budget' else 2)
        assert gateway.invoke_trusted.await_count == (1 if allowed and case != 'budget' else 0)
        if case != 'budget':
            assert result['reply_error'] is None
            assert result['verified_answer'] == ('Đơn hàng đã được tạo thành công.' if allowed else
                                                   'Em chưa tạo đơn hàng cho mình.')
            assert authorize.await_count == 1
            assert sum(e['event'] == 'recovery_attempted' for e in events) == 1
            assert any(e['event'] == 'recovery_succeeded' for e in events)
        if case == 'completed':
            assert attempts[0] == attempts[1]
        assert result['tool_count'] <= 6
    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'Lên đơn máy lọc không khí Solstice giúp tôi.',
    'Không cần hỏi lại, lên đơn Solstice giúp tôi.',
])
def test_product_word_and_waived_confirmation_are_not_purchase_negation(text):
    from app.agent.harness.agent_nodes import _requested_write_missing
    assert _requested_write_missing({'identity_status': 'known', 'safe_text': text,
                                     'tool_calls': []}) is True


@pytest.mark.parametrize('text', [
    'Chị lấy cái đó nhé.',
    'Đặt giúp anh mẫu đó.',
    'Đồng ý, đổi sang size 44 giúp tôi.',
    'Đổi cho tôi sang màu xanh nhé.',
])
def test_explicit_colloquial_requests_are_not_silently_accepted_without_a_write(text):
    from app.agent.harness.agent_nodes import _requested_write_missing
    assert _requested_write_missing({'identity_status': 'known', 'safe_text': text,
                                     'tool_calls': []}) is True


@pytest.mark.parametrize('text', [
    'Chị chưa lấy cái đó nhé.',
    'Đừng đặt giúp anh mẫu đó.',
    'Đổi sang size 44 có được không?',
    'Nếu còn màu xanh thì đổi cho tôi.',
    'Tôi chỉ hỏi chính sách đổi sang size 44.',
    'Bạn tôi nói lấy cái đó.',
])
def test_non_action_colloquial_language_does_not_force_recovery(text):
    from app.agent.harness.agent_nodes import _requested_write_missing
    assert _requested_write_missing({'identity_status': 'known', 'safe_text': text,
                                     'tool_calls': []}) is False


def test_continuation_runs_at_most_once_when_model_still_asks_again(purchase):
    async def run():
        from test_deep_memory import FakeStreamAgent
        state, _, _ = purchase
        agent = FakeStreamAgent()
        agent.response.return_value = {'messages': [AIMessage(content='Mình xác nhận nữa nhé?')]}
        llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content='Em chưa tạo đơn hàng.')))
        nodes = AgentNodes(llm, SimpleNamespace(), None, 6, 6)
        with patch('app.agent.harness.agent_nodes.build_agent', return_value=agent), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='test'), \
             patch('app.agent.harness.agent_nodes.review_answer', AsyncMock(
                 side_effect=lambda model, answer, context: {
                     'Mình xác nhận nữa nhé?': 'unnecessary_clarification',
                     'Em chưa tạo đơn hàng.': None,
                 }[answer])):
            state.update(await nodes.run_agent(state))
            result = await nodes.verify_agent(state)
        assert agent.response.await_count == 2
        assert llm.ainvoke.await_count == 1
        assert result['verified_answer'] == 'Em chưa tạo đơn hàng.'
    asyncio.run(run())


def test_preview_acknowledgement_requests_tool_continuation_before_answer_only_repair():
    async def run():
        from test_semantic_grounding import ReviewModel, turn_state, verdict
        state = turn_state('Em đã tiếp nhận yêu cầu đổi hàng của mình.')
        state['safe_text'] = 'Đồng ý, gửi yêu cầu đổi sang size 44 giúp tôi.'
        state['tool_calls'] = [{'name': 'order.preview_update',
            'args': {'order_id': 'ORDER-81'},
            'result': {'order_id': 'ORDER-81', 'status': 'preview', 'estimate': True}}]

        async def continue_agent(current, draft, reason):
            assert reason == 'order_update_unverified'
            current['tool_calls'].append({'name': 'order.update',
                'args': {'order_id': 'ORDER-81'},
                'result': {'order_id': 'ORDER-81', 'status': 'review_pending', 'estimate': True}})
            return 'Em đã tiếp nhận yêu cầu đổi hàng của mình, hồ sơ đang chờ duyệt.'

        continuation = AsyncMock(side_effect=continue_agent)
        state['agent_continuation'] = continuation
        model = ReviewModel([verdict()])
        nodes = AgentNodes(model, None, None, 6, 6)
        result = await nodes.verify_agent(state)
        continuation.assert_awaited_once()
        model.ainvoke.assert_not_awaited()
        assert result['reply_error'] is None
        assert result['verifier_events'][0]['reason'] == 'order_update_unverified'
        assert result['tool_calls'][-1]['name'] == 'order.update'
    asyncio.run(run())


@pytest.mark.parametrize('case', ['negated', 'conditional', 'question', 'unknown', 'completed'])
def test_accepted_non_action_or_completed_write_does_not_force_continuation(purchase, case):
    async def run():
        from test_deep_memory import FakeStreamAgent
        state, args, name = purchase
        text = {
            'negated': f'Chưa lên đơn {name} nhé.',
            'conditional': f'Nếu giao được ngày mai thì lên đơn {name}.',
            'question': f'Lên đơn {name} có được không?',
            'unknown': f'Lên đơn {name} giúp tôi.',
            'completed': f'Lên đơn {name} giúp tôi.',
        }[case]
        state['safe_text'] = text
        state['request'] = state['request'].model_copy(update={'text': text})
        if case == 'unknown':
            state['identity_status'] = 'unknown'
        if case == 'completed':
            state['tool_calls'].append({'name': 'order.create', 'args': args,
                'result': {'status': 'created', 'order_id': 'ORDER-81'}})
        answer = 'Đơn hàng đã được tạo thành công.' if case == 'completed' else 'Em cần xác minh thêm thông tin.'
        agent = FakeStreamAgent()
        agent.response.return_value = {'messages': [AIMessage(content=answer)]}
        model = SimpleNamespace(ainvoke=AsyncMock())
        nodes = AgentNodes(model, SimpleNamespace(), None, 6, 6)
        with patch('app.agent.harness.agent_nodes.build_agent', return_value=agent), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='test'), \
             patch('app.agent.harness.agent_nodes.review_answer', AsyncMock(return_value=None)):
            state.update(await nodes.run_agent(state))
            result = await nodes.verify_agent(state)
        assert agent.response.await_count == 1
        model.ainvoke.assert_not_awaited()
        assert result['verified_answer'] == answer
    asyncio.run(run())
