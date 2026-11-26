import pytest

from app.agent.guardrails.checks import _money_claims, check_answer
from test_promotion_grounding import calls


def evidence():
    observations = calls(gift=True, shipping=True)
    observations[0]['result']['items'][1]['name'] = 'Phụ kiện Studio 9'
    observations[-1]['result']['estimated_delivery'] = '2026-11-06'
    return observations


@pytest.mark.parametrize('text', ['Phụ kiện Studio 9, đồng thời miễn phí ship.',
    'Mẫu số 7, đồng ý rồi nhé.', 'Studio 12 đồng thời dùng được cho nhiều máy.'])
def test_discourse_markers_after_model_numbers_are_not_currency(text):
    assert _money_claims(text) == []


def test_actual_currency_before_a_new_sentence_is_still_a_money_claim():
    assert _money_claims('Phí là 9 đồng. Đồng thời được giao tận nơi.') == [(9, 'price', False)]


def test_price_and_gift_in_one_sentence_keep_separate_subjects():
    answer = 'Giá máy là 730.000đ và được tặng kèm một Phụ kiện Studio 9, đồng thời miễn phí vận chuyển.'
    assert check_answer(answer, evidence()) == (answer, None)


def test_a_gift_price_cannot_borrow_the_purchased_product_quote():
    answer = 'Máy Alpha giá 730.000đ và được tặng Phụ kiện Studio 9 giá 730.000đ.'
    assert check_answer(answer, evidence())[1] == 'price_without_quote'


def test_unquoted_gift_price_cannot_be_presented_as_a_standalone_price():
    assert check_answer('Phụ kiện Studio 9 giá 730.000đ.', evidence())[1] == 'price_without_quote'


@pytest.mark.parametrize('spoken_date', ['2026-11-06', '06/11/2026', '6/11/2026', '6/11'])
def test_delivery_dates_compare_calendar_values_instead_of_literal_format(spoken_date):
    answer = f'Máy Alpha dự kiến giao đến anh vào ngày {spoken_date}.'
    assert check_answer(answer, evidence()) == (answer, None)


@pytest.mark.parametrize('spoken_date', ['2026-11-07', '7/11/2026', '31/11/2026', '6/11/2027'])
def test_wrong_or_invalid_delivery_dates_remain_blocked(spoken_date):
    assert check_answer(f'Máy Alpha dự kiến giao ngày {spoken_date}.', evidence())[1] == 'delivery_unverified'


def test_the_complete_natural_reply_uses_each_matching_evidence_source():
    answer = ('Giá của máy là 730.000đ, được miễn phí vận chuyển và dự kiến giao đến anh '
        'vào ngày 06/11/2026. Khi mua máy hiện tại anh sẽ được tặng kèm một Phụ kiện Studio 9 nữa ạ.')
    assert check_answer(answer, evidence()) == (answer, None)


def test_delivery_date_cannot_be_borrowed_from_another_product_or_ambiguous_quotes():
    observations = evidence()
    assert check_answer('Phụ kiện Studio 9 dự kiến giao ngày 06/11/2026.', observations)[1] == 'delivery_unverified'
    other = calls(sku='SKU-OTHER')[-1]
    other['result']['estimated_delivery'] = '2026-11-06'
    observations.append(other)
    assert check_answer('Dự kiến giao ngày 06/11/2026.', observations)[1] == 'delivery_unverified'


@pytest.mark.parametrize('answer', [
    'Em là trợ lý bán hàng, em có thể hỗ trợ anh/chị tìm kiếm sản phẩm phù hợp với nhu cầu, '
    'cung cấp thông tin chi tiết về thông số, giá cả, chương trình ưu đãi cũng như hỗ trợ đặt hàng '
    'và tra cứu trạng thái đơn hàng ạ.',
    'Em có thể hỗ trợ anh/chị tìm kiếm sản phẩm phù hợp với nhu cầu, cung cấp thông tin chi tiết '
    'về thông số, giá cả, chương trình ưu đãi hiện có hoặc hỗ trợ kiểm tra trạng thái đơn hàng.',
    'Em có thể hỗ trợ anh/chị cung cấp thông tin chi tiết về thông số, báo giá ưu đãi hiện có hoặc kiểm tra trạng thái đơn hàng.',
    'Dạ, tôi có thể tư vấn sản phẩm và kiểm tra chương trình khuyến mãi cho bạn.',
    'Bên em sẵn sàng giải đáp thắc mắc về giá, tồn kho, ưu đãi và giao hàng.',
    'Hiện tại em chưa nhận được thông tin chi tiết về chương trình ưu đãi cho sản phẩm anh/chị quan tâm.',
    'Hiện tại hệ thống chưa cập nhật được thông tin báo giá ưu đãi cho sản phẩm này.',
])
def test_service_capabilities_are_not_current_commercial_promises(answer):
    assert check_answer(answer, []) == (answer, None)


@pytest.mark.parametrize('answer', [
    'Em có thể tư vấn sản phẩm, hiện có ưu đãi giảm 30%.',
    'Em có thể kiểm tra giá, sản phẩm này được miễn phí vận chuyển.',
    'Em có thể tra cứu ưu đãi và tặng một xe đạp cho anh.',
    'Em có thể tư vấn, bên em có ưu đãi dành cho mọi đơn hàng.',
    'Em có thể kiểm tra giá máy là 730.000đ.',
    'Em có thể tư vấn ưu đãi. Hiện đang miễn phí vận chuyển.',
    'Em đã tạo đơn, em có thể tư vấn thêm về ưu đãi.',
    'Em có thể tư vấn ưu đãi PROMO-FREE.',
    'Em có thể kiểm tra, mọi đơn hàng đều giảm giá.',
    'Em có thể tư vấn, khuyến mãi hết hạn.',
    'Sản phẩm này không có ưu đãi.',
    'Em có thể tư vấn thêm cho anh, mẫu này còn hàng và bảo hành trọn đời ạ.',
    'Em có thể tư vấn thêm cho anh, mẫu này lọc HEPA tốt nhất ạ.',
    'Em có thể kiểm tra giúp anh, ưu đãi đang có rất hấp dẫn ạ.',
])
def test_capability_language_does_not_hide_concrete_commercial_claims(answer):
    assert check_answer(answer, [])[1] is not None


def test_single_named_product_carries_across_sentences_when_multiple_quotes_exist():
    observations = [
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-XM-4P'},
         'result': {'items': [{'sku': 'SKU-XM-4P', 'name': 'Máy lọc không khí Xiaomi Smart 4 Pro', 'variants': []}]}},
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-OTHER'},
         'result': {'items': [{'sku': 'SKU-OTHER', 'name': 'Máy lọc không khí Sharp FP-J40E', 'variants': []}]}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-XM-4P', 'in_stock': True, 'qty': 20}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-OTHER', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-OTHER', 'in_stock': False, 'qty': 0}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-XM-4P', 'list_price_vnd': 5490000, 'final_price_vnd': 5490000,
                    'applied_promos': [], 'freeship': True, 'estimated_delivery': '2026-10-26'}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-OTHER', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-OTHER', 'list_price_vnd': 3990000, 'final_price_vnd': 3990000,
                    'applied_promos': [], 'freeship': False, 'estimated_delivery': '2026-10-27'}},
    ]
    single_subject = ('Máy lọc không khí Xiaomi Smart 4 Pro hiện còn hàng. '
                      'Giá bán hôm nay là 5.490.000đ, miễn phí vận chuyển và dự kiến giao ngày 26/10/2026.')
    assert check_answer(single_subject, observations) == (single_subject, None)
    ambiguous = ('Máy lọc không khí Xiaomi Smart 4 Pro và Máy lọc không khí Sharp FP-J40E đều tốt. '
                 'Giá bán hôm nay là 5.490.000đ.')
    assert check_answer(ambiguous, observations)[1] == 'price_without_quote'


def test_gift_bullet_does_not_pollute_order_confirmation_price_subject_and_service_superlative():
    observations = [
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-XM-4P'},
         'result': {'items': [{'sku': 'SKU-XM-4P', 'name': 'Máy lọc không khí Xiaomi Smart 4 Pro', 'variants': []}]}},
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-XM-FLT'},
         'result': {'items': [{'sku': 'SKU-XM-FLT', 'name': 'Màng lọc thay thế Xiaomi Smart 4', 'variants': []}]}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-XM-4P', 'list_price_vnd': 5490000, 'final_price_vnd': 5490000,
                    'applied_promos': [{'promo_code': 'XM-COMBO', 'type': 'gift', 'discount_vnd': 0, 'gift_sku': 'SKU-XM-FLT'}],
                    'freeship': True, 'estimated_delivery': '2026-10-26'}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-FLT', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-XM-FLT', 'list_price_vnd': 590000, 'final_price_vnd': 590000,
                    'applied_promos': [], 'freeship': False}},
    ]
    confirmation = (
        'Để đảm bảo chính xác, em xin xác nhận lại thông tin đơn hàng của anh như sau:\n\n'
        '- **Sản phẩm:** 01 Máy lọc không khí Xiaomi Smart 4 Pro.\n'
        '- **Giá cuối:** 5.490.000đ.\n'
        '- **Ưu đãi:** Tặng kèm 01 Màng lọc thay thế Xiaomi Smart 4 và miễn phí vận chuyển.\n'
        '- **Phương thức thanh toán:** COD (Thanh toán khi nhận hàng).'
    )
    assert check_answer(confirmation, observations) == (confirmation, None)
    polite = 'Để đảm bảo quyền lợi tốt nhất cho anh, em sẽ kiểm tra lại thông tin ngay ạ.'
    assert check_answer(polite, []) == (polite, None)
    assert check_answer('Em sẽ hỗ trợ anh tốt nhất ạ.', []) == ('Em sẽ hỗ trợ anh tốt nhất ạ.', None)
    assert check_answer('Mẫu này tốt nhất ạ.', []) == ('Mẫu này tốt nhất ạ.', None)


def test_reviewer_edge_cases_delivery_gift_qty_focus_and_mixed_promos():
    obs = [
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-XM-4P'},
         'result': {'items': [{'sku': 'SKU-XM-4P', 'name': 'Máy lọc không khí Xiaomi Smart 4 Pro', 'variants': []}]}},
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-XM-FLT'},
         'result': {'items': [{'sku': 'SKU-XM-FLT', 'name': 'Màng lọc thay thế Xiaomi Smart 4', 'variants': []}]}},
        {'name': 'catalog.get_details', 'args': {'sku': 'SKU-SH-J40'},
         'result': {'items': [{'sku': 'SKU-SH-J40', 'name': 'Máy lọc không khí Sharp FP-J40E', 'variants': []}]}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-SH-J40', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-SH-J40', 'in_stock': True, 'qty': 5}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-XM-4P', 'in_stock': False, 'qty': 0}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-XM-4P', 'on': '2026-10-22', 'qty': 2},
         'result': {'sku': 'SKU-XM-4P', 'list_price_vnd': 5490000, 'final_price_vnd': 5490000,
                    'applied_promos': [{'promo_code': 'XM-COMBO', 'type': 'gift', 'discount_vnd': 0, 'gift_sku': 'SKU-XM-FLT'}],
                    'freeship': True, 'estimated_delivery': '2026-10-26'}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-SH-J40', 'on': '2026-10-22'},
         'result': {'sku': 'SKU-SH-J40', 'list_price_vnd': 4200000, 'final_price_vnd': 4200000,
                    'applied_promos': [], 'freeship': False, 'estimated_delivery': '2026-10-27'}},
    ]
    assert check_answer('Thời gian giao hàng dự kiến: 28/10/2026.', obs)[1] == 'delivery_unverified'
    pb09_ok = (
        'Để đảm bảo chính xác, em xin xác nhận lại thông tin đơn hàng:\n'
        '- **Sản phẩm:** 01 Máy lọc không khí Xiaomi Smart 4 Pro.\n'
        '- **Giá cuối:** 5.490.000đ.\n'
        '- **Thời gian giao hàng dự kiến:** 26/10/2026.'
    )
    assert check_answer(pb09_ok, obs) == (pb09_ok, None)
    order_obs = [*obs, {'name': 'order.create', 'args': {'sku': 'SKU-XM-4P'},
                        'result': {'status': 'created', 'order_id': 'OD-123', 'estimated_delivery': '2026-10-26'}}]
    created_reply = 'Em đã tạo đơn hàng OD-123, dự kiến giao ngày 26/10/2026 ạ.'
    assert check_answer(created_reply, order_obs) == (created_reply, None)
    assert check_answer('- **Sản phẩm:** Máy lọc không khí Xiaomi Smart 4 Pro.\n- **Quà tặng:** 02 Màng lọc thay thế Xiaomi Smart 4.', obs)[1] == 'promotion_detail_unverified'
    alt_reply = 'Em gợi ý sang Máy lọc không khí Sharp FP-J40E:\n- Giá cuối: 4.200.000đ.\n- Tình trạng: Còn hàng.'
    assert check_answer(alt_reply, obs, focus_sku='SKU-XM-4P') == (alt_reply, None)
    mixed_promo = 'Máy lọc không khí Xiaomi Smart 4 Pro không có giảm giá trực tiếp, tặng kèm 01 Màng lọc thay thế Xiaomi Smart 4 và miễn phí vận chuyển.'
    assert check_answer(mixed_promo, obs) == (mixed_promo, None)
    status_obs = [{'name': 'order.status', 'args': {'order_id': 'OD-123'}, 'result': {'orders': [{'order_id': 'OD-123', 'status': 'created'}]}}]
    assert check_answer('Đơn hàng OD-123 của anh đang được xử lý ạ.', status_obs) == ('Đơn hàng OD-123 của anh đang được xử lý ạ.', None)
    unit_and_total = 'Máy lọc không khí Xiaomi Smart 4 Pro giá 5.490.000đ/chiếc, tổng 2 chiếc là 10.980.000đ.'
    assert check_answer(unit_and_total, obs) == (unit_and_total, None)
    oos_reply = 'Máy lọc không khí Xiaomi Smart 4 Pro hiện không sẵn hàng ạ.'
    assert check_answer(oos_reply, obs) == (oos_reply, None)
    passive_gift = (
        'Dạ, nếu anh chốt đơn máy lọc không khí Xiaomi Smart 4 Pro, thì màng lọc thay thế '
        'được tặng kèm sẽ được đóng gói chung trong cùng một kiện hàng với máy để giao đến anh luôn ạ.\n\n'
        'Vì hiện tại hệ thống vẫn chưa ghi nhận đơn hàng của anh, nên nếu anh đồng ý, '
        'em xin phép lên đơn cho mình ngay bây giờ để anh sớm nhận được máy và quà tặng nhé!'
    )
    assert check_answer(passive_gift, obs) == (passive_gift, None)
    wrong_passive_gift = (
        'Dạ, nếu anh chốt đơn máy lọc không khí Xiaomi Smart 4 Pro, thì xe đạp '
        'được tặng kèm sẽ được giao cùng máy ạ.'
    )
    assert check_answer(wrong_passive_gift, obs)[1] == 'promotion_detail_unverified'


def test_variant_only_clause_resolves_without_repeating_parent_name():
    obs = [
        {'name': 'catalog.search', 'args': {'query': 'giày trekking HikePro'},
         'result': {'items': [{'sku': 'SKU-SN-TRK', 'name': 'Giày trekking HikePro', 'variants': [
             {'variant_sku': 'SKU-SN-TRK-41-TRANG', 'size': '41', 'color': 'Trắng'},
             {'variant_sku': 'SKU-SN-TRK-41-XAM', 'size': '41', 'color': 'Xám'},
             {'variant_sku': 'SKU-SN-TRK-42-XAM', 'size': '42', 'color': 'Xám'},
         ]}]}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-SN-TRK-41-TRANG', 'on': '2026-10-19'},
         'result': {'sku': 'SKU-SN-TRK-41-TRANG', 'in_stock': False, 'qty': 0}},
        {'name': 'inventory.check', 'args': {'sku': 'SKU-SN-TRK-41-XAM', 'on': '2026-10-19'},
         'result': {'sku': 'SKU-SN-TRK-41-XAM', 'in_stock': True, 'qty': 8}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-SN-TRK-41-TRANG', 'on': '2026-10-19'},
         'result': {'sku': 'SKU-SN-TRK-41-TRANG', 'list_price_vnd': 1990000, 'final_price_vnd': 1990000, 'applied_promos': []}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'SKU-SN-TRK-41-XAM', 'on': '2026-10-19'},
         'result': {'sku': 'SKU-SN-TRK-41-XAM', 'list_price_vnd': 1990000, 'final_price_vnd': 1990000, 'applied_promos': []}},
    ]
    reply = 'Bản size 41 màu xám hiện còn hàng và giá bán là 1.990.000đ ạ.'
    assert check_answer(reply, obs) == (reply, None)
    wrong_stock = 'Bản size 41 màu trắng hiện còn hàng ạ.'
    assert check_answer(wrong_stock, obs)[1] == 'stock_result_mismatch'
