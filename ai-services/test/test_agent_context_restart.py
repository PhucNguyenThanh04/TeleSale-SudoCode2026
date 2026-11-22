import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.authorization import WriteAuthorization
from app.agent.harness.runtime import AgentHarnessRuntime
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from app.schemas.agent import TextTurnRequest, VoicePlaybackRequest
from test_basket_runtime import Memory, MemoryRepo
from test_deep_memory import FakeToolModel
from test_november_pricing import OrderRepo, reference


@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
def test_restarted_runtime_creates_only_the_requested_basket_using_persisted_evidence(reference, delivery_mode):
    customer = {'customer_id': 'C1', 'phone': '0900000011', 'name': 'Khách', 'orders': [], 'sessions': []}

    class Commerce(OrderRepo):
        async def rows(self, session, table):
            if table == 'customers':
                return [customer]
            if table == 'policy_chunks':
                return []
            return await super().rows(session, table)

        async def identity_matches(self, *args):
            return [{'customer_id': 'C1', 'phone': customer['phone']}]

        async def runtime_orders(self, *args):
            return self.orders

    class ApprovedModel(FakeToolModel):
        def with_structured_output(self, schema, **kwargs):
            if schema is WriteAuthorization:
                async def review(messages):
                    payload = json.loads(messages[-1].content)
                    return {'allowed': True, 'basis': 'customer_request', 'reason': 'authorized',
                            'customer_quote': payload['customer_text']}
                return SimpleNamespace(ainvoke=review)
            return super().with_structured_output(schema, **kwargs)

    async def run():
        commerce, memory = Commerce(reference), MemoryRepo()
        commerce.phone = customer['phone']
        lines = [{'sku': 'SKU-AP-PRO', 'qty': 2}]
        quoted = reference.pricing_quote_order(lines, on='2026-10-15')
        order_lines = [{'sku': unit['sku'], 'qty': 1, 'price_vnd': unit['final_price_vnd']}
                       for unit in quoted['units']]

        def runtime(model):
            secret = 'offline-restart-contract'
            gateway = MCPGateway(catalog_server(commerce, context_secret=secret),
                order_server(commerce, context_secret=secret), None, context_secret=secret)
            return AgentHarnessRuntime(model, gateway, Memory(memory))

        async def respond(active, request):
            response = await active.run(request)
            if delivery_mode == 'voice':
                await active.record_playback(VoicePlaybackRequest(**request.model_dump(include={
                    'session_id', 'client_msg_id', 'channel', 'channel_identity', 'on'}),
                    played_chars=len(response.agent_text), interrupted=False))
            return response

        request = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(), channel='hotline',
            channel_identity=customer['phone'], on='2026-10-15', input_mode='clean',
            delivery_mode=delivery_mode, text='Báo giá 2 máy AirPure Pro, tổng ngân sách 12 triệu.')
        first = runtime(FakeToolModel(replies=[
            AIMessage(content='', tool_calls=[
                {'id': 'catalog', 'name': 'catalog_search', 'args': {'sku': 'SKU-AP-PRO'}},
                {'id': 'stock', 'name': 'inventory_check', 'args': {'sku': 'SKU-AP-PRO'}},
                {'id': 'quote', 'name': 'pricing_quote_order', 'args': {'lines': lines}}]),
            AIMessage(content=f"2 máy AirPure Pro có tổng giá {quoted['total_vnd']:,}đ.".replace(',', '.'))]))
        try:
            await respond(first, request)
        finally:
            await first.close()
        for i in range(14):
            await Memory(memory).commit_turn(str(request.session_id), 'C1', f'Tôi hỏi thêm chi tiết {i}.',
                'Dạ.', '2026-10-15', 'hotline', str(uuid4()))
        restored = runtime(ApprovedModel(replies=[
            AIMessage(content='', tool_calls=[{'id': 'create', 'name': 'order_create',
                'args': {'lines': order_lines, 'payment': 'bank'}}]),
            AIMessage(content='Em đã tạo đơn đúng 2 máy AirPure Pro.')]))
        accepted = request.model_copy(update={'client_msg_id': uuid4(),
            'text': f"Tôi đồng ý mua 2 máy AirPure Pro, tổng giá {quoted['total_vnd']}đ, chuyển khoản nhé."})
        try:
            await respond(restored, accepted)
            assert len(commerce.orders) == 1
            assert commerce.orders[0]['lines'] == order_lines
            assert commerce.orders[0]['total_vnd'] == quoted['total_vnd']
            assert commerce.orders[0]['payment'] == 'bank'
            calls = restored.state_for(accepted)['tool_calls']
            assert [call['name'] for call in calls if call['name'] != 'crm.get_customer'] == ['order.create']
        finally:
            await restored.close()
    asyncio.run(run())
