"""Detailed annotations share projections without scenario or tool truth input."""
from eval_harness import extractor


def test_detailed_candidates_project_one_to_one():
    detailed = getattr(extractor, 'extract_detailed', None)
    assert callable(detailed), 'a common detailed core is required'
    result = detailed('Mình muốn lấy size và màu nào ạ?')
    assert [q['slot'] for q in result['questions']] == ['size', 'color']
    emitted = [c for c in result['candidates'] if c['disposition'] == 'emitted']
    assert [c['projection'] for c in emitted] == result['questions']
    assert len({c['candidate_id'] for c in emitted}) == 2
    assert all(c['uncertainty'] == [] for c in emitted)


def test_tool_truth_cannot_change_spoken_claims():
    detailed = getattr(extractor, 'extract_detailed', None)
    assert callable(detailed)
    text = 'Giá cuối là 870.000đ.'
    expected = [{'field': 'price_vnd', 'value': 870000, 'source': 'text', 'text': text.rstrip('.')}]
    assert detailed(text)['claims'] == expected
    for amount in (1, 9999999):
        assert extractor.extract_claims(text, [{'name':'pricing.get_quote',
            'result':{'final_price_vnd':amount}}]) == expected


def test_generic_question_is_not_uncertain_and_empty_turn_has_no_candidates():
    detailed = getattr(extractor, 'extract_detailed', None)
    assert callable(detailed)
    result = detailed('Chị cần em hỗ trợ gì thêm không ạ?')
    assert result['questions'][0]['slot'] == 'other'
    assert result['candidates'][0]['reason'] == 'generic_question'
    assert detailed('Dạ vâng.') == {'questions':[], 'claims':[], 'candidates':[]}
