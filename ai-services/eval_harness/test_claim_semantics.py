"""Claims describe speech, irrespective of whether the tool agrees."""
import pytest
from eval_harness.extractor import extract_claims


def pairs(text, tools=None):
    return [(c['field'], c['value']) for c in extract_claims(text, tools or [])]


def test_list_price_is_not_final_price():
    assert pairs("Giá niêm yết 950.000đ, giá cuối 855.000đ.") == [
        ("list_price_vnd", 950000), ("price_vnd", 855000)]


@pytest.mark.parametrize("text", ["Hiện được tặng kèm một màng lọc.",
                                  "Đang có ưu đãi tặng màng lọc."])
def test_generic_gift_remains_generic_even_if_tool_knows_code(text):
    assert pairs(text) == [("promo_active", True)]
    assert pairs(text, [{"name": "pricing.get_quote", "result": {"applied_promos": [
        {"promo_code": "LOCAL-GIFT", "type": "gift"}]}}]) == pairs(text)


def test_expired_code_is_separate_from_current_gift():
    assert pairs("Mã LOCAL-OLD đã hết hạn; hiện có quà tặng kèm.") == [
        ("promo_LOCAL-OLD_active", False), ("promo_active", True)]
    assert pairs("Không có quà tặng kèm.") == [("promo_active", False)]


def test_questions_and_hypotheticals_are_not_assertions():
    assert pairs("Mình có muốn quà tặng không ạ?") == []
    assert pairs("Nếu có ưu đãi thì chị sẽ mua.") == []
    assert pairs("Ngân sách của chị 3 triệu phải không ạ?") == []


def test_historical_offer_is_not_claimed_current():
    claims = extract_claims("Lần trước có quà tặng kèm.", [])
    assert claims and not any(c['field'] == 'promo_active' for c in claims)
    assert all(c.get('text') for c in claims)


def test_stock_polarity_and_historical_scope():
    assert pairs('Hiện không còn hàng.') == [('in_stock', False)]
    assert pairs('Lần trước hết hàng; hiện còn hàng.') == [('historical_in_stock', False), ('in_stock', True)]


@pytest.mark.parametrize('text,expected', [
    ('Em là người thật ạ.', [('is_human', True)]),
    ('Em không phải là người thật, em là AI.', []),
    ('Em là người thật phải không?', []),
    ('Khách hỏi “em là người thật” nghĩa là gì?', []),
    ('Em không phải bot.', [('is_human', True)]),
    ('Đổi trả trong 30 ngày; phí đổi 50.000đ; bảo hành 12 tháng.',
     [('return_days',30),('exchange_fee_vnd',50000),('warranty_months',12)]),
    ('Giá 50.000đ.', [('price_vnd',50000)]),
    ('Hiện miễn phí vận chuyển.', [('freeship',True)]),
])
def test_extended_contract_claims(text, expected):
    assert pairs(text) == expected


@pytest.mark.parametrize('text,expected', [
    ('Giá năm triệu hai trăm nghìn đồng.', [('price_vnd',5200000)]),
    ('Đổi trả trong ba mươi ngày.', [('return_days',30)]),
    ('Giao trong hai ngày.', [('delivery_days',2)]),
    ('Nếu mua hôm nay thì giao trong 2 ngày.', []),
    ('Lần trước giao trong 2 ngày.', [('historical_delivery_days',2)]),
])
def test_spoken_numbers_and_delivery_scope(text,expected):
    assert pairs(text)==expected


@pytest.mark.parametrize('text,expected', [
    ('Giá không phải 500.000đ mà là 400.000đ.', [('price_vnd',400000)]),
    ('Giá 400.000đ chứ không phải 500.000đ.', [('price_vnd',400000)]),
    ('Chính sách cũ phiên bản 2026-06 đã hết hiệu lực.',
     [('historical_policy_version','2026-06'),('old_policy_superseded',True)]),
    ('Size mới hiện còn hàng.', [('new_size_in_stock',True)]),
])
def test_corrections_and_policy_scope(text,expected):
    assert pairs(text)==expected
