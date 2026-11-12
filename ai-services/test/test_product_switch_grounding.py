"""Product switches must bind reads and replies without granting purchase consent."""
import asyncio
from copy import deepcopy

import pytest

from test_commerce_evidence import state, catalog, quote
from test_consultation_shortlist import clock
from app.agent.guardrails.checks import check_answer
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.mcp_servers.mcp_shared.consultation import derive_consultation


@pytest.mark.parametrize('new_sku,new_name', [
    ('SKU-BERYL-20', 'Beryl 20'), ('SKU-CEDAR-PRO', 'Cedar Pro'),
])
def test_price_inquiry_discovers_new_model_before_reusing_old_offer(new_sku, new_name):
    s = state(f'Kiểm tra giá {new_name} giúp tôi, chưa đặt hàng.')
    s['session_tool_calls'] = [catalog(), quote()]
    s['history'] = [{'customer': 'Hỏi Aster.', 'agent': 'Em đề xuất Aster giá 900.000đ.'}]

    class Gateway:
        async def invoke(self, name, args):
            if name == 'catalog.search':
                return deepcopy(catalog(new_sku, new_name)['result'])
            assert name == 'pricing.get_quote'
            assert args['sku'] == new_sku
            return deepcopy(quote(new_sku, 1700000)['result'])

    asyncio.run(BusinessTools(Gateway(), s, 6, clock).prepare_consultation())
    assert any(c['name'] == 'catalog.search' for c in s['tool_calls'])
    assert any(c['name'] == 'pricing.get_quote' and c['args']['sku'] == new_sku
               for c in s['tool_calls'])
    assert not derive_consultation(s).purchase_intent
    assert derive_consultation(s).snapshot.accepted_offer is None


@pytest.mark.parametrize('old_price,new_price', [(900000, 1700000), (900000, 900000)])
def test_verifier_rejects_other_product_even_when_its_quote_is_valid(old_price, new_price):
    s = state('Beryl 20 hiện giá bao nhiêu?')
    s['session_tool_calls'] = [catalog(), quote(price=old_price), catalog('SKU-BERYL', 'Beryl 20')]
    s['tool_calls'] = [quote('SKU-BERYL', new_price)]
    s['agent_draft'] = f'Aster giá {old_price:,}đ.'.replace(',', '.')
    calls = build_commerce_evidence(s)
    assert check_answer(s['agent_draft'], calls, s['safe_text'])[1] is not None
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert 'Aster' not in result['agent_text']
    assert 'Beryl 20' in result['agent_text']
    assert f'{new_price:,}'.replace(',', '.') in result['agent_text']


def test_unknown_explicit_model_does_not_reuse_previous_product_scope():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope
    s = state('Cedar 99 giá bao nhiêu?')
    s['session_tool_calls'] = [catalog(), quote()]
    s['history'] = [{'customer': 'Hỏi Aster.', 'agent': 'Em đề xuất Aster giá 900.000đ.'}]
    s['consultation_scope'] = {'skus': ['SKU-ASTER'], 'focus_sku': 'SKU-ASTER', 'known': True}
    assert not consultation_scope(s)['known']


def test_unknown_model_cannot_be_answered_with_a_valid_old_price():
    s = state('Cedar 99 giá bao nhiêu?')
    s['session_tool_calls'] = [catalog(), quote()]
    s['history'] = [{'customer': 'Hỏi Aster.', 'agent': 'Em đề xuất Aster giá 900.000đ.'}]
    s['agent_draft'] = 'Aster giá 900.000đ.'
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert '900.000' not in result['agent_text']


def test_promotion_for_old_product_cannot_answer_new_product_question():
    old = quote()
    old['result']['freeship'] = True
    calls = [catalog(), old, catalog('SKU-BERYL', 'Beryl 20'), quote('SKU-BERYL', 1700000)]
    assert check_answer('Aster được miễn phí vận chuyển.', calls,
                        'Beryl 20 có ưu đãi gì?')[1] is not None


def test_failed_new_quote_cannot_fall_back_to_old_product_price():
    s = state('Beryl 20 giá bao nhiêu?')
    s['session_tool_calls'] = [catalog(), quote(), catalog('SKU-BERYL', 'Beryl 20')]
    s['tool_calls'] = [{'name': 'pricing.get_quote', 'args': quote('SKU-BERYL')['args'],
                        'result': {'error': 'unavailable'}}]
    s['agent_draft'] = 'Aster giá 900.000đ.'
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert '900.000' not in result['agent_text']


def test_comparison_can_keep_two_independently_quoted_products():
    calls = [catalog(), quote(), catalog('SKU-BERYL', 'Beryl 20'), quote('SKU-BERYL', 1700000)]
    answer = 'Aster giá 900.000đ. Beryl 20 giá 1.700.000đ.'
    assert check_answer(answer, calls, 'So sánh giá Aster và Beryl 20.')[1] is None


@pytest.mark.parametrize('text', ['Có ưu đãi mã RUN-10 không?', 'Có ship COD không, tôi ở q7 hcm?'])
def test_coupon_and_address_are_not_new_product_identifiers(text):
    from app.agent.harness.catalog_query import explicit_product_queries
    assert explicit_product_queries(text) == []


def test_generic_price_is_bound_to_customer_model_not_stale_focus():
    calls = [catalog(), quote(), catalog('SKU-BERYL', 'Beryl 20'), quote('SKU-BERYL', 1700000)]
    assert check_answer('Giá hiện tại là 900.000đ.', calls,
                        'Beryl 20 giá bao nhiêu?', focus_sku='SKU-ASTER')[1] is not None
    assert check_answer('Giá hiện tại là 1.700.000đ.', calls,
                        'Beryl 20 giá bao nhiêu?', focus_sku='SKU-ASTER')[1] is None


def test_historical_price_does_not_block_current_product_quote():
    calls = [catalog(), quote(), catalog('SKU-BERYL', 'Beryl 20'), quote('SKU-BERYL', 1700000)]
    answer = 'Lần trước Aster giá 900.000đ. Beryl 20 hiện giá 1.700.000đ.'
    assert check_answer(answer, calls, 'Beryl 20 giá bao nhiêu?')[1] is None


def test_wrong_previous_agent_reply_cannot_replace_customer_product_focus():
    s = state('Chỉ kiểm tra lại báo giá và ưu đãi hôm nay thôi.')
    s['session_tool_calls'] = [catalog(), quote(), catalog('SKU-BERYL', 'Beryl 20')]
    s['tool_calls'] = [quote('SKU-BERYL', 1700000)]
    s['history'] = [{'customer': 'Beryl 20 giá bao nhiêu?', 'agent': 'Em đề xuất Aster giá 900.000đ.'}]
    s['agent_draft'] = 'Aster giá 900.000đ.'
    assert derive_consultation(s).focus_sku == 'SKU-BERYL'
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert 'Aster' not in result['agent_text']
    assert '1.700.000' in result['agent_text']


def test_requested_alternative_can_replace_previous_recommendation():
    s = state('Giá mẫu đó hiện bao nhiêu?')
    s['session_tool_calls'] = [catalog(), quote(), catalog('SKU-BERYL', 'Beryl 20')]
    s['tool_calls'] = [quote('SKU-BERYL', 1700000)]
    s['history'] = [{'customer': 'Aster không hợp, tìm mẫu khác giúp tôi.',
                     'agent': 'Em đề xuất Beryl 20 giá 1.700.000đ.'}]
    assert derive_consultation(s).focus_sku == 'SKU-BERYL'


def test_new_day_without_fresh_quote_does_not_reuse_old_day_price():
    from datetime import date
    s = state('Beryl 20 hôm nay giá bao nhiêu?')
    s['request'] = s['request'].model_copy(update={'on': date(2026, 11, 6)})
    s['session_tool_calls'] = [catalog('SKU-BERYL', 'Beryl 20'), quote('SKU-BERYL', 1700000)]
    s['agent_draft'] = 'Beryl 20 hiện giá 1.700.000đ.'
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert '1.700.000' not in result['agent_text']


@pytest.mark.parametrize('new_name,new_price', [('Orion 24', 2300000), ('Vega Pro', 900000)])
@pytest.mark.parametrize('lookup', ['ok', 'empty', 'unavailable'])
def test_shared_runtime_replaces_stale_model_answer_without_side_effects(new_name, new_price, lookup):
    from types import SimpleNamespace
    from unittest.mock import patch
    from langchain_core.messages import AIMessage
    s = state(f'Báo giá {new_name} giúp tôi, chỉ tham khảo thôi.')
    s['session_tool_calls'] = [catalog(), quote()]
    s['history'] = [{'customer': 'Hỏi Aster.', 'agent': 'Em đề xuất Aster giá 900.000đ.'}]
    invoked = []

    async def invoke(name, args, *_args, **_kwargs):
        invoked.append((name, dict(args)))
        if name == 'catalog.search':
            if lookup == 'empty':
                return {'items': [], 'total': 0}
            if lookup == 'unavailable':
                return {'error': 'unavailable'}
            return deepcopy(catalog('SKU-NEW-MODEL', new_name)['result'])
        assert name == 'pricing.get_quote'
        assert args['sku'] == 'SKU-NEW-MODEL'
        return deepcopy(quote('SKU-NEW-MODEL', new_price)['result'])

    class Agent:
        async def ainvoke(self, *_args, **_kwargs):
            return {'messages': [AIMessage(content='Aster giá 900.000đ.')]}

    async def run():
        node = AgentNodes(None, SimpleNamespace(invoke_trusted=invoke), None, 6, 6, clock=clock)
        s.update(await node.run_agent(s))
        return await node.verify_agent(s)

    before = deepcopy(s['history'])
    with patch('app.agent.harness.agent_nodes.build_agent', return_value=Agent()), \
         patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
        result = asyncio.run(run())
    assert 'Aster' not in result['agent_text']
    if lookup == 'ok':
        assert new_name in result['agent_text']
        assert f'{new_price:,}'.replace(',', '.') in result['agent_text']
    assert s['history'] == before
    assert all(name in {'catalog.search', 'pricing.get_quote'} for name, _ in invoked)
    assert not derive_consultation(s).purchase_intent
