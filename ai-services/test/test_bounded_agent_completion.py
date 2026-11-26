import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from test_authorization_generalization import purchase


@pytest.mark.parametrize('case', ['confirmation', 'unanswered', 'denied', 'completed', 'negative', 'budget'])
def test_one_model_continuation_preserves_authorization_receipts_and_budget(purchase, case):
    async def run():
        state, args, _ = purchase
        state['tool_count'] = 0
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
        nodes = AgentNodes(SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(
            content='Em chưa tạo đơn hàng cho mình.'))), gateway, None, 6, 6)
        with patch('app.agent.harness.agent_nodes.build_agent', side_effect=build), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='test'), \
             patch('app.agent.harness.agent_nodes.review_answer', reviewer), \
             patch('app.agent.harness.authorization.authorize_write', authorize):
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
        if case == 'completed':
            assert attempts[0] == attempts[1]
        assert result['tool_count'] <= 6
    asyncio.run(run())


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
                 side_effect=['unnecessary_clarification', 'unnecessary_clarification', None])):
            state.update(await nodes.run_agent(state))
            result = await nodes.verify_agent(state)
        assert agent.response.await_count == 2
        assert llm.ainvoke.await_count == 1
        assert result['verified_answer'] == 'Em chưa tạo đơn hàng.'
    asyncio.run(run())
