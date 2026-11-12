"""Shortlist behavior from sourced catalog and customer turns, never eval labels."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.agent import TextTurnRequest
from app.agent.implementations.business_agent import BusinessTools


def products():
    return [
        {'sku': 'SKU-ASTER', 'name': 'Aster Air', 'category': 'air', 'variants': [],
         'list_price_vnd': 5200000, 'attributes': {'room_area_m2': 30, 'child_safe_lock': True}},
        {'sku': 'SKU-BERYL', 'name': 'Beryl Air', 'category': 'air', 'variants': [],
         'list_price_vnd': 4800000, 'attributes': {'room_area_m2': 25, 'child_safe_lock': False}},
        {'sku': 'SKU-CEDAR', 'name': 'Cedar Air', 'category': 'air', 'variants': [],
         'list_price_vnd': 3200000, 'attributes': {'room_area_m2': 15}},
    ]


def consultation_state(text='Nhà có bé nhỏ, ngân sách khoảng 5 triệu.', items=None):
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel='hotline',
        channel_identity='0900000000', on=date(2026, 11, 5), text=text, input_mode='clean')
    source = str(uuid4())
    catalog = {'name': 'catalog.search', 'args': {'category': 'air', 'min_room_area_m2': 25},
        'result': {'items': deepcopy(products() if items is None else items)},
        'customer_id': 'C-SHORTLIST', 'session_id': str(request.session_id), 'source_turn_id': source}
    return {'request': request, 'safe_text': text, 'customer_id': 'C-SHORTLIST',
        'customer_phone': '0900000000', 'identity_status': 'known', 'tool_calls': [],
        'tool_count': 0, 'session_tool_calls': [catalog],
        'history': [{'source_turn_id': source, 'customer': 'Tư vấn máy lọc không khí cho phòng 25m2.',
                     'agent': 'Có Aster Air và Beryl Air để mình cân nhắc.'}]}


class QuoteGateway:
    def __init__(self, items=None):
        self.items = products() if items is None else items
        self.calls = []
        self.fail = False

    async def invoke(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return {'items': deepcopy([p for p in self.items if not args.get('sku') or p['sku'] == args['sku']])}
        assert name == 'pricing.get_quote', name
        if self.fail: return {'error': 'unavailable'}
        price = next(p['list_price_vnd'] for p in self.items if p['sku'] == args['sku'])
        return {'sku': args['sku'], 'final_price_vnd': price, 'applied_promos': [], 'freeship': False}


def clock(): return datetime(2026, 11, 5, tzinfo=timezone.utc)


def test_budget_followup_uses_previous_catalog_without_new_search():
    state = consultation_state()
    gateway = QuoteGateway()
    business = BusinessTools(gateway, state, 6, clock)
    assert asyncio.run(business.prepare_consultation())
    assert gateway.calls and gateway.calls[0][0] == 'pricing.get_quote'
    assert gateway.calls[0][1]['sku'] == 'SKU-ASTER'
    assert all(name != 'catalog.search' for name, _ in gateway.calls)
    assert state.get('tool_count') <= 2


def test_preparation_shortlist_is_independent_of_catalog_order():
    orders = []
    for items in (products(), list(reversed(products()))):
        state = consultation_state(items=items)
        gateway = QuoteGateway(items)
        business = BusinessTools(gateway, state, 6, clock)
        asyncio.run(business.prepare_consultation())
        orders.append([args['sku'] for name, args in gateway.calls if name == 'pricing.get_quote'])
    assert orders[0] == orders[1] and orders[0][0] == 'SKU-ASTER'
    assert 'SKU-CEDAR' not in orders[0]


def test_shortlist_preserves_scope_before_a_broad_search():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    state = consultation_state()
    scope = consultation_scope(state)
    unrelated = {'sku': 'SKU-UNRELATED', 'name': 'Travel Buggy', 'category': 'stroller',
                 'list_price_vnd': 100000, 'variants': [], 'attributes': {}}
    state['tool_calls'].append({'name': 'catalog.search', 'args': {'query': 'Alo hôm trước'},
        'result': {'items': [unrelated, *products()]}})
    shortlist = build_shortlist(state, scope=scope)
    assert shortlist.scope_known
    assert [p['sku'] for p in shortlist.items][:1] == ['SKU-ASTER']
    assert 'SKU-UNRELATED' not in [p['sku'] for p in shortlist.items]


def test_shortlist_unknown_required_attribute_and_soft_child_preference():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    state = consultation_state('Ngân sách khoảng 5 triệu, bắt buộc có khóa trẻ em.')
    result = build_shortlist(state, scope=consultation_scope(state))
    assert [p['sku'] for p in result.items] == ['SKU-ASTER']
    state['session_tool_calls'][0]['result']['items'][0]['attributes'].pop('child_safe_lock')
    result = build_shortlist(state, scope=consultation_scope(state))
    assert not result.items and result.missing_fields


def test_preparation_repeated_does_not_retry_failed_quotes_or_expand_budget():
    state = consultation_state()
    state['tool_calls'] = state.pop('session_tool_calls')
    gateway = QuoteGateway(); gateway.fail = True
    business = BusinessTools(gateway, state, 6, clock)
    async def run():
        await business.prepare_consultation()
        await business.prepare_consultation()
    asyncio.run(run())
    assert 0 < len(gateway.calls) <= 2
    assert len({args['sku'] for _, args in gateway.calls}) == len(gateway.calls)


def test_explicit_product_type_change_does_not_reuse_old_scope():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    s = consultation_state()
    s['consultation_scope'] = consultation_scope(s)
    s['safe_text'] = 'Tôi muốn đổi sang xe đẩy.'
    s['request'] = s['request'].model_copy(update={'text': s['safe_text']})
    assert not consultation_scope(s)['known']
    buggy = {'sku': 'SKU-BUGGY', 'name': 'Travel Buggy', 'category': 'stroller',
             'variants': [], 'list_price_vnd': 1000000, 'attributes': {}}
    s['tool_calls'] = [{'name': 'catalog.search', 'args': {'query': 'xe đẩy', 'category': 'stroller'},
                       'result': {'items': [buggy]}}]
    scope = consultation_scope(s)
    assert scope['category'] == 'stroller'
    assert [i['sku'] for i in build_shortlist(s, scope=scope).items] == ['SKU-BUGGY']


@pytest.mark.parametrize('quoted_price', [4500000, 5300000])
def test_final_quote_drives_ranking_without_mutating_evidence(quoted_price):
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    s = consultation_state('Ngân sách khoảng 5 triệu.')
    scope = consultation_scope(s)
    s['tool_calls'] = [{'name': 'pricing.get_quote', 'args': {'sku': sku, 'qty': 1, 'on': '2026-11-05'},
        'result': {'sku': sku, 'final_price_vnd': price}} for sku, price in
        [('SKU-ASTER', quoted_price), ('SKU-BERYL', 4800000)]]
    before = deepcopy(s)
    result = build_shortlist(s, scope=scope, quoted_only=True)
    assert result.items[0]['sku'] == ('SKU-ASTER' if quoted_price < 5000000 else 'SKU-BERYL')
    assert s == before


def test_child_safety_from_memory_outranks_budget_without_relaxing_room_area():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    items = products()
    items[2]['attributes']['child_safe_lock'] = True
    s = consultation_state('Ngân sách khoảng 5 triệu.', items=items)
    s['profile'] = {'has_children': {'value': True}}
    result = build_shortlist(s, scope=consultation_scope(s))
    assert [item['sku'] for item in result.items] == ['SKU-ASTER', 'SKU-BERYL']


def test_float_area_unknown_required_attributes_and_budget_basis():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    s = consultation_state('Ngân sách 5 triệu cho 2 chiếc, phòng 25,5m2.')
    result = build_shortlist(s, scope=consultation_scope(s))
    assert 'budget_basis' in result.missing_fields
    assert [i['sku'] for i in result.items] == ['SKU-ASTER']
    s['session_tool_calls'][0]['result']['items'][0]['attributes'].pop('room_area_m2')
    result = build_shortlist(s, scope=consultation_scope(s))
    assert not result.items and 'room_area_m2' in result.missing_fields


def test_failed_targeted_refresh_does_not_revive_catalog_metadata():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    s = consultation_state('Tôi muốn xem giá Aster Air.')
    scope = consultation_scope(s)
    s['tool_calls'] = [{'name': 'catalog.search', 'args': {'sku': 'SKU-ASTER'},
                       'result': {'error': 'unavailable'}}]
    assert not build_shortlist(s, scope=scope).items


def test_new_budget_can_reconsider_agent_recommendation_but_not_customer_selection():
    from app.mcp_servers.mcp_shared.consultation_shortlist import consultation_scope, build_shortlist
    s = consultation_state('Ngân sách tối đa 5 triệu thôi.')
    s['history'][0]['agent'] = 'Em đề xuất Aster Air có giá 5.200.000đ.'
    result = build_shortlist(s, scope=consultation_scope(s))
    assert result.items[0]['sku'] == 'SKU-BERYL'
    s['history'].append({'source_turn_id': str(uuid4()), 'customer': 'Tôi chọn Aster Air.',
                         'agent': 'Em ghi nhận mẫu mình chọn.'})
    result = build_shortlist(s, scope=consultation_scope(s))
    assert [item['sku'] for item in result.items] == ['SKU-ASTER']


@pytest.mark.parametrize('text', [
    'Tìm lại mẫu phù hợp nhất với ngân sách tối đa 5 triệu.',
    'Em tìm trong danh mục giúp anh mẫu có khóa trẻ em.',
])
def test_alternative_search_does_not_override_customer_selection(text):
    from app.mcp_servers.mcp_shared.consultation_shortlist import catalog_search_requested
    s = consultation_state(text)
    assert catalog_search_requested(s)
    s['history'].append({'source_turn_id': str(uuid4()), 'customer': 'Tôi chọn Aster Air.',
                         'agent': 'Em ghi nhận mẫu mình chọn.'})
    assert not catalog_search_requested(s)


@pytest.mark.parametrize('text', [
    'Chưa cần tìm lại mẫu khác, ngân sách vẫn 5 triệu.',
    'Đừng tìm mẫu khác nhé.',
    'Nếu tìm mẫu khác trong tầm 5 triệu thì sao?',
    'Tìm lại giá mẫu Aster Air giúp tôi.',
])
def test_alternative_search_requires_current_unambiguous_request(text):
    from app.mcp_servers.mcp_shared.consultation_shortlist import catalog_search_requested
    assert not catalog_search_requested(consultation_state(text))
