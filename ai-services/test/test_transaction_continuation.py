"""Saved K0 customer speech through production graph/MCP with offline storage/model."""
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.runtime import AgentHarnessRuntime
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from eval_harness.benchmark_runner import run_scenario_call, scenario_call_date
from test_basket_runtime import Memory, MemoryRepo
from test_deep_memory import FakeToolModel
from test_november_pricing import OrderRepo, reference

K0 = Path(__file__).resolve().parents[1] / 'eval_harness/results/knowledge-k0/20261111T082822Z-116126a9'


@pytest.mark.parametrize('text,requested', [
    ('Anh muốn kiểm lại đơn với khoản thu trước khi khui.', True),
    ('Em kiểm lại đơn giúp anh nhé.', True),
    ('Anh chưa cần kiểm lại đơn.', False),
    ('Đừng kiểm lại đơn, anh chỉ hỏi giá.', False),
    ('Nếu kiểm lại đơn thì cần thông tin gì?', False),
    ('Em lên đơn giúp anh nhé.', False),
])
def test_receipt_lookup_language_keeps_negation_and_purchase_separate(text, requested):
    from app.mcp_servers.mcp_shared.consultation_followup import order_status_requested
    assert order_status_requested(text) is requested


@pytest.mark.parametrize('scenario_id,sku', [
    ('SC-T01', 'SKU-XM-4P'), ('SC-T02', 'SKU-JK-WND-M-NAVY'), ('SC06', 'SKU-XM-4P')])
@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
def test_k0_customer_sequence_creates_selected_order_and_reads_receipt(reference, scenario_id, sku,
                                                                     delivery_mode):
    scenario = next(data for path in (K0 / 'scenarios').glob('*.json')
                    if (data := json.loads(path.read_text()))['scenario_id'] == scenario_id)
    customer = next(c for c in reference.CRM if c['phone'] == scenario['customer_phone'])
    class Repo(OrderRepo):
        async def rows(self, session, table):
            return reference.CRM if table == 'customers' else await super().rows(session, table)
        async def identity_matches(self, *args):
            return [{'customer_id': customer['customer_id'], 'phone': self.phone}]
        async def runtime_orders(self, session, customer_id, order_id=None):
            return [order for order in self.orders if customer_id == customer['customer_id']
                    and (order_id is None or order['order_id'] == order_id)]
        async def order_owned(self, session, order_id, customer_id):
            return bool(await self.runtime_orders(session, customer_id, order_id))
        async def insert_order(self, session, order_id, customer_id, args, price, total, codes):
            await super().insert_order(session, order_id, customer_id, args, price, total, codes)
            self.orders[-1].update(status='created', created_on=args['on'])
    repo = Repo(reference)
    repo.phone = customer['phone']
    saved = [json.loads(line) for line in (K0 / 'full.diagnostics_full.jsonl').read_text().splitlines()]
    first = next(row for row in saved if row['scenario_id'] == scenario_id)
    from app.agent.implementations.tool_names import MODEL_TOOL_NAMES
    reads = [call for call in first['tool_calls']
             if call['name'] in {'catalog.search', 'inventory.check', 'pricing.get_quote'}]
    # Replay actual discovery proposals, not scenario answer/SKU labels. Trusted
    # owner/date parameters come from runtime, not the masked trace values.
    model = FakeToolModel(replies=[AIMessage(content='', tool_calls=[{
        'id': f'saved-discovery-{i}', 'name': MODEL_TOOL_NAMES[call['name']],
        'args': {k: v for k, v in call['args'].items() if k not in {'customer_phone', 'address', 'on'}}}
        for i, call in enumerate(reads)]),
        *[AIMessage(content='Dạ, em kiểm tra giúp mình.') for _ in range(80)]])
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(repo), order_server(repo), None),
                                  Memory(MemoryRepo()), max_tool_calls=8)
    async def run():
        rows = []
        try:
            # Order/lookup path only; SC-T02's later policy/exchange discussion is separate.
            calls = list(sorted(scenario['calls'].items()))[:1 if scenario_id == 'SC-T02' else 3]
            for call, spec in calls:
                rows.extend(await run_scenario_call(runtime, scenario_id, call, spec,
                    date(2026, 10, 15), customer['phone'],
                    call_date=scenario_call_date(scenario['calls'], call, date(2026, 10, 15)),
                    delivery_mode=delivery_mode))
            assert len(repo.orders) == 1, [(r['call'], r['turn'], r['agent_text'],
                [(t['name'], t.get('args'), t.get('result', {}).get('error')) for t in r['tool_calls']]) for r in rows]
            assert repo.orders[0]['sku'] == sku
            assert not any(t['args'].get('sku', '').startswith('SKU-MB-') for r in rows
                           for t in r['tool_calls'] if t['name'] == 'pricing.get_quote')
            if scenario_id == 'SC-T01':
                lookups = [t for r in rows if r['call'] == 'call_3' for t in r['tool_calls']
                           if t['name'] == 'order.status']
                assert lookups and lookups[0]['args']['order_id'] == repo.orders[0]['order_id']
                assert any(repo.orders[0]['order_id'] in row['agent_text'] and 'đơn đã tạo' in row['agent_text']
                           for row in rows if row['call'] == 'call_3')
            assert all('facts_established' not in prompt for prompt in model.seen)
        finally:
            await runtime.close()
    asyncio.run(run())
