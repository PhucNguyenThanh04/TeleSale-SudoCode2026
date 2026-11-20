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
