"""An inquiry is not a selection; writes wait for an unambiguous customer choice."""
from copy import deepcopy
from uuid import uuid4

import pytest

from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations
from test_m1_round2 import Gateway, run_node
from app.mcp_servers.mcp_shared.consultation import committed_consultation, derive_consultation
from app.mcp_servers.mcp_shared.presented_offers import derive_presented_offers


def offered_state(*, returning=False, multiple=True, selected=False, legacy=False, recommended=False):
    s = state('Lấy mẫu đó, lên đơn.')
    s['history'] = [{'customer': 'Tôi chọn Aster để xem giá.' if selected else 'Giá Aster bao nhiêu?',
        'agent': ('Em đề xuất ' if recommended else '') + 'Aster giá 900.000đ.' + (' Brio giá 800.000đ.' if multiple else '')}]
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    if multiple:
        s['session_tool_calls'] += [catalog('SKU-BRIO', 'Brio'), quote('SKU-BRIO', 800000), stock('SKU-BRIO')]
    bind_history_observations(s)
    if returning:
        sid = str(s['request'].session_id)
        turn = {'customer_id': s['customer_id'], 'session_id': sid,
            'turn_id': s['history'][0]['source_turn_id'], 'on': '2026-11-05',
            'customer_text': s['history'][0]['customer'], 'agent_text': s['history'][0]['agent']}
        snapshot = committed_consultation(s['customer_id'], sid, [turn], s['session_tool_calls'])
        candidates = derive_presented_offers(customer_id=s['customer_id'], session_id=sid,
            committed_turns=[turn], tool_calls=s['session_tool_calls'])
        if legacy:
            snapshot.presented_offer = candidates[0]
            snapshot.source_refs['presented_offer'] = candidates[0].sources['price'].agent
        s['episodes'] = [{'customer_id': s['customer_id'], 'session_id': sid, 'on': '2026-11-05',
            'topics': [{'scope_type': 'global', 'consultation': snapshot.model_dump(mode='json')}],
            'offer_candidates': [o.model_dump(mode='json') for o in candidates]}]
        s['request'] = s['request'].model_copy(update={'session_id': uuid4()})
        s['tool_calls'] = [{k: deepcopy(v) for k, v in c.items()
            if k not in {'customer_id', 'session_id', 'source_turn_id'}} for c in s['session_tool_calls']]
        s['session_tool_calls'], s['history'] = [], []
    return s


@pytest.mark.parametrize('returning', [False, True])
@pytest.mark.parametrize('recommended', [False, True])
def test_ambiguous_choice_asks_before_write_then_named_choice_can_buy(returning, recommended):
    s = offered_state(returning=returning, recommended=recommended)
    gateway = Gateway([catalog(), catalog('SKU-BRIO', 'Brio')])
    result = run_node(s, gateway, 'Em kiểm tra giúp mình.', [
        ('order.create', {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000})])
    assert not any(name == 'order.create' for name, _ in gateway.calls)
    assert 'mẫu nào' in result['agent_text'].lower()
    assert derive_consultation(s).snapshot.selected_sku is None
    s['history'].append({'customer': s['safe_text'], 'agent': result['agent_text'], 'source_turn_id': str(uuid4())})
    s['session_tool_calls'] += s['tool_calls'];s['tool_calls'] = [];s['tool_count'] = 0
    s['safe_text'] = 'Lấy Brio, lên đơn.'
    s['request'] = s['request'].model_copy(update={'client_msg_id': uuid4(), 'text': s['safe_text']})
    result = run_node(s, gateway, 'Em kiểm tra giúp mình.')
    orders = [args for name, args in gateway.calls if name == 'order.create']
    assert len(orders) == 1 and orders[0]['sku'] == 'SKU-BRIO' and orders[0]['price_vnd'] == 800000
    assert 'OD-OFFLINE' in result['agent_text']


@pytest.mark.parametrize('returning', [False, True])
@pytest.mark.parametrize('multiple,selected', [(False, False), (True, True)])
def test_unique_offer_or_explicit_customer_choice_keeps_valid_permission(returning, multiple, selected):
    s = offered_state(returning=returning, multiple=multiple, selected=selected)
    assert derive_consultation(s).snapshot.accepted_offer.price_vnd == 900000
    gateway = Gateway([catalog(), catalog('SKU-BRIO', 'Brio')])
    result = run_node(s, gateway, 'Em kiểm tra giúp mình.')
    orders = [args for name, args in gateway.calls if name == 'order.create']
    assert len(orders) == 1 and orders[0]['sku'] == 'SKU-ASTER'
    assert 'OD-OFFLINE' in result['agent_text']


def test_legacy_focused_snapshot_does_not_hide_its_same_turn_sibling_offer():
    s = offered_state(returning=True, legacy=True)
    d = derive_consultation(s)
    assert d.snapshot.accepted_offer is None and d.snapshot.selected_sku is None
