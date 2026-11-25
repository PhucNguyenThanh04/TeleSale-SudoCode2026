import asyncio
import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from app.agent.harness.runtime import AgentHarnessRuntime
from app.agent.harness.authorization import WriteAuthorization
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from app.mcp_servers.mcp_memory.services.memory import read, write
from app.mcp_servers.mcp_shared.memory_observations import memory_observations
from app.schemas.agent import PrepareSessionRequest, TextTurnRequest, VoicePlaybackRequest
from test_deep_memory import FakeToolModel
from test_operational_memory import Repo as ReadRepo, Projection
from test_november_pricing import OrderRepo, reference


class BasketModel(FakeToolModel):
    authorization_decisions: list[bool] = []
    authorization_payloads: list[dict] = []

    def with_structured_output(self, schema, **kwargs):
        if schema is WriteAuthorization:
            async def review(messages):
                payload = json.loads(messages[-1].content)
                self.authorization_payloads.append(payload)
                allowed = self.authorization_decisions.pop(0)
                return {'allowed': allowed, 'basis': 'customer_request' if allowed else 'none',
                    'reason': 'authorized' if allowed else 'wrong_terms',
                    'customer_quote': payload['customer_text']}
            return SimpleNamespace(ainvoke=review)
        return super().with_structured_output(schema, **kwargs)


class MemoryRepo(ReadRepo):
    def __init__(self):
        super().__init__()
        self.operations = {}
        self.links = []
        self.sequence = 0

    async def next_turn(self, conn, sid):
        return await self.turn_count(conn, sid) + 1

    async def insert_turn(self, conn, sid, number, cid, channel, on, customer, agent, tid, tool_observations=None, outcome="khac"):
        self.sessions.setdefault(sid, {'owner': cid, 'turns': []})['turns'].append({
            'client_msg_id': tid, 'customer_text': customer, 'agent_text': agent,
            'on_date': on.isoformat(), 'channel': channel, 'tool_observations': tool_observations or []})

    async def enqueue_distillation(self, conn, sid, cid, tid, calls, *args, **kwargs):
        self.sequence += 1
        row = next(t for t in self.sessions[sid]['turns'] if str(t['client_msg_id']) == str(tid))
        row.update(job_id=self.sequence, memory_status='pending', tool_observations=memory_observations(calls))

    async def claim_operation(self, conn, key, digest):
        if key not in self.operations:
            self.operations[key] = (digest, None)
        old, result = self.operations[key]
        return result if old == digest else {'error': 'operation_key_conflict'}

    async def finish_operation(self, conn, key, result):
        self.operations[key] = (self.operations[key][0], result)

    async def link_order(self, conn, cid, order):
        self.links.append((cid, order))

    async def order_links(self, conn, cid):
        return [order for customer, order in self.links if customer == cid]


class Memory:
    include_prior = True
    def __init__(self, repo):
        self.repo = repo
    async def read_context(self, sid, cid):
        return await read(self.repo, cid, sid, include_prior=self.include_prior, projector=Projection())
    async def commit_turn(self, sid, cid, customer, agent, on, channel, tid, **kwargs):
        return await write(self.repo, 'commit_turn', cid, sid,
            {'client_msg_id': tid, 'customer_text': customer, 'agent_text': agent,
             'on': on, 'channel': channel, **kwargs}, f'{sid}:{tid}:commit_turn')


@pytest.mark.parametrize('delivery_mode,include_prior,heard,price_changed', [
    ('text', True, True, False), ('voice', True, True, False), ('text', False, True, False),
    ('voice', False, True, False), ('voice', True, False, False),
    ('text', True, True, True), ('voice', True, True, True)],
    ids=['text-full', 'voice-full', 'text-baseline', 'voice-baseline', 'voice-interrupted',
         'text-price-change', 'voice-price-change'])
def test_returning_customer_buys_delivered_basket_while_all_workers_pending(reference, delivery_mode, include_prior, heard, price_changed):
    customer = {'customer_id': 'C1', 'phone': '0900000000', 'name': 'Khách',
                'orders': [], 'sessions': [], 'honorific': 'anh'}
    class CommerceRepo(OrderRepo):
        reprice = False
        async def rows(self, session, table):
            if table == 'policy_chunks':
                return []
            if table == 'promotions' and self.reprice:
                return []
            return [customer] if table == 'customers' else await super().rows(session, table)
        async def runtime_orders(self, *args):
            return self.orders
        async def identity_matches(self, *args):
            return [{'customer_id': customer['customer_id'], 'phone': self.phone}]
    commerce = CommerceRepo(reference)
    commerce.phone = customer['phone']
    memory_repo = MemoryRepo()
    price = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])['total_vnd']
    new_price = 2 * next(product['list_price_vnd'] for product in reference.PRODUCTS
                         if product['sku'] == 'SKU-AP-PRO')
    quote_calls = [AIMessage(content='', tool_calls=[
        {'id': str(uuid4()), 'name': 'catalog_search', 'args': {'sku': 'SKU-AP-PRO'}},
        {'id': str(uuid4()), 'name': 'pricing_quote_order', 'args': {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 2}]}}])]
    quoted = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])
    order_lines = [{'sku': unit['sku'], 'qty': 1, 'price_vnd': unit['final_price_vnd']}
                   for unit in quoted['units']]
    if price_changed:
        order_lines = [{'sku': 'SKU-AP-PRO', 'qty': 1, 'price_vnd': new_price // 2} for _ in range(2)]
    create = AIMessage(content='', tool_calls=[{'id': str(uuid4()), 'name': 'order_create',
        'args': {'lines': order_lines, 'payment': 'bank'}}])
    stock = AIMessage(content='', tool_calls=[{'id': str(uuid4()), 'name': 'inventory_check',
        'args': {'sku': 'SKU-AP-PRO'}}])
    should_create = include_prior and heard and not price_changed
    model = BasketModel(authorization_decisions=[should_create, True], replies=[*quote_calls,
        AIMessage(content=f'2 máy AirPure Pro có tổng giá {price:,}đ.'.replace(',', '.')),
        *quote_calls, stock, create,
        AIMessage(content=(f'2 máy AirPure Pro có tổng giá {new_price:,}đ.'.replace(',', '.')
            if price_changed else 'Em đã tạo đơn 2 máy AirPure Pro.' if should_create
            else 'Em cần xác nhận báo giá trước khi tạo đơn.')),
        create, AIMessage(content='Em đã tạo đơn 2 máy AirPure Pro.')])
    secret = 'offline-basket-runtime'
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce, context_secret=secret),
        order_server(commerce, context_secret=secret), None, context_secret=secret),
                                  Memory(memory_repo), max_tool_calls=8)
    runtime.memory.include_prior = include_prior
    async def run():
        responses = []
        for text in ('Báo giá 2 máy AirPure Pro.', 'Đồng ý mua cả hai máy như hôm trước, chuyển khoản nhé.'):
            request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), on=date(2026, 10, 15),
                channel='hotline', channel_identity=customer['phone'], text=text,
                input_mode='clean', delivery_mode=delivery_mode)
            await runtime.prepare_session(PrepareSessionRequest(**request.model_dump(include={
                'session_id', 'channel', 'channel_identity', 'on'})))
            response = await runtime.run(request)
            if delivery_mode == 'voice':
                await runtime.record_playback(VoicePlaybackRequest(**request.model_dump(include={
                    'session_id', 'client_msg_id', 'channel', 'channel_identity', 'on'}),
                    played_chars=len(response.agent_text) if heard or responses else 10,
                    interrupted=not heard and not responses))
            responses.append(response)
            commerce.reprice = price_changed
        assert len(commerce.orders) == int(include_prior and heard and not price_changed), [(r.agent_text) for r in responses]
        review = model.authorization_payloads[0]
        history = json.dumps({key: review[key] for key in
            ('session_history', 'previous_episodes', 'customer_statements')}, ensure_ascii=False)
        prior_offer = f'2 máy AirPure Pro có tổng giá {price:,}đ.'.replace(',', '.')
        assert (prior_offer in history) is (include_prior and heard)
        if price_changed:
            quotes = [call for call in runtime.state_for(request).get('tool_calls', [])
                      if call.get('name') == 'pricing.quote_order']
            assert quotes and quotes[-1]['result']['total_vnd'] != price
            assert f'{new_price:,}đ'.replace(',', '.') in responses[-1].agent_text
            confirmation = request.model_copy(update={'client_msg_id': uuid4(),
                'text': 'Đồng ý mua cả hai máy theo giá mới, chuyển khoản nhé.'})
            accepted = await runtime.run(confirmation)
            if delivery_mode == 'voice':
                await runtime.record_playback(VoicePlaybackRequest(**confirmation.model_dump(include={
                    'session_id', 'client_msg_id', 'channel', 'channel_identity', 'on'}),
                    played_chars=len(accepted.agent_text), interrupted=False))
            assert len(commerce.orders) == 1, accepted.agent_text
        if commerce.orders:
            assert len(commerce.orders[0]['lines']) == 2
            assert commerce.orders[0]['total_vnd'] == (new_price if price_changed else price)
            assert commerce.orders[0]['payment'] == 'bank'
        assert all(row['memory_status'] == 'pending' for session in memory_repo.sessions.values() for row in session['turns'])
        assert not runtime._playback_tasks
    asyncio.run(run())


@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
@pytest.mark.parametrize('changed_lines,change_text', [
    ([{'sku': 'SKU-AP-PRO', 'qty': 1}], 'Chỉ lấy một máy AirPure Pro, chuyển khoản nhé.'),
    ([{'sku': 'SKU-AP-MINI', 'qty': 2}], 'Đổi sang mua 2 máy AirPure Mini, chuyển khoản nhé.'),
    ([{'sku': 'SKU-AP-PRO', 'qty': 1}, {'sku': 'SKU-AP-MINI', 'qty': 1}],
     'Lấy một AirPure Pro và một AirPure Mini, chuyển khoản nhé.'),
], ids=['quantity', 'product', 'mixed-products'])
def test_changed_basket_requires_new_delivered_offer_then_can_complete(reference, delivery_mode, changed_lines, change_text):
    from collections import Counter
    customer = {'customer_id': 'C1', 'phone': '0900000000', 'name': 'Khách', 'orders': [], 'sessions': []}
    class CommerceRepo(OrderRepo):
        async def rows(self, session, table):
            if table == 'policy_chunks':
                return []
            return [customer] if table == 'customers' else await super().rows(session, table)
        async def identity_matches(self, *args):
            return [{'customer_id': 'C1', 'phone': customer['phone']}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = CommerceRepo(reference)
    commerce.phone = customer['phone']
    old_lines = [{'sku': 'SKU-AP-PRO', 'qty': 2}]
    new_quote = reference.pricing_quote_order(changed_lines)
    def quoted_reply(lines):
        quote = reference.pricing_quote_order(lines)
        labels = ', '.join(next(p['name'] for p in reference.PRODUCTS if p['sku'] == sku)
                           for sku in dict.fromkeys(line['sku'] for line in lines))
        return f"{sum(line['qty'] for line in lines)} sản phẩm {labels} có tổng giá {quote['total_vnd']:,}đ.".replace(',', '.')
    def quote_message(lines):
        return AIMessage(content='', tool_calls=[
            *[{'id': str(uuid4()), 'name': 'catalog_search', 'args': {'sku': sku}}
              for sku in dict.fromkeys(line['sku'] for line in lines)],
            *[{'id': str(uuid4()), 'name': 'inventory_check', 'args': {'sku': sku}}
              for sku in dict.fromkeys(line['sku'] for line in lines)],
            {'id': str(uuid4()), 'name': 'pricing_quote_order', 'args': {'lines': lines}}])
    order_lines = [{'sku': unit['sku'], 'qty': 1, 'price_vnd': unit['final_price_vnd']}
                   for unit in new_quote['units']]
    model = BasketModel(authorization_decisions=[True], replies=[
        quote_message(old_lines), AIMessage(content=quoted_reply(old_lines)),
        quote_message(changed_lines), AIMessage(content=quoted_reply(changed_lines)),
        AIMessage(content='', tool_calls=[{'id': str(uuid4()), 'name': 'order_create',
            'args': {'lines': order_lines, 'payment': 'bank'}}]),
        AIMessage(content='Em đã tạo đơn theo báo giá mới.')])
    memory_repo = MemoryRepo()
    secret = 'offline-basket-runtime'
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce, context_secret=secret),
        order_server(commerce, context_secret=secret), None, context_secret=secret),
                                  Memory(memory_repo), max_tool_calls=12)
    async def run():
        sid = uuid4()
        for index, text in enumerate(('Báo giá 2 máy AirPure Pro.', change_text,
                                     'Đồng ý mua theo báo giá mới, chuyển khoản nhé.')):
            request = TextTurnRequest(client_msg_id=uuid4(), session_id=sid, on=date(2026, 10, 15),
                channel='hotline', channel_identity=customer['phone'], text=text,
                input_mode='clean', delivery_mode=delivery_mode)
            if index == 0:
                await runtime.prepare_session(PrepareSessionRequest(**request.model_dump(include={
                    'session_id', 'channel', 'channel_identity', 'on'})))
            response = await runtime.run(request)
            if delivery_mode == 'voice':
                await runtime.record_playback(VoicePlaybackRequest(**request.model_dump(include={
                    'session_id', 'client_msg_id', 'channel', 'channel_identity', 'on'}),
                    played_chars=len(response.agent_text), interrupted=False))
            if index < 2:
                assert not commerce.orders, response.agent_text
            if index == 1:
                assert f"{new_quote['total_vnd']:,}đ".replace(',', '.') in response.agent_text
        assert len(commerce.orders) == 1, response.agent_text
        actual = Counter((line['sku'], line['price_vnd']) for line in commerce.orders[0]['lines']
                         for _ in range(line['qty']))
        assert actual == Counter((unit['sku'], unit['final_price_vnd']) for unit in new_quote['units'])
        assert commerce.orders[0]['total_vnd'] == new_quote['total_vnd']
        assert not runtime._playback_tasks
    asyncio.run(run())
