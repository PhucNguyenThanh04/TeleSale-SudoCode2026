import pytest

from eval_harness.extractor import extract_claims


@pytest.mark.parametrize('budget', ['năm triệu rưỡi', '5,5 triệu', '5.500.000đ'])
def test_budget_in_price_sentence_is_not_another_selling_price(budget):
    claims = extract_claims(
        f'Mức giá 5.490.000đ của máy vẫn nằm trong ngân sách {budget} của anh ạ.', [])
    assert [(c['field'], c['value']) for c in claims] == [('price_vnd', 5490000)]


@pytest.mark.parametrize('text,expected', [
    ('Giá máy là năm triệu rưỡi.', 5500000),
    ('Giá máy là hai triệu rưỡi.', 2500000),
    ('Giá máy là bảy nghìn rưỡi.', 7500),
    ('Giá máy là 5 triệu 490 nghìn đồng.', 5490000),
])
def test_price_with_multiple_units_keeps_real_selling_price(text, expected):
    assert [c['value'] for c in extract_claims(text, []) if c['field'] == 'price_vnd'] == [expected]


def test_budget_does_not_hide_a_subsequent_selling_price():
    claims = extract_claims('Ngân sách 5 triệu của anh còn giá máy là 6 triệu.', [])
    assert [c['value'] for c in claims if c['field'] == 'price_vnd'] == [6000000]
