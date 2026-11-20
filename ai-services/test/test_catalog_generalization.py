import asyncio
from datetime import date, datetime
from uuid import uuid4

import pytest

from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
from app.mcp_servers.mcp_shared.commerce_rules import _catalog
from app.schemas.agent import TextTurnRequest


def state(text, items):
    return {'request': TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
        channel='hotline', channel_identity='offline', on=date(2028, 3, 17), text=text, input_mode='clean'),
        'safe_text': text, 'tool_calls': [{'name': 'catalog.search', 'args': {'query': 'Nova'},
        'result': {'items': items}}], 'tool_count': 0}


def product(sku, name):
    return {'sku': sku, 'name': name, 'brand': 'Nova', 'category': 'van-phong/den',
            'list_price_vnd': 100_000, 'attributes': {}, 'variants': []}


@pytest.mark.parametrize('size,color', [('3XL', 'tím than'), ('38.5', 'vàng kem'), ('one size', 'hồng phấn')])
def test_claim_variant_values_come_from_catalog(size, color):
    item = product('SKU-NOVA', 'Đèn Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-CHOSEN', 'size': size, 'color': color},
                        {'variant_sku': 'SKU-NOVA-OTHER', 'size': 'M', 'color': 'trắng'}]
    s = state(f'Nova Lumi size {size} màu {color} có giá 100.000đ.', [item])
    assert resolve_claim_skus(s['safe_text'], s['tool_calls']) == {'SKU-NOVA-CHOSEN'}


def test_unknown_model_version_is_not_replaced_with_existing_version():
    item = product('SKU-NOVA-800', 'Đèn Nova 800')
    assert _catalog([item], {'query': 'Nova 900'})['items'] == []


def test_verified_sku_without_published_prefix_can_be_quoted():
    item = product('LAMP:2028-A', 'Đèn Nova Lumi')
    s = state('Nova Lumi giá bao nhiêu?', [item])
    s['decision'] = Decision(action='tool', tool_name='pricing.get_quote', tool_args={'sku': item['sku']})
    prepared = prepare_tool_call(s, datetime.now)
    assert prepared is not None and prepared[1]['sku'] == item['sku']
    s['tool_calls'] = []
    assert prepare_tool_call(s, datetime.now) is None












def test_variant_selection_uses_longest_catalog_value_for_decimal_size_and_color():
    from app.agent.harness.policy import resolve_product_selection
    item = product('SKU-NOVA', 'Giày Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-EXACT', 'size': '38.5', 'color': 'xanh dương'},
                        {'variant_sku': 'SKU-NOVA-SHORT', 'size': '38', 'color': 'xanh'}]
    s = state('Nova Lumi size 38.5 màu xanh dương.', [item])
    assert resolve_product_selection(s, {'sku': item['sku']}).sku == 'SKU-NOVA-EXACT'
    assert resolve_claim_skus(s['safe_text'], s['tool_calls']) == {'SKU-NOVA-EXACT'}


def test_unspecified_variant_is_not_confused_with_vietnamese_words_co_or_mau():
    item = product('SKU-NOVA', 'Giày Nova Lumi')
    item['variants'] = [{'variant_sku': 'SKU-NOVA-38', 'size': '38', 'color': 'tím'},
                        {'variant_sku': 'SKU-NOVA-39', 'size': '39', 'color': 'xanh'}]
    s = state('Mẫu Nova Lumi có giá bao nhiêu?', [item])
    assert resolve_claim_skus(s['safe_text'], s['tool_calls']) == {'SKU-NOVA', 'SKU-NOVA-38', 'SKU-NOVA-39'}
