import pytest
from eval_harness.extractor import extract_questions


@pytest.mark.parametrize("text,slots", [
    ("Mẫu có khóa trẻ em cho bé nhà mình, chị đã trao đổi với anh nhà chưa ạ?", ["blocker"]),
    ("Phòng 28m2 và nhà có trẻ nhỏ. Mình đã cân nhắc xong chưa ạ?", ["blocker"]),
    ("Nhà mình có trẻ nhỏ không ạ?", ["has_children"]),
    ("Mình muốn lấy size và màu nào ạ?", ["size", "color"]),
    ("Lần trước mình xem phòng 28m2, hôm nay ngân sách khoảng bao nhiêu ạ?", ["budget_vnd"]),
    ("Mình xem mẫu giày nào ạ?", ["product_advised"]),
    ("Mẫu này có khóa trẻ em. Mình đã bàn với người nhà xong chưa ạ?", ["blocker"]),
])
def test_question_targets(text, slots):
    assert [q["slot"] for q in extract_questions(text)] == slots


def test_question_type_and_statement_are_distinct():
    assert extract_questions("Nhà mình có trẻ nhỏ, mẫu này có khóa an toàn.") == []
    assert extract_questions("Phòng vẫn 28m2 đúng không ạ?")[0]["type"] == "confirm"


@pytest.mark.parametrize('text,slot', [
    ('Chị cần em hỗ trợ gì thêm không ạ?', 'other'),
    ('Cho em xin mã đơn hàng ạ.', 'order_id'),
    ('Chị cho em biết địa chỉ giao hàng nhé.', 'address'),
    ('Chị thanh toán bằng gì ạ?', 'payment'),
])
def test_fallback_and_requests_without_question_mark(text, slot):
    assert [q['slot'] for q in extract_questions(text)] == [slot]


def test_product_list_preserves_requested_slot():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Anh chọn mẫu nào trong danh sách Aster, Brio, Coda ạ?')
    assert [(q['slot'], q['type']) for q in result['questions']] == [('product_advised', 'open')]


def test_unknown_confirm_is_open_and_flagged():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Chỉ số độ ẩm là 50 đúng không ạ?')
    assert [(q['slot'], q['type']) for q in result['questions']] == [('other', 'open')]
    assert result['candidates'][0]['uncertainty'] == ['unresolved_slot']


def test_quoted_question_is_excluded():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Khách hỏi: “Anh chọn size nào?”')
    assert result['questions'] == []
    assert result['candidates'][0]['disposition'] == 'excluded'


def test_markdown_multislot_and_real_repetition():
    from eval_harness.extractor import extract_questions
    assert [q['slot'] for q in extract_questions('**Chị cho biết cỡ và màu muốn lấy nhé.**')] == ['size', 'color']
    assert len(extract_questions('Anh chọn size nào? Anh chọn size nào?')) == 2


def test_unclear_question_type_preserves_known_slot():
    from eval_harness.extractor import extract_detailed
    result = extract_detailed('Size 42?')
    assert result['questions'][0]['slot'] == 'size'
    assert result['questions'][0]['type'] == 'open'
    assert result['candidates'][0]['uncertainty'] == ['unresolved_question_type']


def test_offer_choice_does_not_ask_the_slot_in_purpose_clause():
    from eval_harness.extractor import extract_questions
    assert [q['slot'] for q in extract_questions('Anh có muốn mua sản phẩm này không để em tra màu trong kho?')] == ['product_advised']


def test_narrative_interrogative_word_is_not_a_request():
    from eval_harness.extractor import extract_detailed
    result=extract_detailed('Em đang kiểm tra mẫu nào còn hàng để tư vấn.')
    assert result['questions'] == []
    assert result['claims'] == []
    assert all(c['disposition']=='excluded' for c in result['candidates'])


def test_negative_indefinite_and_future_invitation_are_not_questions():
    from eval_harness.extractor import extract_detailed
    for text in ('Hiện sản phẩm chưa có chương trình giảm giá nào nhé.',
                 'Khi nào cần hỗ trợ anh cứ báo em nhé.'):
        result=extract_detailed(text)
        assert result['questions'] == [], text
        assert all(c['disposition']=='excluded' for c in result['candidates'] if c['kind']=='question')


def test_product_reference_without_interrogative_which():
    from eval_harness.extractor import extract_questions
    for text in ('Anh đang quan tâm mẫu Boreal đúng không?',
                 'Chị cho em xin tên máy hoặc mã sản phẩm nhé.'):
        assert [q['slot'] for q in extract_questions(text)] == ['product_advised']


@pytest.mark.parametrize('text,expected', [
    ('Em sẵn sàng hỗ trợ anh bất cứ lúc nào ạ.', []),
    ('Chị chốt mẫu này để em lên đơn cho mình nhé?', [('product_advised', 'confirm')]),
    ('Chị chọn mẫu nào để em lên đơn nhé?', [('product_advised', 'open')]),
    ('Anh vẫn lấy size 42 màu đen nhé?', [('size', 'confirm'), ('color', 'confirm')]),
    ('Chị muốn em lên đơn cho mình luôn không chị?', [('purchase_consent', 'open')]),
    ('Anh muốn lấy mỗi loại một chiếc hay số lượng khác ạ?', [('quantity', 'open')]),
    ('Anh muốn em hỗ trợ đổi sang size lớn hơn hay trả hàng ạ?', [('size', 'open')]),
    ('Mức ngân sách này cho mỗi sản phẩm hay tổng cả đơn ạ?', [('budget_vnd', 'open')]),
    ('Mình muốn em kiểm tra tồn kho phương án này không ạ?', [('stock_check_consent', 'open')]),
    ('Anh cho em xin lý do trả hàng nhé.', [('return_reason', 'open')]),
    ('Chị có yêu cầu đặc biệt nào cho máy không ạ?', [('product_requirements', 'open')]),
])
def test_requests_and_confirmations_without_inventing_known_profile_slots(text, expected):
    from eval_harness.extractor import extract_detailed
    result = extract_detailed(text)
    assert [(q['slot'], q['type']) for q in result['questions']] == expected
    assert not any(c['uncertainty'] for c in result['candidates'] if c['kind'] == 'question')


@pytest.mark.parametrize('text,expected', [
    ('Khi nào cần hỗ trợ hoặc muốn đặt hàng mẫu quạt Panasonic F-409, anh nhắn em nhé.', []),
    ('Khi nào anh muốn đặt hàng mẫu quạt Panasonic F-409?', [('other', 'open')]),
    ('Mình cho em làm rõ điều kiện cần áp dụng nhé?', [('other', 'open')]),
    ('Anh có muốn em xử lý tiếp bây giờ không anh?', [('other', 'open')]),
    ('Anh chốt lấy một máy luôn em lên đơn cho mình nhé?', [('purchase_consent', 'confirm')]),
    ('Dạ anh, anh đang quan tâm đến mẫu Xiaomi 4 Pro đúng không ạ?', [('product_advised', 'confirm')]),
])
def test_remaining_saved_run_questions_have_explicit_roles(text, expected):
    from eval_harness.extractor import extract_detailed
    result = extract_detailed(text)
    assert [(q['slot'], q['type']) for q in result['questions']] == expected
    assert not any(c['uncertainty'] for c in result['candidates'] if c['kind'] == 'question')
