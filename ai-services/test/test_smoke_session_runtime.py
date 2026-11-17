"""Smoke speech through preparation, production memory projection and real graph."""
import asyncio
import json
from datetime import date
from pathlib import Path
from uuid import uuid4
import pytest

from langchain_core.messages import AIMessage

from app.agent.harness.runtime import AgentHarnessRuntime
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from app.mcp_servers.mcp_shared.memory_observations import memory_observations
from app.schemas.agent import PrepareSessionRequest, TextTurnRequest
from test_basket_runtime import Memory, MemoryRepo
from test_deep_memory import FakeToolModel
from test_november_pricing import OrderRepo, reference

RUN = Path(__file__).resolve().parents[1] / 'eval_harness/results/smoke-repairs/20261112T060044Z-17ffa366'


@pytest.mark.parametrize('acceptance,created', [
    (None, True), ('Chưa đặt hàng nhé.', False),
    ('Em lên đơn đúng đôi đó giá 1.000.000 đồng, chuyển khoản nhé.', False)])
def test_t17_real_preparation_and_operational_prior_episode_can_close(reference, acceptance, created):
    rows = [r for r in map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines())
            if r['scenario_id'] == 'SC-T17']
    customer = next(c for c in reference.CRM if c['customer_id'] == 'C008')
    class Commerce(OrderRepo):
        async def rows(self, conn, table):
            return [customer] if table == 'customers' else await super().rows(conn, table)
        async def identity_matches(self, *args):
            return [{'customer_id': 'C008', 'phone': self.phone}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = Commerce(reference)
    commerce.phone = customer['phone']
    repo = MemoryRepo()
    prior = str(uuid4())
    repo.sessions[prior] = {'owner': 'C008', 'turns': [
        {'client_msg_id': str(uuid4()), 'customer_text': r['user_text'], 'agent_text': r['agent_text'],
         'on_date': '2026-10-22', 'channel': 'hotline',
         'tool_observations': memory_observations(r['tool_calls'])}
        for r in rows if r['call'] == 'call_1']}
    current = [r for r in rows if r['call'] == 'call_2']
    def reads(row):
        return AIMessage(content='', tool_calls=[{'id': str(uuid4()),
            'name': c['name'].replace('.', '_'),
            'args': {k: v for k, v in c['args'].items() if k not in {'on', 'customer_phone'}}}
            for c in row['tool_calls']])
    model = FakeToolModel(replies=[reads(current[0]), AIMessage(content=current[0]['agent_text']),
                                  reads(current[1]), AIMessage(content=current[1]['agent_text'])])
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce), order_server(commerce), None),
                                  Memory(repo), max_tool_calls=5)
    async def run():
        sid = uuid4()
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=sid, on=date(2026, 10, 27),
            channel='hotline', channel_identity=customer['phone'], text=current[0]['user_text'],
            input_mode='clean', delivery_mode='text')
        await runtime.prepare_session(PrepareSessionRequest(**request.model_dump(include={
            'session_id', 'channel', 'channel_identity', 'on'})))
        await runtime.run(request)
        request = request.model_copy(update={'client_msg_id': uuid4(), 'text': acceptance or current[1]['user_text']})
        response = await runtime.run(request)
        state = runtime.state_for(request)
        from app.mcp_servers.mcp_shared.consultation import purchase_arguments, purchase_block_reason
        args = purchase_arguments(state)
        assert len(commerce.orders) == int(created), (response.agent_text, args,
            purchase_block_reason(state, args) if args else (state.get('consultation'), state.get('scoped_facts')))
        if created:
            assert commerce.orders[0]['sku'] == 'SKU-SN-RUN1-41-DEN'
            assert commerce.orders[0]['payment'] == 'bank'
    asyncio.run(run())


@pytest.mark.parametrize('sid,cid,on,total', [
    ('SC-T18', 'C010', '2026-10-25', 779000),
    ('SC-T10', 'C011', '2026-10-23', 8480000)])
def test_basket_real_memory_and_preparation_quotes_total_before_acceptance(reference, sid, cid, on, total):
    rows = [r for r in map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines())
            if r['scenario_id'] == sid]
    customer = next(c for c in reference.CRM if c['customer_id'] == cid)
    class Commerce(OrderRepo):
        async def rows(self, conn, table):
            return [customer] if table == 'customers' else await super().rows(conn, table)
        async def identity_matches(self, *args):
            return [{'customer_id': cid, 'phone': self.phone}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = Commerce(reference)
    commerce.phone = customer['phone']
    repo = MemoryRepo()
    session_id = uuid4()
    prior_id = str(session_id) if sid == 'SC-T10' else str(uuid4())
    repo.sessions[prior_id] = {'owner': cid, 'turns': [
        {'client_msg_id': str(uuid4()), 'customer_text': r['user_text'], 'agent_text': r['agent_text'],
         'on_date': '2026-10-23', 'channel': 'hotline',
         'tool_observations': memory_observations(r['tool_calls'])}
        for r in rows if r['call'] == 'call_1' and (sid == 'SC-T18' or r['turn'] == 1)]}
    model = FakeToolModel(replies=[AIMessage(content='', tool_calls=[
        {'id': str(uuid4()), 'name': 'catalog_search', 'args': {'sku': sku}}
        for sku in (['SKU-MB-BOT', 'SKU-MB-MON'] if sid == 'SC-T18' else ['SKU-MB-CAR', 'SKU-MB-STR1'])]),
        AIMessage(content='Dạ, em đang kiểm tra giỏ hàng.')])
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce), order_server(commerce), None),
                                  Memory(repo), max_tool_calls=5)
    current = [r for r in rows if r['call'] == 'call_2'] if sid == 'SC-T18' else [r for r in rows if r['call'] == 'call_1' and r['turn'] > 1]
    async def run():
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=session_id, on=date.fromisoformat(on),
            channel='hotline', channel_identity=customer['phone'], text=current[0]['user_text'],
            input_mode='clean', delivery_mode='text')
        await runtime.prepare_session(PrepareSessionRequest(**request.model_dump(include={
            'session_id', 'channel', 'channel_identity', 'on'})))
        offered = await runtime.run(request)
        assert f'{total:,}'.replace(',', '.') in offered.agent_text, offered.agent_text
        assert not commerce.orders
        request = request.model_copy(update={'client_msg_id': uuid4(), 'text': current[1]['user_text']})
        accepted = await runtime.run(request)
        assert len(commerce.orders) == 1, accepted.agent_text
        assert commerce.orders[0]['total_vnd'] == total
        assert {line['sku'] for line in commerce.orders[0]['lines']} == ({'SKU-MB-BOT', 'SKU-MB-MON'} if sid == 'SC-T18' else {'SKU-MB-CAR', 'SKU-MB-STR1'})
        assert runtime.state_for(request)['tool_count'] <= 5
    asyncio.run(run())


def test_t09_trace_records_real_prepare_quote_without_duplicate_read(reference):
    from eval_harness.benchmark_runner import run_scenario_call
    rows = [r for r in map(json.loads, (RUN / 'full.diagnostics_full.jsonl').read_text().splitlines())
            if r['scenario_id'] == 'SC-T09']
    customer = next(c for c in reference.CRM if c['customer_id'] == 'C006')
    class Commerce(OrderRepo):
        async def rows(self, conn, table):
            return [customer] if table == 'customers' else await super().rows(conn, table)
        async def identity_matches(self, *args):
            return [{'customer_id': 'C006', 'phone': self.phone}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = Commerce(reference)
    commerce.phone = customer['phone']
    repo = MemoryRepo()
    for call, on in [('call_1', '2026-10-19'), ('call_2', '2026-10-21')]:
        repo.sessions[str(uuid4())] = {'owner': 'C006', 'turns': [
            {'client_msg_id': str(uuid4()), 'customer_text': r['user_text'], 'agent_text': r['agent_text'],
             'on_date': on, 'channel': 'hotline', 'tool_observations': memory_observations(r['tool_calls'])}
            for r in rows if r['call'] == call]}
    current = [r for r in rows if r['call'] == 'call_3']
    model = FakeToolModel(replies=[AIMessage(content='', tool_calls=[{
        'id': str(uuid4()), 'name': 'catalog_search', 'args': {'sku': 'SKU-AP-PRO'}}]),
        AIMessage(content=current[0]['agent_text']), AIMessage(content=current[1]['agent_text'])])
    runtime = AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce), order_server(commerce), None),
                                  Memory(repo), max_tool_calls=5)
    trace = asyncio.run(run_scenario_call(runtime, 'SC-T09', 'call_3',
        {'customer_turns': [r['user_text'] for r in current]}, date(2026, 10, 22),
        customer['phone'], delivery_mode='text'))
    quotes = [c for c in trace[0]['tool_calls'] if c['name'] == 'pricing.get_quote']
    assert len(quotes) == 1
    assert quotes[0]['args']['sku'] == 'SKU-AP-PRO'
    assert quotes[0]['args']['on'] == '2026-10-22'
    assert quotes[0]['result']['final_price_vnd'] == 7690000
    assert not commerce.orders
