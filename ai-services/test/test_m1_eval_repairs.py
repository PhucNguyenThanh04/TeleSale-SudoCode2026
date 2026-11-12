"""Regressions from BTC public inputs, using the actual tool and verifier boundary."""
import asyncio
import json
from pathlib import Path

import pytest

from btc_data import btc_data_dir
from test_commerce_evidence import state
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.mcp_servers.mcp_shared.commerce_rules import _catalog


PRODUCTS = json.loads((btc_data_dir() / 'catalog/products.json').read_text())['products']


@pytest.mark.parametrize('query,category,expected', [
    ('Urban Classic', 'giày sneaker', 'SKU-SN-CAS'),
    ('RunLite 2 Pro', 'giày chạy bộ', 'SKU-SN-RUN2'),
    ('Xiaomi 4 Pro', 'máy lọc không khí', 'SKU-XM-4P'),
    ('Xiaomi 4 Pro', 'may loc khong khi', 'SKU-XM-4P'),
])
def test_customer_category_is_translated_before_catalog_filter(query, category, expected):
    s = state()
    s['decision'] = Decision(action='tool', tool_name='catalog.search',
                             tool_args={'query': query, 'category': category})
    name, args = prepare_tool_call(s, lambda: None)
    result = _catalog(PRODUCTS, args)
    assert result['items'], args
    assert result['items'][0]['sku'] == expected


def test_category_repair_preserves_hard_constraints_and_unknown_categories():
    s = state()
    for category in ['giày chạy bộ', 'unknown/category']:
        s['decision'] = Decision(action='tool', tool_name='catalog.search',
            tool_args={'query': 'RunLite 2 Pro', 'category': category, 'max_price_vnd': 100})
        _, args = prepare_tool_call(s, lambda: None)
        assert args['max_price_vnd'] == 100
        assert _catalog(PRODUCTS, args)['items'] == []
        if category.startswith('unknown'): assert args['category'] == category


def test_actual_policy_recovery_is_not_rejected_as_product_price():
    from app.agent.harness.session_nodes import safe_followup_reply
    from app.agent.guardrails.checks import check_answer, _money_claims
    # Public changelog is applicable even when the order date is unknown.
    content = (btc_data_dir() / 'policy/changelog.md').read_text()
    section = content.split('[CL-01]', 1)[-1].split('[CL-02]', 1)[0]
    s = state('Bên em cho đổi trả trong 14 ngày đúng không?')
    s['tool_calls'] = [{'name': 'policy.search',
        'args': {'query': 'Bên em cho đổi trả trong 14 ngày đúng không', 'on': '2026-11-05'},
        'result': {'retrieval_status': 'ok', 'evidence': [{
            'content': section, 'evidence_type': 'business_rule',
            'applicability': {'status': 'applicable'}}]}}]
    answer = safe_followup_reply(s)
    assert '7 ngày' in answer
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None, (answer, _money_claims(answer), _money_claims(section))


@pytest.mark.parametrize('text', ['Đơn tạo trước 01/10/2026 vẫn áp dụng bản cũ.',
    'Thời hạn 7 ngày kể từ ngày nhận hàng.', 'Chính sách 2026-10 có hiệu lực.',
    'Đổi mới 30 ngày đối với lỗi nhà sản xuất.'])
def test_policy_dates_and_durations_are_not_money(text):
    from app.agent.guardrails.checks import _money_claims
    assert _money_claims(text) == []


def test_sc07_saved_policy_response_survives_real_verifier():
    from datetime import date
    from app.agent.harness.session_nodes import safe_followup_reply
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.guardrails.checks import check_answer, _money_claims
    s = state('Bên em cho đổi trả trong 14 ngày đúng không? Chị đọc trên web thấy thế.')
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 15)})
    s['tool_calls'] = [json.loads((Path(__file__).parent / 'fixtures/m1_policy_search.json').read_text())]
    answer = safe_followup_reply(s)
    assert '7 ngày' in answer
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None, (answer, _money_claims(answer))
    s['agent_draft'] = 'Chính sách đổi trả là 999 ngày.'
    s['followup_kind'] = 'policy'
    result = asyncio.run(AgentNodes(None, None, None, 6, 6).verify_agent(s))
    assert '7 ngày' in result['agent_text'], result


@pytest.mark.parametrize('on,address,expected', [
    ('2026-10-18', None, '2026-10-22'),
    ('2026-10-24', 'Hà Nội', '2026-10-28'),
])
def test_quote_exposes_same_delivery_estimate_as_order(on, address, expected):
    from app.mcp_servers.mcp_catalog.services.catalog import get_quote
    from app.mcp_servers.mcp_shared.commerce_rules import _delivery
    class Repo:
        async def rows(self, session, table):
            return PRODUCTS if table == 'products' else []
        async def identity_matches(self, *args): return []
        async def used_promos(self, *args): return set()
    result = asyncio.run(get_quote(Repo(), None, {'sku': 'SKU-AP-X', 'on': on, 'address': address}))
    assert result.get('estimated_delivery') == expected == _delivery(on, address)


@pytest.mark.parametrize('estimated', ['2026-11-07', '2026-11-09', None, 'invalid', '2026-11-04'])
def test_week_delivery_preference_does_not_require_delivery_estimate(estimated):
    from test_commerce_evidence import catalog, quote, stock
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s = state('Mua Aster giá 900.000đ, giao trong tuần này nhé.')
    q = quote()
    q['result']['estimated_delivery'] = estimated
    s['tool_calls'] = [catalog(), q, stock()]
    reason = purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000})
    assert reason is None


def test_estimate_does_not_authorize_extra_delivery_conditions_or_wrong_address():
    from test_commerce_evidence import catalog, quote, stock
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    for text, address in [
        ('Mua Aster giá 900.000đ, giao trong tuần này trước 8 giờ nhé.', None),
        ('Mua Aster giá 900.000đ, giao trong tuần này nhé.', 'Hà Nội'),
    ]:
        s = state(text)
        q = quote()
        q['result']['estimated_delivery'] = '2026-11-07'
        s['tool_calls'] = [catalog(), q, stock()]
        args = {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}
        if address: args['address'] = address
        assert purchase_block_reason(s, args) is not None


def test_policy_recovery_does_not_copy_competitor_instructions():
    from datetime import date
    from app.agent.harness.session_nodes import safe_followup_reply
    s = state('Bên em cho đổi trả trong 14 ngày đúng không?')
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 15)})
    s['tool_calls'] = [json.loads((Path(__file__).parent / 'fixtures/m1_policy_search.json').read_text())]
    answer = safe_followup_reply(s)
    assert 'đối thủ' not in answer
    assert 'playbook' not in answer.lower()
    from eval_harness.extractor import extract_claims
    claims = extract_claims(answer, s['tool_calls'])
    assert not any(c['field'] == 'exchange_fee_vnd' and c['value'] == 20000 for c in claims), claims


def test_actual_model_tool_accepts_customer_category_and_preserves_trace_contract():
    from app.agent.implementations.business_agent import BusinessTools
    class Gateway:
        async def invoke_trusted(self, name, args, *a, **kw):
            assert name == 'catalog.search'
            return _catalog(PRODUCTS, args)
    s = state('Tôi muốn xem Urban Classic size 39 màu đen.')
    tools = BusinessTools(Gateway(), s, 6, lambda: None)
    search = next(t for t in tools.langchain_tools() if t.name == 'catalog_search')
    result = asyncio.run(search.ainvoke({'query': 'Urban Classic', 'category': 'giày sneaker'}))
    assert result['items'][0]['sku'] == 'SKU-SN-CAS'
    assert s['tool_calls'][0]['name'] == 'catalog.search'
    assert s['tool_calls'][0]['args']['category'] == 'thoi-trang/giay'


def test_public_price_and_stock_rules_match_btc_across_dates_and_variants():
    import importlib.util
    from app.mcp_servers.mcp_shared.commerce_rules import quote, _inventory
    root = btc_data_dir()
    spec = importlib.util.spec_from_file_location('m1_btc_reference', root / 'eval/mock_tools.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    promos = json.loads((root / 'catalog/promotions.json').read_text())['promotions']
    events = json.loads((root / 'catalog/inventory_timeline.json').read_text())['events']
    skus = [s for p in PRODUCTS for s in [p['sku'], *(v['variant_sku'] for v in p['variants'])]]
    for sku in skus:
        for on in ['2026-09-25', '2026-10-15', '2026-10-20', '2026-10-27']:
            assert _inventory(PRODUCTS, events, sku, on) == reference.inventory_check(sku, on)
            for address in [None, 'Quận 7 HCM']:
                args = {'sku': sku, 'on': on, 'address': address}
                expected = reference.pricing_get_quote(**args)
                expected.pop('_internal_price_floor_vnd')
                assert quote(PRODUCTS, promos, args) == expected, (sku, on, address)


def test_stockless_quote_has_no_delivery_estimate():
    from app.mcp_servers.mcp_catalog.services.catalog import get_quote
    class Repo:
        async def rows(self, session, table):
            if table == 'products': return PRODUCTS
            if table == 'inventory_events':
                return [{'sku': 'SKU-XM-4P', 'date': '2026-10-15', 'qty': 0}]
            return []
        async def identity_matches(self, *args): return []
        async def used_promos(self, *args): return set()
    result = asyncio.run(get_quote(Repo(), None, {'sku': 'SKU-XM-4P', 'on': '2026-10-15'}))
    assert 'estimated_delivery' not in result


@pytest.mark.parametrize('answer,accepted', [
    ('Aster dự kiến giao ngày 2026-11-07.', True),
    ('Aster dự kiến giao ngày 2026-11-08.', False),
    ('Cam kết Aster giao ngày 2026-11-07.', False),
])
def test_delivery_answer_uses_quote_as_estimate_not_guarantee(answer, accepted):
    from test_commerce_evidence import catalog, quote
    from app.agent.guardrails.checks import check_answer
    q = quote()
    q['result']['estimated_delivery'] = '2026-11-07'
    result = check_answer(answer, [catalog(), q], focus_sku='SKU-ASTER')
    assert (result[1] is None) is accepted


def test_unmet_delivery_deadline_offers_sourced_date_without_creating_order():
    from test_commerce_evidence import catalog, quote, stock
    from app.agent.harness.session_nodes import safe_consultation_reply
    from app.agent.guardrails.checks import check_answer
    s = state('Mua Aster giá 900.000đ, bắt buộc giao trong tuần này.')
    q = quote()
    q['result']['estimated_delivery'] = '2026-11-09'
    s['tool_calls'] = [catalog(), q, stock()]
    answer = safe_consultation_reply(s)
    assert '2026-11-09' in answer and '?' in answer
    assert check_answer(answer, s['tool_calls'], s['safe_text'], focus_sku='SKU-ASTER')[1] is None
    assert not any(c['name'] == 'order.create' for c in s['tool_calls'])


@pytest.mark.parametrize('text', [
    'Mua Aster giá 900.000đ, giao trước thứ sáu, giao trong tuần này nhé.',
    'Mua Aster giá 900.000đ, trước 8 giờ, giao trong tuần này nhé.',
])
def test_week_constraint_does_not_erase_another_deadline(text):
    from test_commerce_evidence import catalog, quote, stock
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s = state(text)
    q = quote()
    q['result']['estimated_delivery'] = '2026-11-07'
    s['tool_calls'] = [catalog(), q, stock()]
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) == 'delivery_confirmation_required'


def test_all_saved_empty_catalog_queries_recover_without_dropping_filters():
    cases = json.loads((Path(__file__).parent / 'fixtures/m1_empty_catalog_queries.json').read_text())
    assert len(cases) == 15
    for case in cases:
        s = state()
        s['decision'] = Decision(action='tool', tool_name='catalog.search', tool_args=case['args'])
        _, args = prepare_tool_call(s, lambda: None)
        result = _catalog(PRODUCTS, args)
        assert result['items'], case
        for key in ['max_price_vnd', 'min_room_area_m2']:
            assert args.get(key) == case['args'].get(key)
