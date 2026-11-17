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


def test_negation_binds_to_benefit():
    assert pairs('Máy lọc không khí được miễn phí vận chuyển.') == [('freeship', True)]
    assert pairs('Máy lọc không khí không được miễn phí vận chuyển.') == [('freeship', False)]


def test_sale_price_is_not_discount():
    assert pairs('Giá ưu đãi là 1.521.000đ.') == [('price_vnd', 1521000), ('promo_active', True)]
    assert pairs('Giảm 70.000đ.') == [('discount_vnd', 70000)]


@pytest.mark.parametrize('text,reason', [
    ('Tổng tiền 4.700.000đ.', 'unsupported_mapping'),
    ('Dự kiến giao ngày 18/11.', 'unsupported_mapping'),
    ('Lần đổi đầu tiên được miễn phí.', 'qualified_not_representable'),
    ('Nếu có lỗi nhà sản xuất thì được đổi mới trong 30 ngày.', 'qualified_not_representable'),
])
def test_total_is_not_unit_price(text, reason):
    from eval_harness.extractor import extract_detailed
    result = extract_detailed(text)
    assert result['claims'] == []
    assert [(c['disposition'], c['reason']) for c in result['candidates']] == [('excluded', reason)]


def test_policy_duration_and_quotation():
    assert pairs('Thời hạn đổi trả là trong vòng 7 ngày.') == [('return_days', 7)]
    assert pairs('Bảo hành trong mười tám tháng.') == [('warranty_months', 18)]
    assert pairs('Khách nói “giá 700.000đ”.') == []


def test_independent_assertion_survives_conditional_clause():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Giá 810.000đ, nếu có lỗi nhà sản xuất thì đổi mới trong 20 ngày.')
    assert [(c['field'],c['value']) for c in result['claims']] == [('price_vnd',810000)]
    assert result['candidates'][-1]['reason'] == 'qualified_not_representable'
    assert result['candidates'][-1]['qualifiers']['condition']


def test_hypothetical_intention_is_not_conditional_entitlement():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Nếu có ưu đãi thì chị sẽ mua.')
    assert result['candidates'][0]['reason'] == 'hypothetical'


def test_clear_exchange_fee_and_stock_negation():
    assert pairs('Đổi size miễn phí.') == [('exchange_fee_vnd', 0)]
    assert pairs('Hiện không có hàng.') == [('in_stock', False)]


def test_understood_shipping_fee_and_variant_scope_are_not_parse_failures():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Phí giao hàng 25.000đ; size 43 hiện còn hàng.')
    assert result['claims'] == []
    assert [c['reason'] for c in result['candidates']] == ['unsupported_mapping', 'qualified_not_representable']
    assert result['candidates'][1]['qualifiers'] == {'size':43}


def test_discount_amount_is_separate_from_sale_price():
    assert pairs('Giá gốc 900.000đ; giảm thêm 80.000đ; giá ưu đãi 820.000đ.') == [
        ('list_price_vnd',900000), ('discount_vnd',80000), ('price_vnd',820000), ('promo_active',True)]
    assert pairs('Giảm giá 65.000đ.') == [('discount_vnd',65000), ('promo_active',True)]


def test_conditional_comma_does_not_become_unconditional_benefit():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Nếu mua hai chiếc, được miễn phí vận chuyển.')
    assert result['claims'] == []
    assert result['candidates'][0]['reason'] == 'qualified_not_representable'


def test_price_fee_total_in_independent_conjuncts():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Giá 750.000đ và phí đổi 35.000đ và tổng tiền 785.000đ.')
    assert [(c['field'], c['value']) for c in result['claims']] == [('price_vnd',750000),('exchange_fee_vnd',35000)]
    assert result['candidates'][-1]['reason'] == 'unsupported_mapping'


def test_markdown_policy_and_first_exchange_scope():
    from eval_harness.extractor import extract_detailed
    assert pairs('Thời hạn đổi trả là **9 ngày**.') == [('return_days',9)]
    result=extract_detailed('Lần đổi size hoặc màu đầu tiên được **miễn phí** hoàn toàn.')
    assert result['claims'] == []
    assert result['candidates'][0]['reason'] == 'qualified_not_representable'


def test_calendar_date_before_delivery_predicate_is_understood():
    from eval_harness.extractor import extract_detailed
    result=extract_detailed('Dự kiến ngày 19/12 hàng sẽ giao đến anh.')
    assert result['claims'] == []
    assert result['candidates'][0]['reason'] == 'unsupported_mapping'
    assert result['candidates'][0]['qualifiers'] == {'category':'calendar_delivery'}


@pytest.mark.parametrize('text,current,historical', [
    ('Chính sách hiện hành phiên bản 2026-10. Thay thế phiên bản 2026-06.', ['2026-10'], ['2026-06']),
    ('Phiên bản 2026-10 thay thế phiên bản 2026-06.', ['2026-10'], ['2026-06']),
    ('Phiên bản 2026-06 được thay thế bởi phiên bản 2026-10.', ['2026-10'], ['2026-06']),
    ('Hiện vẫn áp dụng phiên bản 2026-06.', ['2026-06'], []),
    ('Không phải phiên bản 2026-06; hiện dùng 2026-10.', ['2026-10'], []),
    ('Trước đây dùng 2026-06.', [], ['2026-06']),
    ('Đơn trước 01/10 vẫn theo bản 2026-06.', [], []),
    ('Bản mới có thay thế 2026-06 không?', [], []),
    ('Khách nói “hiện dùng phiên bản 2026-06”.', [], []),
    ('Phiên bản 2026-10 không thay thế phiên bản 2026-06.', [], []),
])
def test_policy_version_roles(text, current, historical):
    claims = extract_claims(text, [])
    assert [c['value'] for c in claims if c['field'] == 'policy_version'] == current
    assert [c['value'] for c in claims if c['field'] == 'historical_policy_version'] == historical


def test_sc07_original_changelog_keeps_new_version_only_current():
    text = 'Theo thông tin chính sách đã kiểm tra: # Nhật ký thay đổi chính sách — Shop BTC\n\n01/10/2026 — Chính sách đổi trả phiên bản 2026-10\nThay thế phiên bản 2026-06. Thay đổi: thời hạn đổi trả 14 → **7 ngày**; đổi size lần đầu **miễn phí** (trước: 20.000đ); hoàn tiền 7 → **3–5 ngày làm việc**; lỗi nhà sản xuất đổi mới 15 → **30 ngày** (gia dụng, mẹ & bé). Đơn tạo trước 01/10/2026 vẫn áp dụng bản cũ.'
    claims = extract_claims(text, [])
    assert [c['value'] for c in claims if c['field'] == 'policy_version'] == ['2026-10']


def test_replaced_version_without_named_successor_is_historical():
    claims = extract_claims('Phiên bản 2026-06 đã bị thay thế.', [])
    assert [(c['field'],c['value']) for c in claims] == [('historical_policy_version','2026-06')]


@pytest.mark.parametrize('text,expected', [
    ('Mẫu này được bảo hành chính hãng 24 tháng.', [('warranty_months', 24)]),
    ('Bảo hành chính hãng trong mười tám tháng.', [('warranty_months', 18)]),
    ('Chị được đổi hoặc trả sản phẩm trong vòng 7 ngày.', [('return_days', 7)]),
    ('Anh được đổi hoặc trả trong vòng 9 ngày.', [('return_days', 9)]),
])
def test_explicit_policy_durations_are_not_lost(text, expected):
    assert pairs(text) == expected


def test_spoken_hundreds_keep_tens_inside_the_same_group():
    assert pairs('Giá một triệu bảy trăm bốn mươi nghìn đồng.') == [('price_vnd', 1740000)]


@pytest.mark.parametrize('text', [
    'Em chưa xác minh được giá cuối để so sánh với mức chi của mình ạ.',
    'Em chưa có thông tin về khuyến mãi hiện tại.',
    'Chị chờ em một chút để em kiểm tra giá chính xác nhất nhé.',
    'Theo thông tin chính sách đã kiểm tra: Phí vận chuyển',
    'Về chế độ bảo hành',
])
def test_headings_and_explicit_lack_of_information_are_not_factual_claims(text):
    from eval_harness.extractor import extract_detailed
    result = extract_detailed(text)
    assert result['claims'] == []
    assert all(c['disposition'] == 'excluded' and c['reason'] == 'not_assertion'
               for c in result['candidates'] if c['kind'] == 'claim')
