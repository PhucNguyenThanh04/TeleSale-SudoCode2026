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
