import asyncio
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.harness.context import load_context, prompt_context
from app.agent.memory.deterministic_tool_facts import verified_order_details
from app.mcp_servers.mcp_memory.distiller_worker import process_one
from app.mcp_servers.mcp_memory.services.memory import _operational_facts
from test_memory_fact_review import source, worker_fixture


def variant_reads():
    variants = [{'variant_sku': 'ITEM-COAT-43-RED', 'size': 43, 'color': 'đỏ'},
                {'variant_sku': 'ITEM-COAT-45-BLUE', 'size': 45, 'color': 'xanh'}]
    return variants, [
        {'name': 'catalog.search', 'args': {}, 'result': {'items': [
            {'sku': 'ITEM-COAT', 'name': 'Áo khoác Boreal', 'variants': variants}]}},
        {'name': 'inventory.check', 'args': {'sku': variants[0]['variant_sku'], 'on': '2032-05-09'},
         'result': {'sku': variants[0]['variant_sku'], 'in_stock': False, 'qty': 0}},
        {'name': 'pricing.get_quote', 'args': {'sku': variants[1]['variant_sku'], 'on': '2032-05-09'},
         'result': {'sku': variants[1]['variant_sku'], 'final_price_vnd': 740000}}]


def test_worker_does_not_turn_variant_reads_into_customer_selection():
    async def run():
        turn = source('Tôi muốn so sánh các lựa chọn, chưa chọn size hay màu.')
        repo, job, _, extractor, projection, transport = worker_fixture(turn)
        variants, observations = variant_reads()
        job['tool_observations'] = observations
        repo.variant_details = AsyncMock(side_effect=lambda conn, sku: next(
            ({**v, 'parent_sku': 'ITEM-COAT'} for v in variants if v['variant_sku'] == sku), None))
        with transport:
            await process_one(repo, extractor, projection)
            facts = await projection.list_facts(turn['customer_id'])
        assert job['status'] == 'completed'
        assert not {f['key'] for f in facts} & {'size', 'color', 'variant_sku'}
    asyncio.run(run())


def test_operational_replay_keeps_customer_selection_when_other_variants_are_read():
    async def run():
        turn = source('Các lựa chọn khác còn hàng không?')
        _, observations = variant_reads()
        selected = [{'key': key, 'value': value, 'scope_type': 'product',
            'scope_id': 'ITEM-COAT', 'revision': 1, 'source_kind': 'customer'}
            for key, value in [('size', 47), ('color', 'tím')]]
        repo = SimpleNamespace(owner=AsyncMock(return_value=turn['customer_id']),
            turn_count=AsyncMock(return_value=1), recent_session_turns=AsyncMock(return_value=[{
                'client_msg_id': turn['turn_id'], 'on_date': turn['on'],
                'customer_text': turn['customer_text'], 'agent_text': turn['agent_text'],
                'tool_observations': observations, 'job_id': 2, 'memory_status': 'pending'}]))
        facts = await _operational_facts(repo, None, turn['customer_id'],
            [turn['session_id']], deepcopy(selected), {}, {})
        assert {f['key']: f['value'] for f in facts} == {'size': 47, 'color': 'tím'}
    asyncio.run(run())


def test_confirmed_order_memory_supports_catalog_codes_without_a_sku_prefix():
    facts = verified_order_details({'name': 'order.create',
        'args': {'sku': 'CONTROL-81', 'payment': 'bank'},
        'result': {'status': 'created', 'order_id': 'ORDER-81'}}, None, source()['turn_id'])
    assert {f['key']: f['value'] for f in facts} == {
        'order_id': 'ORDER-81', 'product_advised': 'CONTROL-81', 'payment': 'bank'}


@pytest.mark.parametrize('receipt', [
    {'status': 'created'},
    {'status': 'created', 'order_id': ' '},
    {'status': 'created', 'order_id': 'ORDER-81', 'ok': False},
    {'status': 'created', 'order_id': 'ORDER-81', 'error': 'unavailable'},
])
def test_incomplete_or_failed_order_receipt_cannot_create_selection_memory(receipt):
    assert verified_order_details({'name': 'order.create',
        'args': {'sku': 'CONTROL-81', 'payment': 'bank'},
        'result': receipt}, None, source()['turn_id']) == []


@pytest.mark.parametrize('ttl,expected', [(20, False), (90, True)])
def test_configured_memory_freshness_reaches_prompt_and_scoped_facts(ttl, expected):
    from app.schemas.agent import TextTurnRequest
    from uuid import uuid4
    fact = {'key': 'budget_vnd', 'value': 740000, 'status': 'active',
        'source_kind': 'customer', 'on': '2033-05-01'}
    turn = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(), channel='hotline',
        channel_identity='0900000081', on=date(2033, 6, 15), text='Tôi hỏi lại ngân sách.', input_mode='clean')
    state = {'request': turn, 'safe_text': turn.text, 'identity_status': 'known',
        'customer_id': 'OWNER-INDEPENDENT', 'tool_calls': []}
    memory = SimpleNamespace(include_prior=True, fact_ttl_days=ttl,
        read_context=AsyncMock(return_value={'history': [], 'profile': {'budget_vnd': fact},
            'scoped_facts': {'product': {}, 'room': {'studio': {'budget_vnd': fact}}},
            'episodes': [], 'turn_count': 0}))
    loaded = asyncio.run(load_context(state, memory, None, lambda: None))
    context = prompt_context({**state, **loaded}, 6)
    assert ('budget_vnd' in context['customer_facts']) is expected
    assert bool(context['customer_facts'].get('rooms')) is expected
