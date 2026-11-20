import asyncio
from copy import deepcopy

import pytest

from test_commerce_evidence import state, catalog, quote
from test_consultation_shortlist import clock
from app.agent.guardrails.checks import check_answer
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence




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






def test_new_day_without_fresh_quote_does_not_reuse_old_day_price():
    from datetime import date
    s = state('Beryl 20 hôm nay giá bao nhiêu?')
    s['request'] = s['request'].model_copy(update={'on': date(2026, 11, 6)})
    s['session_tool_calls'] = [catalog('SKU-BERYL', 'Beryl 20'), quote('SKU-BERYL', 1700000)]
    s['agent_draft'] = 'Beryl 20 hiện giá 1.700.000đ.'
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert '1.700.000' not in result['agent_text']
