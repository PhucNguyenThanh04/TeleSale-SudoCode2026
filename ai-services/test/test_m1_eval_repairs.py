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




@pytest.mark.parametrize('text', ['Đơn tạo trước 01/10/2026 vẫn áp dụng bản cũ.',
    'Thời hạn 7 ngày kể từ ngày nhận hàng.', 'Chính sách 2026-10 có hiệu lực.',
    'Đổi mới 30 ngày đối với lỗi nhà sản xuất.'])
def test_policy_dates_and_durations_are_not_money(text):
    from app.agent.guardrails.checks import _money_claims
    assert _money_claims(text) == []




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
