"""Speech regressions from the M1 audit; no truth/tool input to extraction."""
import pytest

from eval_harness.extractor import extract_detailed


@pytest.mark.parametrize('text', [
    'Lần đổi này hoàn toàn miễn phí và không phát sinh thêm chi phí nào.',
    'Khi nào cần hỗ trợ hoặc muốn chốt đơn, chị báo em nhé.',
])
def test_narrative_nao_is_not_a_question(text):
    result = extract_detailed(text)
    assert result['questions'] == []
    assert any(c['kind'] == 'question' and c['reason'] == 'narrative' for c in result['candidates'])


@pytest.mark.parametrize('text', [
    'Tổng giá 779.000đ.', 'Hai sản phẩm có tổng giá 779.000đ.',
    'Miễn phí thu hộ COD ạ.', 'Miễn phí thu hộ (COD) chị nhé.',
    'Ngày giao dự kiến là 2026-10-22.',
])
def test_known_non_unit_price_fields_remain_visible_without_false_projection(text):
    result = extract_detailed(text)
    assert result['claims'] == []
    assert result['candidates']
    assert all(c['reason'] == 'unsupported_mapping' for c in result['candidates'])


@pytest.mark.parametrize('text', [
    'Đơn từ **500.000đ**: miễn phí vận chuyển toàn quốc với ngành mẹ & bé (chương trình MOM-FREESHIP).',
    'Miễn phí với đơn từ 2.000.000đ.',
])
def test_order_threshold_is_not_unconditional_freeship(text):
    result = extract_detailed(text)
    assert result['claims'] == []
    assert result['candidates'][0]['reason'] == 'qualified_not_representable'
    assert result['candidates'][0]['qualifiers']['condition']


@pytest.mark.parametrize('text', [
    'Theo thông tin chính sách đã kiểm tra: Bảo hành mở rộng',
    'Về điều kiện đổi trả', 'Giá bán', '01/08/2026 — Bảo hành',
    'Báo giá cần được xác nhận lại trước khi tạo đơn.',
    'Theo thông tin chính sách đã kiểm tra: 01/08/2026 — Bảo hành',
    'Em gửi anh giá và tình trạng kho của hai sản phẩm:',
    'Chị đợi em một chút để kiểm tra chi tiết hơn về tiến độ giao hàng cho mình nhé.',
])
def test_policy_headings_and_confirmation_requirement_are_not_claims(text):
    result = extract_detailed(text)
    assert result['claims'] == []
    assert result['candidates']
    assert all(c['reason'] == 'not_assertion' for c in result['candidates'])


@pytest.mark.parametrize('text,field,value', [
    ('Thời hạn đổi trả cho các đơn hàng mới là trong vòng 7 ngày kể từ ngày nhận hàng.', 'return_days', 7),
    ('Thay đổi: thời hạn đổi trả 14 → **7 ngày**.', 'return_days', 7),
    ('Mẫu này hiện đang có sẵn trong kho.', 'in_stock', True),
    ('Mẫu này hiện không có sẵn trong kho.', 'in_stock', False),
    ('Mẫu này chưa có sẵn trong kho.', 'in_stock', False),
])
def test_explicit_duration_and_stock_survive_wording_variants(text, field, value):
    assert [(c['field'], c['value']) for c in extract_detailed(text)['claims']] == [(field, value)]


def test_review_does_not_discard_real_but_unresolved_claims():
    for text in ['Lõi lọc không được bảo hành.', 'Đơn vẫn chưa bàn giao cho vận chuyển.',
                 'Giá hiện tại cao hơn mức mình đã đồng ý trước đó.']:
        result = extract_detailed(text)
        assert any(c['disposition'] == 'unresolved' for c in result['candidates'])


def test_real_questions_and_unconditional_shipping_still_emitted():
    assert extract_detailed('Chị muốn lấy mẫu nào?')['questions']
    assert extract_detailed('Khi nào chị muốn nhận hàng?')['questions']
    assert [(c['field'], c['value']) for c in extract_detailed('Miễn phí vận chuyển.')['claims']] == [('freeship', True)]


def test_later_exchange_condition_stays_with_its_fee():
    result = extract_detailed('Từ lần đổi thứ hai trở đi, phí vận chuyển sẽ là 30.000đ/chiều.')
    assert result['claims'] == []
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['reason'] == 'qualified_not_representable'
    assert '30.000' in result['candidates'][0]['text']


def test_available_variant_does_not_become_unscoped_stock():
    result = extract_detailed('Giày màu xám size 42 hiện đang có sẵn trong kho.')
    assert result['claims'] == []
    assert result['candidates'][0]['qualifiers'] == {'size': 42}


@pytest.mark.parametrize('text', [
    'Khi cần bảo hành', 'Về quy định giao hàng', 'Về yêu cầu đổi áo của chị',
    'Để tham khảo trước khi mua: Điều kiện đổi trả',
])
def test_standalone_topic_fragments_are_not_unresolved_assertions(text):
    result = extract_detailed(text)
    assert result['claims'] == []
    assert result['candidates']
    assert all(c['disposition'] == 'excluded' and c['reason'] == 'not_assertion'
               for c in result['candidates'])


def test_decision_about_previously_named_product_is_a_blocker_followup():
    text = 'Không biết chị đã trao đổi với anh nhà và có quyết định chọn mẫu này chưa ạ?'
    questions = extract_detailed(text)['questions']
    assert len(questions) == 1
    assert questions[0]['slot'] == 'blocker'


def test_open_product_identity_question_remains_product_advised():
    questions = extract_detailed('Chị đã quyết định chọn mẫu nào chưa ạ?')['questions']
    assert questions[0]['slot'] == 'product_advised'


@pytest.mark.parametrize('text,slot,kind', [
    ('Khóa trẻ em có phải yêu cầu bắt buộc của mình không ạ?', 'product_requirements', 'confirm'),
    ('Mình có đồng ý điều chỉnh mức chi này không ạ?', 'budget_consent', 'open'),
])
def test_required_feature_and_budget_permission_are_not_profile_or_blocker(text, slot, kind):
    result = extract_detailed(text)
    assert [(q['slot'], q['type']) for q in result['questions']] == [(slot, kind)]
