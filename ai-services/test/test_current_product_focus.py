import pytest

from app.agent.guardrails.checks import check_answer


@pytest.mark.parametrize('old_sku,old_name,new_sku,new_name', [
    ('CONTROL-81', 'Bộ điều khiển Lumen', 'PANEL-B7', 'Tấm điều khiển Boreal'),
    ('LAMP-C4', 'Đèn bàn Solstice', 'SENSOR-D8', 'Cảm biến Nimbus'),
])
@pytest.mark.parametrize('kind', ['price', 'stock', 'shipping'])
def test_explicit_current_product_overrides_stale_focus(old_sku, old_name, new_sku, new_name, kind):
    calls = []
    for sku, name, price, available, shipping in [
        (old_sku, old_name, 275000, False, False),
        (new_sku, new_name, 830000, True, True),
    ]:
        calls.extend([
            {'name': 'catalog.search', 'args': {}, 'result': {'items': [
                {'sku': sku, 'name': name, 'variants': []}]}},
            {'name': 'pricing.get_quote', 'args': {'sku': sku, 'on': '2033-05-10'},
             'result': {'sku': sku, 'list_price_vnd': price, 'final_price_vnd': price,
                        'freeship': shipping, 'applied_promos': []}},
            {'name': 'inventory.check', 'args': {'sku': sku, 'on': '2033-05-10'},
             'result': {'sku': sku, 'in_stock': available, 'qty': 4 if available else 0}},
        ])
    query, correct, stale = {
        'price': (f'{new_name} giá bao nhiêu?', 'Giá hiện tại là 830.000đ.',
                  'Giá hiện tại là 275.000đ.'),
        'stock': (f'{new_name} còn hàng không?', 'Hiện còn hàng.', 'Hiện hết hàng.'),
        'shipping': (f'{new_name} phí giao thế nào?', 'Được miễn phí vận chuyển.',
                     'Không được miễn phí vận chuyển.'),
    }[kind]
    assert check_answer(correct, calls, query, focus_sku=old_sku)[1] is None
    assert check_answer(stale, calls, query, focus_sku=old_sku)[1] is not None


def test_parent_price_can_use_bound_variant_without_accepting_a_different_variant():
    calls = [
        {'name': 'catalog.get_details', 'args': {'sku': 'COAT-N7'}, 'result': {'items': [{
            'sku': 'COAT-N7', 'name': 'Áo khoác Vega', 'variants': [
                {'variant_sku': 'COAT-N7-32-GREEN', 'size': 32, 'color': 'xanh'},
                {'variant_sku': 'COAT-N7-34-RED', 'size': 34, 'color': 'đỏ'}]}]}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'COAT-N7-32-GREEN', 'on': '2033-05-10'},
         'result': {'sku': 'COAT-N7-32-GREEN', 'final_price_vnd': 740000}},
    ]
    assert check_answer('Áo khoác Vega giá 740.000đ.', calls,
                        focus_sku='COAT-N7-32-GREEN')[1] is None
    assert check_answer('Áo khoác Vega size 34 màu đỏ giá 740.000đ.', calls,
                        focus_sku='COAT-N7-32-GREEN')[1] is not None
    assert check_answer('Giá hiện tại là 740.000đ.', calls,
                        'Áo khoác Vega size 34 màu đỏ giá bao nhiêu?',
                        focus_sku='COAT-N7-32-GREEN')[1] is not None
