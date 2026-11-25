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
