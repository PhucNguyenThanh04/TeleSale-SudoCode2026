import asyncio
import time
from unittest.mock import patch
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.runtime import DeepHarnessRuntime
from test_deep_memory import FakeGateway, FakeToolModel, FakeStreamAgent, turn
from test_audit_durable_retry import Memory


@pytest.mark.parametrize('phase', ['model', 'verification', 'after_write'])
def test_total_deadline_bounds_model_review_and_successful_write_recovery(phase):
    async def run():
        memory = Memory()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), FakeGateway(), memory)
        runtime.turn_timeout_seconds = .15
        request = turn('Tôi cần tư vấn.')

        async def invoke(inputs, **kwargs):
            if phase == 'verification':
                return {'messages': [AIMessage(content='Mình muốn tư vấn loại sản phẩm nào ạ?')]}
            if phase == 'after_write':
                from app.agent.harness.streaming import active_stream
                active_stream.get().state['tool_calls'].append({'name': 'order.create',
                    'args': {'sku': 'SKU-A', 'qty': 1},
                    'result': {'order_id': 'OD-SAVED', 'status': 'created'}})
            await asyncio.sleep(5)

        async def review(*args, **kwargs):
            await asyncio.sleep(5)

        started = time.monotonic()
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', return_value=FakeStreamAgent(side_effect=invoke)), \
                 patch('app.agent.harness.agent_nodes.review_answer', side_effect=review):
                with pytest.raises(RuntimeError, match='turn_deadline_exceeded'):
                    await runtime.run(request)
            assert time.monotonic() - started < .5
            if phase == 'after_write':
                assert (str(request.session_id), str(request.client_msg_id)) in memory.replays
                assert any(call['result'].get('order_id') == 'OD-SAVED'
                           for call in runtime.state_for(request)['tool_calls'])
        finally:
            await runtime.close()
    asyncio.run(run())


def test_timeout_after_real_signed_mcp_write_survives_restart_without_second_order():
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
    from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
    from test_write_authorization import OrderRepo, current, SECRET

    class Repo(OrderRepo):
        async def rows(self, session, table):
            return [] if table == 'policy_chunks' else await super().rows(session, table)

    async def run():
        repo, memory = Repo(), Memory()
        repo.product['brand'] = 'Offline'
        request = current()['request']
        gateway = MCPGateway(catalog_server(repo, context_secret=SECRET),
            order_server(repo, context_secret=SECRET), None, context_secret=SECRET)
        original = gateway.invoke

        async def invoke(name, args):
            if name == 'crm.get_customer':
                return {'found': True, 'customer_id': repo.owner, 'phone': '0900000027',
                        'orders': [], 'sessions': []}
            return await original(name, args)

        gateway.invoke = invoke
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), gateway, memory, turn_timeout_seconds=.5)

        def build(kind, model, business, prompt):
            async def respond(inputs, **kwargs):
                await business.invoke('catalog.search', {'sku': 'DEVICE-RED'})
                await business.invoke('inventory.check', {'sku': 'DEVICE-RED'})
                await business.invoke('pricing.get_quote', {'sku': 'DEVICE-RED'})
                result = await business.invoke('order.create', {'sku': 'DEVICE-RED', 'qty': 1,
                                               'price_vnd': 97000, 'payment': 'COD'})
                assert result['status'] == 'created', result
                await asyncio.Event().wait()
            return FakeStreamAgent(side_effect=respond)

        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=build), \
                 patch('app.agent.harness.authorization.authorize_write', AsyncMock(return_value=True)):
                with pytest.raises(RuntimeError, match='turn_deadline_exceeded'):
                    await runtime.run(request)
            assert len(repo.writes) == 1
            restored = DeepHarnessRuntime(FakeToolModel(replies=[]), gateway, memory)
            try:
                with pytest.raises(RuntimeError, match='turn_recovery_required'):
                    await restored.run(request)
                assert len(repo.writes) == 1
            finally:
                await restored.close()
        finally:
            await runtime.close()
    asyncio.run(run())
