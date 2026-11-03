"""Known needs are statements; questions request only new blocker progress."""
import pytest
from app.agent.harness.brief_opening import build_suggested_opening
from app.agent.implementations.business_agent import _SYSTEM_PROMPT
from eval_harness.extractor import extract_questions


@pytest.mark.parametrize("sku,blocker", [("SKU-LOCAL-A", "cần hỏi người nhà"),
                                         ("SKU-OTHER-B", "cần cân nhắc thêm")])
def test_opening_only_asks_about_open_progress(sku, blocker):
    opening = build_suggested_opening(advised_products=[{"sku": sku}], open_blockers=[blocker])
    assert sku in opening
    assert [q['slot'] for q in extract_questions(opening)] == ['blocker']
    assert opening.index('.') < opening.index('?')


def test_no_blocker_does_not_probe_profile_again():
    opening = build_suggested_opening(advised_products=[{"sku": "SKU-LOCAL-A"}], open_blockers=[])
    assert extract_questions(opening) == []
    assert 'SKU-AP-Y' not in _SYSTEM_PROMPT
    assert 'ngay cả khi giá nhỉnh hơn ngân sách' not in _SYSTEM_PROMPT
