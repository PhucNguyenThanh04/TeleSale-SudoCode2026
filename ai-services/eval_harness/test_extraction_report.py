import json
import pytest
from eval_harness.extractor import extract_detailed
from eval_harness.extraction_report import make_extraction_row, summarize_extraction, verify_extraction_report


def fixture_pair(tmp_path, text='Dạ vâng.'):
    traces, sides = {}, {}
    for config in ('full', 'baseline_no_memory'):
        row = dict(run_id='r', config=config, scenario_id='generic', call='c', turn=1, agent_text=text)
        result = extract_detailed(text)
        row.update(questions=result['questions'], claims=result['claims'])
        traces[config] = tmp_path / (config + '.jsonl')
        sides[config] = tmp_path / (config + '.extraction.jsonl')
        traces[config].write_text(json.dumps(row) + '\n')
        sides[config].write_text(json.dumps(make_extraction_row(row, result)) + '\n')
    return traces, sides


def test_zero_candidate_rows_and_checked_are_not_emitted(tmp_path):
    traces, sides = fixture_pair(tmp_path)
    score = {'system': {'hallucination_rate': {'total_claims': 7}}, 'baseline': {}}
    report = summarize_extraction(traces, sides, score)
    counts = report['configs']['full']['claim']
    assert counts['detected'] == 0
    assert counts['emission_rate'] is None
    assert report['configs']['full']['btc_checked'] == score['system']
    path = tmp_path / 'extraction_report.json'
    path.write_text(json.dumps(report))
    assert verify_extraction_report(path) == report
    sides['full'].write_text('')
    with pytest.raises(ValueError):
        verify_extraction_report(path)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'fingerprint', 'projection', 'text_hash'])
def test_sidecar_mismatch_is_integrity_error(tmp_path, change):
    traces, sides = fixture_pair(tmp_path, 'Giá 700.000đ.')
    path = sides['full']
    row = json.loads(path.read_text())
    if change == 'missing': path.write_text('')
    elif change == 'duplicate': path.write_text(path.read_text() * 2)
    else:
        if change == 'fingerprint': row['extractor_fingerprint'] = 'bad'
        if change == 'projection': row['candidates'][0]['projection']['value'] = 1
        if change == 'text_hash': row['agent_text_sha256'] = 'bad'
        path.write_text(json.dumps(row) + '\n')
    with pytest.raises(ValueError): summarize_extraction(traces, sides, {})


def test_exclusions_and_uncertainty_have_disjoint_counts(tmp_path):
    traces, sides = fixture_pair(tmp_path, 'Tổng tiền 700.000đ. Độ ẩm đúng không?')
    report = summarize_extraction(traces, sides, {})
    assert report['extraction_status'] == 'needs_review'
    for kind in ('question', 'claim'):
        c = report['configs']['full'][kind]
        assert c['detected'] == c['emitted'] + c['unresolved'] + c['excluded']
    assert report['configs']['full']['question']['emitted_uncertain'] == 1
