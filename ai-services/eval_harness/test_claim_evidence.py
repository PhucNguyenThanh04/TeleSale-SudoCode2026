"""Ground-truth mismatches are not automatically unsupported tool claims."""
from copy import deepcopy

import pytest

from eval_harness.claim_evidence import explain_claim_mismatch


def row(field='price_vnd', value=2990000):
    text = 'Xiaomi giá 2.990.000đ.' if field == 'price_vnd' else 'Xiaomi đang có quà tặng.'
    return {'agent_text': text, 'claims': [{'field': field, 'value': value, 'text': text}],
        'tool_calls': [
            {'name': 'catalog.search', 'result': {'items': [{'sku': 'SKU-X', 'name': 'Xiaomi'}]}},
            {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-X', 'on': '2026-10-18'},
             'result': {'sku': 'SKU-X', 'final_price_vnd': 2990000,
                        'applied_promos': [{'type': 'gift', 'promo_code': 'GIFT',
                                            'gift_sku': 'SKU-FILTER', 'valid_until': '2026-10-22'}]}}]}


@pytest.mark.parametrize('field,value', [('price_vnd', 2990000), ('promo_active', True)])
def test_quote_supported_mismatch_keeps_claim_and_quote_unchanged(field, value):
    r = row(field, value)
    before = deepcopy(r)
    assert explain_claim_mismatch(r, field, value, on='2026-10-18') == {
        'status': 'supported_by_quote', 'sku': 'SKU-X'}
    assert r == before


@pytest.mark.parametrize('change', ['stale', 'failed', 'wrong_sku', 'different_product', 'ambiguous', 'expired_gift'])
def test_incompatible_quotes_cannot_clear_a_ground_truth_mismatch(change):
    r = row('promo_active', True)
    q = r['tool_calls'][-1]
    if change == 'stale': q['args']['on'] = '2026-10-17'
    elif change == 'failed': q['result'] = {'error': 'unavailable'}
    elif change == 'wrong_sku': q['result']['sku'] = 'SKU-OTHER'
    elif change == 'different_product':
        q['args']['sku'] = q['result']['sku'] = 'SKU-OTHER'
    elif change == 'ambiguous':
        other = deepcopy(q)
        other['args']['qty'] = 2
        other['result']['applied_promos'] = []
        r['tool_calls'].append(other)
    elif change == 'expired_gift': q['result']['applied_promos'][0]['valid_until'] = '2026-10-17'
    assert explain_claim_mismatch(r, 'promo_active', True, on='2026-10-18')['status'] == 'unresolved'


def test_gift_claim_is_not_supported_by_cod_only_quote():
    r = row('promo_active', True)
    r['tool_calls'][-1]['result']['applied_promos'] = [{'type': 'freecod', 'promo_code': 'COD'}]
    assert explain_claim_mismatch(r, 'promo_active', True, on='2026-10-18')['status'] == 'unresolved'


def test_different_price_is_not_supported_even_for_correct_sku():
    r = row()
    r['tool_calls'][-1]['result']['final_price_vnd'] = 3100000
    assert explain_claim_mismatch(r, 'price_vnd', 2990000, on='2026-10-18')['status'] == 'unresolved'


def test_repeated_equivalent_quotes_with_default_quantity_are_not_ambiguous():
    r = row()
    repeated = deepcopy(r['tool_calls'][-1])
    repeated['args']['qty'] = 1
    r['tool_calls'].append(repeated)
    assert explain_claim_mismatch(r, 'price_vnd', 2990000, on='2026-10-18')['status'] == 'supported_by_quote'


def test_projection_matching_quote_cannot_clear_wrong_price_in_speech():
    r = row()
    r['claims'][0]['text'] = 'Xiaomi giá 1.000.000đ.'
    assert explain_claim_mismatch(r, 'price_vnd', 2990000, on='2026-10-18')['status'] == 'unresolved'
