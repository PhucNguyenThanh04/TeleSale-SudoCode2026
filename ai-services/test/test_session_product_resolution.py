import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app.agent.implementations.business_agent import BusinessTools
from test_commerce_evidence import state, catalog, quote, stock
from test_november_pricing import reference




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












@pytest.mark.parametrize('scenario_id,sku,name', [
    ('SAMPLE-01', 'SKU-AP-Y', 'AirPure Y'),
    ('SAMPLE-04', 'SKU-SN-RUN2', 'RunLite 2 Pro'),
    ('SAMPLE-06', 'SKU-XM-4P', 'Xiaomi 4 Pro')])
@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
def test_btc_context_replays_keep_brief_on_all_returning_turns(reference, scenario_id, sku, name, delivery_mode):
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
                                  Memory(repo), max_tool_calls=10)
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
