"""Resolve an explicitly named product before asking the customer to name it again."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.session_nodes import safe_consultation_reply
from app.mcp_servers.mcp_shared.consultation import derive_consultation
from test_commerce_evidence import state, catalog, quote, stock
from test_november_pricing import reference


@pytest.mark.parametrize('text,query', [
    ('Chị gọi lại lấy cái AirPure X giảm 500k hôm trước nhé.', 'AirPure X'),
    ('Lấy AsterAir42, chuyển khoản nhé.', 'AsterAir42'),
    ('Giá Xiaomi 4 Pro bao nhiêu?', 'Xiaomi 4 Pro'),
    ('Lấy SKU-ASTER-42 nhé.', 'SKU-ASTER-42'),
    ('Alo, tôi gọi lại.', None), ('Lấy cái hôm trước nhé.', None),
    ('Ngân sách 5 triệu, phòng 25 m2.', None)])
def test_product_lookup_query_comes_from_an_explicit_identifier(text, query):
    from app.agent.harness.catalog_query import explicit_product_query
    assert explicit_product_query(text) == query


class Gateway:
    def __init__(self, outcome='one'):
        self.calls = []
        self.outcome = outcome

    async def invoke(self, name, args):
        self.calls.append((name, args))
        if name == 'catalog.search':
            if self.outcome == 'failed':
                return {'error': 'unavailable'}
            items = [{'sku': 'SKU-ASTER', 'name': 'AsterAir42', 'category': 'air',
                      'variants': [], 'list_price_vnd': 900000, 'attributes': {}}]
            if self.outcome == 'none':
                items = []
            elif self.outcome == 'ambiguous':
                items.append({**items[0], 'sku': 'SKU-BERYL'})
            return {'items': items}
        if name == 'pricing.get_quote':
            return {'sku': args['sku'], 'final_price_vnd': 900000, 'list_price_vnd': 900000,
                    'applied_promos': [], 'freeship': False}
        if name == 'inventory.check':
            return {'sku': args['sku'], 'in_stock': True, 'qty': 10}
        raise AssertionError('Preparation must remain read-only: ' + name)


def test_named_product_is_resolved_before_selection_clarification():
    current = state('Lấy AsterAir42, chuyển khoản nhé.')
    gateway = Gateway()
    tools = BusinessTools(gateway, current, 6, lambda: datetime.now(timezone.utc))
    asyncio.run(tools.prepare_consultation())
    assert gateway.calls and gateway.calls[0] == ('catalog.search', {'query': 'AsterAir42'})
    assert derive_consultation(current).snapshot.selected_sku == 'SKU-ASTER'
    assert 'Mình muốn lấy mẫu nào' not in (safe_consultation_reply(current) or '')


def test_price_request_prepares_only_the_explicit_model_without_purchase_consent():
    current = state('Báo giá AsterAir42.')
    gateway = Gateway()
    tools = BusinessTools(gateway, current, 6, lambda: datetime.now(timezone.utc))
    asyncio.run(tools.prepare_consultation())
    assert gateway.calls[0] == ('catalog.search', {'query': 'AsterAir42'})
    assert all(name in {'catalog.search', 'pricing.get_quote'} for name, _ in gateway.calls)
    assert derive_consultation(current).snapshot.selected_sku is None
    assert derive_consultation(current).snapshot.accepted_offer is None


@pytest.mark.parametrize('outcome', ['none', 'failed', 'ambiguous'])
def test_unresolved_lookup_never_selects_first_item_and_is_not_repeated(outcome):
    async def run():
        current = state('Lấy AsterAir42, chuyển khoản nhé.')
        gateway = Gateway(outcome)
        tools = BusinessTools(gateway, current, 6, lambda: datetime.now(timezone.utc))
        await tools.prepare_consultation()
        await tools.prepare_consultation()
        assert len([call for call in gateway.calls if call[0] == 'catalog.search']) == 1
        assert derive_consultation(current).snapshot.selected_sku is None
        assert await tools.complete_purchase_if_ready() is None
        if outcome in {'none', 'failed'}:
            assert 'Mình muốn lấy mẫu nào' not in (safe_consultation_reply(current) or '')
    asyncio.run(run())


def test_unresolved_new_product_cannot_reuse_an_older_selected_product():
    current = state('Đổi sang lấy BerylAir93, chuyển khoản nhé.')
    source = str(uuid4())
    current['history'] = [{'customer': 'Tôi chọn AsterAir42.',
                          'agent': 'AsterAir42 giá 900.000đ.', 'source_turn_id': source}]
    current['session_tool_calls'] = [{**call, 'source_turn_id': source} for call in (
        catalog('SKU-ASTER', 'AsterAir42'), quote(), stock())]
    gateway = Gateway('none')
    tools = BusinessTools(gateway, current, 6, lambda: datetime.now(timezone.utc))
    asyncio.run(tools.prepare_consultation())
    assert derive_consultation(current).snapshot.selected_sku is None


@pytest.mark.parametrize('agent_kind', ['deep', 'react'])
@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
def test_btc_returning_product_replay_does_not_repeat_selection(reference, agent_kind, delivery_mode):
    import json
    from datetime import date
    from pathlib import Path
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
    from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
    from eval_harness.benchmark_runner import run_scenario_call, scenario_call_date
    from test_november_pricing import OrderRepo
    from test_basket_runtime import Memory, MemoryRepo
    from test_deep_memory import FakeToolModel
    root = Path(__file__).resolve().parents[2].parent / 'BTC-Data-Vong1-TEAMS/test_set/public_sample'
    scenario = next(data for path in root.glob('*.json')
                    if (data := json.loads(path.read_text()))['scenario_id'] == 'SAMPLE-05')
    customer = {'customer_id': 'C1', 'phone': scenario['customer_phone'], 'name': 'Khách',
                'orders': [], 'sessions': []}
    class CommerceRepo(OrderRepo):
        async def rows(self, session, table):
            return [customer] if table == 'customers' else await super().rows(session, table)
        async def identity_matches(self, *args):
            return [{'customer_id': 'C1', 'phone': customer['phone']}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = CommerceRepo(reference)
    commerce.phone = customer['phone']
    model = FakeToolModel(replies=[AIMessage(content=text) for text in (
        'AirPure X giá 4.390.000đ.', 'Dạ, khi cần mình liên hệ lại nhé.',
        'AirPure X giá hiện tại 4.890.000đ. Mình đồng ý giá này để lên đơn không ạ?',
        'AirPure X giá hiện tại 4.890.000đ.', 'Dạ, em kiểm tra đơn giúp mình.')])
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce), order_server(commerce), None),
                                  Memory(MemoryRepo()), agent_kind=agent_kind, max_tool_calls=10)
    async def run():
        trace = []
        states = []
        for call, spec in sorted(scenario['calls'].items()):
            trace.extend(await run_scenario_call(runtime, scenario['scenario_id'], call, spec,
                date(2026, 10, 15), customer['phone'],
                call_date=scenario_call_date(scenario['calls'], call, date(2026, 10, 15)),
                delivery_mode=delivery_mode, on_turn=lambda request, response, state, row: states.append(state)))
        returning = [row for row in trace if row['call'] == 'call_2']
        assert not any('Mình muốn lấy mẫu nào' in row['agent_text'] for row in returning)
        from app.mcp_servers.mcp_shared.consultation import consultation_missing_fields
        last = derive_consultation(states[-1])
        assert len(commerce.orders) == 1, (
            consultation_missing_fields(states[-1]), last.snapshot.selected_sku,
            last.snapshot.accepted_offer.price_vnd if last.snapshot.accepted_offer else None,
            [(call['name'], call.get('args', {}).get('sku')) for call in states[-1].get('tool_calls', [])])
        assert commerce.orders[0]['sku'] == 'SKU-AP-X'
        assert commerce.orders[0]['total_vnd'] == 4890000
        assert all('facts_established' not in prompt for prompt in model.seen)
        await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('scenario_id,sku,name', [
    ('SAMPLE-01', 'SKU-AP-Y', 'AirPure Y'),
    ('SAMPLE-04', 'SKU-SN-RUN2', 'RunLite 2 Pro'),
    ('SAMPLE-06', 'SKU-XM-4P', 'Xiaomi 4 Pro')])
@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
def test_btc_context_replays_keep_brief_on_all_returning_turns(reference, scenario_id, sku, name, delivery_mode):
    """Original customer inputs; model stub tests transport/context, not model quality."""
    import json
    from datetime import date
    from pathlib import Path
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
    from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
    from eval_harness.benchmark_runner import run_scenario_call, scenario_call_date
    from test_november_pricing import OrderRepo
    from test_basket_runtime import Memory, MemoryRepo
    from test_deep_memory import FakeToolModel
    root = Path(__file__).resolve().parents[2].parent / 'BTC-Data-Vong1-TEAMS/test_set/public_sample'
    scenario = next(data for path in root.glob('*.json')
                    if (data := json.loads(path.read_text()))['scenario_id'] == scenario_id)
    customer = {'customer_id': 'C1', 'phone': scenario['customer_phone'], 'name': 'Khách',
                'fb_id': scenario['calls']['call_1'].get('channel_identity'),
                'orders': [], 'sessions': []}
    class CommerceRepo(OrderRepo):
        async def rows(self, session, table):
            return [customer] if table == 'customers' else await super().rows(session, table)
        async def identity_matches(self, *args):
            return [{'customer_id': 'C1', 'phone': customer['phone']}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = CommerceRepo(reference)
    commerce.phone = customer['phone']
    calls = [AIMessage(content='', tool_calls=[
        {'id': 'catalog', 'name': 'catalog_search', 'args': {'sku': sku}},
        {'id': 'quote', 'name': 'pricing_get_quote', 'args': {'sku': sku}}])]
    count = sum(len(spec['customer_turns']) for spec in scenario['calls'].values())
    model = FakeToolModel(replies=[*calls, *[AIMessage(content=f'Em đang tư vấn {name}.') for _ in range(count + 4)]])
    repo = MemoryRepo()
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce), order_server(commerce), None),
                                  Memory(repo), agent_kind='react', max_tool_calls=10)
    async def run():
        returning = []
        for call, spec in sorted(scenario['calls'].items()):
            await run_scenario_call(runtime, scenario_id, call, spec, date(2026, 10, 20), customer['phone'],
                call_date=scenario_call_date(scenario['calls'], call, date(2026, 10, 20)),
                delivery_mode=delivery_mode,
                on_turn=lambda request, response, state, row: returning.append((response, state)) if call == 'call_2' else None)
        assert len(returning) == len(scenario['calls']['call_2']['customer_turns'])
        for response, state in returning:
            assert response.call_brief and response.call_brief['is_returning']
            assert state['episodes'], state
            assert state['customer_id'] == 'C1'
            assert state['scoped_facts']['product'], state['scoped_facts']
            assert not state.get('memory_blocked')
        initial = returning[0][1]
        if scenario_id == 'SAMPLE-01':
            assert initial['profile']['room_area_m2']['value'] == 25
            assert initial['profile']['budget_vnd']['value'] == 5000000
        elif scenario_id == 'SAMPLE-06':
            assert initial['profile']['room_area_m2']['value'] == 35
            assert initial['profile']['budget_vnd']['value'] == 5500000
        assert all('facts_established' not in prompt for prompt in model.seen)
        assert all(row['memory_status'] == 'pending' for session in repo.sessions.values() for row in session['turns'])
        await runtime.close()
    asyncio.run(run())
