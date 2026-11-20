import asyncio
from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.runtime import AgentHarnessRuntime
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from app.schemas.agent import TextTurnRequest
from test_basket_runtime import Memory, MemoryRepo
from test_deep_memory import FakeToolModel
from test_november_pricing import OrderRepo, reference
from test_consultation_followup import policy_result


def tool_message(*calls):
    return AIMessage(content='', tool_calls=[{'id': str(uuid4()), 'name': name.replace('.', '_'), 'args': args}
        for name, args in calls])


def runtime_for(reference, replies, *, old_orders=()):
    customer = {'customer_id': 'C-ROUND2', 'phone': '0900000000', 'name': 'Khách',
                'orders': list(old_orders), 'sessions': [], 'honorific': 'anh'}
    class Repo(OrderRepo):
        def __init__(self):
            super().__init__(reference)
            self.phone = customer['phone']
            self.updates = []
        async def rows(self, conn, table):
            return [customer] if table == 'customers' else await super().rows(conn, table)
        async def identity_matches(self, *args):
            return [{'customer_id': customer['customer_id'], 'phone': self.phone}]
        async def runtime_orders(self, conn, cid, oid=None):
            return [o for o in self.orders if cid == customer['customer_id'] and (not oid or o['order_id'] == oid)]
        async def order_owned(self, conn, oid, cid):
            return cid == customer['customer_id'] and any(o['order_id'] == oid for o in [*old_orders, *self.orders])
        async def phone_owned(self, conn, phone, cid):
            return cid == customer['customer_id'] and phone == self.phone
        async def exchange_count(self, conn, oid):
            return sum(o['order_id'] == oid for o in self.updates)
        async def insert_update(self, conn, oid, action, result):
            self.updates.append(deepcopy(result))
        async def insert_order(self, *args):
            await super().insert_order(*args)
            self.orders[-1].update(status='created', created_on=self.orders[-1]['on'])
    repo = Repo()
    base = MCPGateway(catalog_server(repo), order_server(repo), None)
    class Gateway:
        async def invoke(self, name, args):
            return await base.invoke(name, args)
        async def invoke_trusted(self, name, args, *context, **kwargs):
            if name == 'policy.search':
                result = policy_result()
                result['evidence'][0]['content'] = 'Sản phẩm bảo hành chính hãng 12 tháng. Điều kiện đổi trả cần xác minh theo đơn.'
                return result
            return await base.invoke_trusted(name, args, *context, **kwargs)
    model = FakeToolModel(replies=[*replies, *[AIMessage(content='Em kiểm tra giúp mình.') for _ in range(24)]])
    runtime = AgentHarnessRuntime(model, Gateway(), Memory(MemoryRepo()), max_tool_calls=8)
    return runtime, repo


async def turns(runtime, texts, on):
    sid = uuid4()
    responses, states = [], []
    for text in texts:
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=sid, on=date.fromisoformat(on),
            channel='hotline', channel_identity='0900000000', input_mode='clean', text=text)
        responses.append(await runtime.run(request))
        states.append(deepcopy(runtime.state_for(request)))
    return responses, states


@pytest.mark.parametrize('text,sku,on', [
    ('Anh đang xem AirPure Pro giá bao nhiêu và hiện còn hàng không?', 'SKU-AP-PRO', '2026-10-19'),
    ('Kiểm tra Giày trekking HikePro size 42 màu xám còn hàng không, chưa tạo phiếu đổi nhé.',
     'SKU-SN-TRK-42-XAM', '2026-11-04'),
])
def test_explicit_stock_request_reaches_exact_mcp_sku(reference, text, sku, on):
    runtime, repo = runtime_for(reference, [AIMessage(content='Em kiểm tra giúp mình.')])
    async def run():
        try:
            replies, states = await turns(runtime, [text], on)
            checks = [c for c in states[0]['tool_calls'] if c['name'] == 'inventory.check']
            assert checks and checks[-1]['args']['sku'] == sku, (replies[0].agent_text, states[0]['tool_calls'])
            expected = reference.inventory_check(sku, on=on)['in_stock']
            assert ('còn hàng' if expected else 'hết hàng') in replies[0].agent_text
            assert not repo.orders and not repo.updates
        finally:
            await runtime.close()
    asyncio.run(run())


def test_mixed_basket_is_presented_before_acceptance_and_creates_both_lines(reference):
    runtime, repo = runtime_for(reference, [
        tool_message(('catalog.search', {'sku': 'SKU-MB-BOT'}), ('catalog.search', {'sku': 'SKU-MB-MON'})),
        AIMessage(content='Máy hâm sữa Fatz 4 chức năng có giá 490.000đ.')])
    async def run():
        try:
            replies, states = await turns(runtime, [
                'Anh hỏi bình sữa Pigeon PPSU 240ml và máy hâm sữa Fatz 4 chức năng, kiểm tra tồn kho và báo tổng giá giỏ hàng cả 2 sản phẩm giúp anh.',
                'Ok anh đồng ý tổng giá đó, lên đơn cả 2 sản phẩm thanh toán COD giúp anh nhé.',
            ], '2026-10-25')
            assert '779.000' in replies[0].agent_text, replies[0].agent_text
            assert 'Pigeon' in replies[0].agent_text and 'Fatz' in replies[0].agent_text
            assert len(repo.orders) == 1, [r.agent_text for r in replies]
            assert {line['sku'] for line in repo.orders[0]['lines']} == {'SKU-MB-BOT', 'SKU-MB-MON'}
            assert repo.orders[0]['total_vnd'] == 779000 and repo.orders[0]['payment'] == 'COD'
            assert not any(c['name'] == 'order.create' for c in states[0]['tool_calls'])
        finally:
            await runtime.close()
    asyncio.run(run())


def test_policy_backed_offer_survives_intervening_policy_turn_and_creates_bank_order(reference):
    runtime, repo = runtime_for(reference, [
        tool_message(('catalog.search', {'sku': 'SKU-MB-STER'}),
                     ('pricing.get_quote', {'sku': 'SKU-MB-STER'}), ('inventory.check', {'sku': 'SKU-MB-STER'})),
        AIMessage(content='Máy tiệt trùng sấy khô Moaz Bebe giá 1.890.000đ, bảo hành 12 tháng.'),
        AIMessage(content='Theo chính sách đã kiểm tra, bảo hành chính hãng 12 tháng.')])
    async def run():
        try:
            replies, _ = await turns(runtime, [
                'Máy tiệt trùng sấy khô Moaz Bebe giá bao nhiêu, còn hàng không và bảo hành bao lâu?',
                'Chính sách bảo hành thế nào em?',
                'Được rồi, lên đơn 1 chiếc máy tiệt trùng sấy khô Moaz Bebe, thanh toán chuyển khoản nhé.',
            ], '2026-10-21')
            assert len(repo.orders) == 1, [r.agent_text for r in replies]
            assert repo.orders[0]['sku'] == 'SKU-MB-STER' and repo.orders[0]['payment'] == 'bank'
            assert repo.orders[0]['order_id'] in replies[-1].agent_text
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('size', [41, 43])
def test_parent_quote_then_variant_choice_completes_order(reference, size):
    runtime, repo = runtime_for(reference, [AIMessage(content='Mình cho em biết size hoặc màu cần chọn ạ?')])
    async def run():
        try:
            replies, states = await turns(runtime, ['Giày chạy bộ RunLite 2 Pro giá bao nhiêu em?',
                f'Ok lấy size {size} màu đen, lên đơn cho chị.'], '2026-10-16')
            assert '1.521.000' in replies[0].agent_text, replies[0].agent_text
            if size == 43:
                assert not repo.orders, [r.agent_text for r in replies]
                assert 'đồng ý' in replies[-1].agent_text.lower(), replies[-1].agent_text
                accepted = await runtime.run(states[-1]['request'].model_copy(update={
                    'client_msg_id': uuid4(), 'text': 'Đồng ý mua theo báo giá mới này, lên đơn cho chị.'}))
                assert repo.orders and repo.orders[-1]['order_id'] in accepted.agent_text
            assert len(repo.orders) == 1, [r.agent_text for r in replies]
            assert repo.orders[0]['sku'] == f'SKU-SN-RUN2-{size}-DEN'
            assert repo.orders[0]['price_vnd'] == (1521000 if size == 41 else 1740000)
        finally:
            await runtime.close()
    asyncio.run(run())


def test_exchange_receipt_is_acknowledged_after_model_draft_is_rejected(reference):
    seed = {'order_id': 'OD-SEED', 'sku': 'SKU-JK-WND-L-BE', 'qty': 1, 'price_vnd': 690000,
            'customer_phone': '0900000000', 'status': 'delivered', 'created_on': '2026-10-21'}
    runtime, repo = runtime_for(reference, [tool_message(
        ('catalog.search', {'sku': 'SKU-JK-WND'}),
        ('order.update', {'order_id': 'OD-SEED', 'action': 'exchange_product', 'new_variant_sku': 'SKU-JK-WND-XL-NAVY'})),
        AIMessage(content='Đã đổi hàng, chênh lệch 40.000đ.')], old_orders=[seed])
    async def run():
        try:
            replies, _ = await turns(runtime, [
                'Chị đồng ý bù chênh lệch giá 40.000 đồng, cập nhật đổi áo Windbreak sang size XL màu navy cho đơn OD-SEED nhé.',
            ], '2026-10-28')
            assert len(repo.updates) == 1 and repo.updates[0]['action'] == 'exchange_size'
            assert 'OD-SEED' in replies[0].agent_text and 'ghi nhận' in replies[0].agent_text
            assert 'tổng đài' not in replies[0].agent_text and not repo.orders
        finally:
            await runtime.close()
    asyncio.run(run())
