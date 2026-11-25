import pytest
from app.agent.guardrails.checks import check_answer


def calls(*, gift=False, shipping=False, code="LOCAL-OFFER", expiry="2026-11-20", sku="SKU-LOCAL-A"):
    promos = [{"promo_code": "LOCAL-COD", "type": "freecod", "discount_vnd": 0}]
    if gift:
        promos.append({"promo_code": code, "type": "gift", "gift_sku": "SKU-LOCAL-GIFT", "valid_until": expiry})
    return [{"name": "catalog.search", "args": {}, "result": {"items": [
        {"sku": sku, "name": "Máy Alpha", "attributes": {}},
        {"sku": "SKU-LOCAL-GIFT", "name": "Màng lọc thay thế", "attributes": {}}]}},
        {"name": "pricing.get_quote", "args": {"sku": sku, "on": "2026-11-02"},
         "result": {"sku": sku, "final_price_vnd": 730000, "list_price_vnd": 730000,
                    "applied_promos": promos, "freeship": shipping, "expired_promos": ["LOCAL-OLD"]}}]


@pytest.mark.parametrize("text", ["Em tặng kèm một màng lọc ạ.",
    "Hiện có ưu đãi tặng một màng lọc đến ngày 20/11 ạ.", "Mình được miễn phí vận chuyển ạ."])
def test_freecod_is_not_evidence_for_other_benefits(text):
    assert check_answer(text, calls())[1] is not None


@pytest.mark.parametrize('text,shipping,cod', [
    ('Phí COD là 0 đồng.', False, True),
    ('Phí COD: 0đ.', False, True),
    ('**Phí COD:** 0đ.', False, True),
    ('**Phí COD**: 0đ.', False, True),
    ('Miễn phí COD.', False, True),
    ('Phí vận chuyển là 0đ.', True, False),
    ('Phí vận chuyển: **0đ**.', True, False),
    ('Phí vận chuyển: 0 VNĐ.', True, False),
])
def test_zero_fee_requires_the_corresponding_quote_benefit(text, shipping, cod):
    observations = calls(shipping=shipping)
    if not cod:
        observations[-1]['result']['applied_promos'] = []
    assert check_answer(text, observations) == (text, None)
    assert check_answer(text, [])[1] == 'promotion_quote_missing'
    wrong_benefit = calls(shipping=not shipping)
    if cod:
        wrong_benefit[-1]['result']['applied_promos'] = []
    assert check_answer(text, wrong_benefit)[1] == 'promotion_detail_unverified'


def test_basket_cod_fee_uses_the_order_promotion():
    result = {'units': [{'sku': 'A', 'list_price_vnd': 730000, 'final_price_vnd': 730000},
                        {'sku': 'B', 'list_price_vnd': 730000, 'final_price_vnd': 730000}],
              'order_promos': [{'type': 'freecod', 'promo_code': 'LOCAL-COD'}]}
    observations = [{'name': 'pricing.quote_order', 'args': {'on': '2026-11-02'}, 'result': result}]
    assert check_answer('Phí thu hộ là 0đ.', observations, focus_sku='A')[1] is None
    result['order_promos'] = []
    assert check_answer('Phí thu hộ là 0đ.', observations, focus_sku='A')[1] == 'promotion_detail_unverified'


@pytest.mark.parametrize("code,expiry", [("LOCAL-OFFER", "2026-11-20"), ("OTHER-GIFT", "2026-12-09")])
def test_valid_benefit_and_deadline_are_linked(code, expiry):
    day = expiry[8:10] + "/" + expiry[5:7]
    assert check_answer(f"Được tặng một màng lọc đến ngày {day} ạ.", calls(gift=True, code=code, expiry=expiry))[1] is None
    assert check_answer("Được tặng ba màng lọc ạ.", calls(gift=True, code=code, expiry=expiry))[1] is not None
    assert check_answer("Được tặng một xe đạp ạ.", calls(gift=True, code=code, expiry=expiry))[1] is not None
    assert check_answer("Được tặng màng lọc đến ngày 30/12 ạ.", calls(gift=True, code=code, expiry=expiry))[1] is not None


def test_expired_code_and_current_gift_can_coexist():
    text = "Khuyến mãi LOCAL-OLD đã hết hạn; hiện được tặng màng lọc đến ngày 20/11 ạ."
    assert check_answer(text, calls(gift=True))[1] is None
    assert check_answer("Khuyến mãi LOCAL-OLD đang áp dụng.", calls(gift=True))[1] is not None


def test_percentage_has_to_match_actual_discount():
    observations = calls()
    quote = observations[-1]["result"]
    quote.update(list_price_vnd=1000000, final_price_vnd=900000,
                 applied_promos=[{"promo_code": "LOCAL-TEN", "type": "percent", "discount_vnd": 100000}])
    assert check_answer("Mẫu này được giảm 10% ạ.", observations)[1] is None
    assert check_answer("Mẫu này được giảm 30% ạ.", observations)[1] is not None


def test_questions_and_explicit_past_are_not_current_promises():
    assert check_answer("Mình muốn hỏi về quà tặng nào ạ?", [])[1] is None
    assert check_answer("Lần trước có quà tặng, hôm nay em cần kiểm tra lại.", [])[1] is None


def test_deadline_cannot_be_borrowed_from_another_benefit():
    observations = calls(gift=True)
    observations[-1]['result']['applied_promos'][0]['valid_until'] = '2026-12-30'
    assert check_answer('Được tặng màng lọc đến ngày 30/12 ạ.', observations)[1] is not None


def test_negative_benefit_must_also_agree_with_quote():
    assert check_answer('Hiện không có quà tặng kèm.', calls(gift=True))[1] is not None
    assert check_answer('Hiện không được miễn phí vận chuyển.', calls(shipping=True))[1] is not None


def test_multi_product_offer_is_bound_to_named_sku():
    observations = calls(gift=True, sku='SKU-LOCAL-A')
    other = calls(sku='SKU-LOCAL-B')[-1]
    observations.append(other)
    assert check_answer('SKU-LOCAL-A được tặng màng lọc.', observations)[1] is None
    assert check_answer('SKU-LOCAL-B được tặng màng lọc.', observations)[1] is not None
    assert check_answer('Được tặng màng lọc.', observations)[1] is not None


def test_named_gift_is_verified_against_the_purchased_product():
    observations = calls(gift=True)
    answer = 'Được tặng Màng lọc thay thế ạ.'
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-A') == (answer, None)
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-B')[1] is not None
    assert check_answer('Màng lọc thay thế được tặng quà.', observations)[1] is not None


@pytest.mark.parametrize('gift_name', ['Túi vải du lịch', 'Bộ cọ vệ sinh', 'Pin dự phòng nhỏ'])
def test_named_gift_does_not_choose_the_product_quote(gift_name):
    observations = calls(gift=True)
    observations[0]['result']['items'][1]['name'] = gift_name
    observations.append(calls(sku='SKU-LOCAL-B')[-1])
    answer = f'Máy Alpha được tặng {gift_name} ạ.'
    assert check_answer(answer, observations) == (answer, None)
    answer = f'Được tặng {gift_name} ạ.'
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-A') == (answer, None)
    assert check_answer(answer, observations)[1] is not None
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-B')[1] is not None


@pytest.mark.parametrize('answer', [
    'Có quà tặng là xe đạp ạ.', 'Được tặng quà là xe đạp ạ.',
    'Có quà tặng kèm là xe đạp ạ.',
])
def test_generic_gift_wording_does_not_hide_an_unverified_description(answer):
    assert check_answer(answer, calls(gift=True))[1] == 'promotion_detail_unverified'


def test_basket_named_gift_is_bound_to_the_purchased_unit():
    observations = calls(gift=True)
    unit = observations.pop()['result']
    observations.append({'name': 'pricing.quote_order', 'args': {'on': '2026-11-02'},
        'result': {'units': [unit, {'sku': 'SKU-LOCAL-B', 'list_price_vnd': 730000,
            'final_price_vnd': 730000, 'applied_promos': []}], 'order_promos': []}})
    answer = 'Máy Alpha được tặng Màng lọc thay thế ạ.'
    assert check_answer(answer, observations) == (answer, None)
    answer = 'Được tặng Màng lọc thay thế ạ.'
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-A') == (answer, None)
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-B')[1] is not None
    assert check_answer(answer, observations)[1] is not None


def test_product_codes_are_not_mistaken_for_promotion_codes():
    observations = calls(gift=True, sku='DEVICE-81')
    answer = 'DEVICE-81 được tặng Màng lọc thay thế ạ.'
    assert check_answer(answer, observations) == (answer, None)
    assert check_answer('DEVICE-81 có ưu đãi INVENTED-PROMO.', observations)[1] == 'promotion_code_mismatch'


@pytest.mark.parametrize('gift_name', ['Túi vải du lịch', 'Bộ cọ vệ sinh', 'Cáp'])
@pytest.mark.parametrize('wording', [
    'Được tặng **{gift}** ạ.', 'Được tặng __1 {gift}__ ạ.',
    'Được tặng 1 chiếc {gift} ạ.', 'Được tặng một bộ {gift} ạ.',
    'Được tặng {gift} anh nhé.', 'Được tặng {gift} chị ạ.',
    'Được tặng {gift} miễn phí.', 'Được tặng `{gift}` miễn phí anh nhé.',
])
def test_supported_gift_survives_formatting_units_and_polite_endings(gift_name, wording):
    observations = calls(gift=True)
    observations[0]['result']['items'][1]['name'] = gift_name
    answer = wording.format(gift=gift_name)
    assert check_answer(answer, observations, focus_sku='SKU-LOCAL-A') == (answer, None)


@pytest.mark.parametrize('answer', [
    'Được tặng **ba màng lọc** ạ.', 'Được tặng một chiếc **xe đạp** miễn phí anh nhé.',
])
def test_gift_formatting_does_not_hide_wrong_quantity_or_wrong_item(answer):
    assert check_answer(answer, calls(gift=True))[1] is not None


def test_formatting_cannot_hide_an_unsupported_promotion_deadline_or_percentage():
    assert check_answer('Được tặng **Màng lọc thay thế** đến ngày **30/12**.', calls(gift=True))[1] is not None
    observations = calls()
    observations[-1]['result'].update(list_price_vnd=1000000, final_price_vnd=900000,
        applied_promos=[{'promo_code': 'LOCAL-TEN', 'type': 'percent', 'discount_vnd': 100000}])
    answer = 'Mẫu này được giảm **10**% ạ.'
    assert check_answer(answer, observations) == (answer, None)
    assert check_answer('Mẫu này được giảm **30**% ạ.', observations)[1] is not None
