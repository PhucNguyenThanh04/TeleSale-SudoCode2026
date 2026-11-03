"""Questions are classified by requested information, not contextual keywords."""
import pytest
from eval_harness.extractor import extract_questions


@pytest.mark.parametrize("text,slots", [
    ("Mẫu có khóa trẻ em cho bé nhà mình, chị đã trao đổi với anh nhà chưa ạ?", ["blocker"]),
    ("Phòng 28m2 và nhà có trẻ nhỏ. Mình đã cân nhắc xong chưa ạ?", ["blocker"]),
    ("Nhà mình có trẻ nhỏ không ạ?", ["has_children"]),
    ("Mình muốn lấy size và màu nào ạ?", ["size", "preferred_color"]),
    ("Lần trước mình xem phòng 28m2, hôm nay ngân sách khoảng bao nhiêu ạ?", ["budget_vnd"]),
    ("Mình xem mẫu giày nào ạ?", ["product_advised"]),
    ("Mẫu này có khóa trẻ em. Mình đã bàn với người nhà xong chưa ạ?", ["blocker"]),
])
def test_question_targets(text, slots):
    assert [q["slot"] for q in extract_questions(text)] == slots


def test_question_type_and_statement_are_distinct():
    assert extract_questions("Nhà mình có trẻ nhỏ, mẫu này có khóa an toàn.") == []
    assert extract_questions("Phòng vẫn 28m2 đúng không ạ?")[0]["type"] == "confirm"
