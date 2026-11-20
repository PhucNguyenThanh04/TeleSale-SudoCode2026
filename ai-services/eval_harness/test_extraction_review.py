import json

import pytest

from eval_harness.extraction_report import summarize_extraction, sha256
from eval_harness.test_extraction_report import fixture_pair


def report_fixture(tmp_path):
    traces, sides = fixture_pair(tmp_path, 'Miễn phí thu hộ COD ạ.')
    for path in traces.values():
        row = json.loads(path.read_text())
        row.update(user_text='Phí COD thế nào?', tool_calls=[{'name': 'pricing.get_quote',
            'args': {}, 'result': {'applied_promos': [{'promo_code': 'COD-0', 'type': 'freecod'}]}}])
        path.write_text(json.dumps(row) + '\n')
    report = tmp_path / 'extraction_report.json'
    report.write_text(json.dumps(summarize_extraction(traces, sides, {})))
    return report


def completed_review(report):
    from eval_harness.extraction_review import review_template, evidence_reference
    review = review_template(report)
    review['reviewer'] = {'name': 'Offline reviewer', 'kind': 'assistant'}
    for item in review['candidates']:
        item.update(decision='supported', note='COD-0 explicitly grants free COD collection.',
            evidence=[evidence_reference(report, item, '/tool_calls/0/result/applied_promos/0')])
    return review


def test_template_remains_pending_and_keeps_unsupported_mapping_visible(tmp_path):
    from eval_harness.extraction_review import review_template, inspect_review
    report = report_fixture(tmp_path)
    review = review_template(report)
    assert len(review['candidates']) == 2
    assert {item['decision'] for item in review['candidates']} == {'pending'}
    assert {item['reason'] for item in review['candidates']} == {'unsupported_mapping'}
    review['reviewer'] = {'name': 'Reviewer', 'kind': 'assistant'}
    assert inspect_review(report, review)['complete'] is False


def test_complete_review_preserves_extraction_and_scorer_artifacts(tmp_path):
    from eval_harness.extraction_review import inspect_review
    report = report_fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = inspect_review(report, completed_review(report))
    assert result['complete'] is True
    assert result['reviewer']['kind'] == 'assistant'
    assert result['reviewed'] == 2
    assert result['limitations']
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize('damage', ['partial', 'duplicate', 'candidate', 'report', 'evidence_hash',
    'own_speech', 'unknown_row', 'other_configuration', 'missing_evidence', 'missing_note', 'reviewer'])
def test_incomplete_or_tampered_review_is_rejected(tmp_path, damage):
    from eval_harness.extraction_review import inspect_review
    report = report_fixture(tmp_path)
    review = completed_review(report)
    item = review['candidates'][0]
    if damage == 'partial': review['candidates'].pop()
    elif damage == 'duplicate': review['candidates'].append(item)
    elif damage == 'candidate': item['candidate_sha256'] = 'wrong'
    elif damage == 'report': review['extraction_report_sha256'] = 'wrong'
    elif damage == 'evidence_hash': item['evidence'][0]['sha256'] = 'wrong'
    elif damage == 'own_speech': item['evidence'][0]['pointer'] = '/agent_text'
    elif damage == 'unknown_row': item['evidence'][0]['turn'] = 99
    elif damage == 'other_configuration': item['evidence'][0]['config'] = 'baseline_no_memory'
    elif damage == 'missing_evidence': item['evidence'] = []
    elif damage == 'missing_note': item['note'] = ''
    else: review['reviewer']['name'] = ''
    with pytest.raises(ValueError): inspect_review(report, review)


@pytest.mark.parametrize('decision', ['pending', 'contradicted', 'unverifiable'])
def test_a_reviewed_unresolved_or_wrong_claim_does_not_become_a_pass(tmp_path, decision):
    from eval_harness.extraction_review import inspect_review
    report = report_fixture(tmp_path)
    review = completed_review(report)
    review['candidates'][0]['decision'] = decision
    assert inspect_review(report, review)['complete'] is False


def test_real_claim_cannot_be_discarded_as_a_heading_without_explanation(tmp_path):
    from eval_harness.extraction_review import inspect_review
    report = report_fixture(tmp_path)
    review = completed_review(report)
    review['candidates'][0].update(decision='not_assertion', evidence=[], note='')
    with pytest.raises(ValueError): inspect_review(report, review)


@pytest.mark.parametrize('state,expected', [('supported', 'pass'), ('pending', 'fail'), ('tampered', 'missing')])
def test_acceptance_requires_a_complete_bound_review_and_keeps_other_gates(tmp_path, state, expected):
    from eval_harness.test_official_pipeline import _case, BTC
    from eval_harness.official_pipeline import publish_pair
    from eval_harness.extraction_report import write_extraction_sidecar
    from eval_harness.extractor import extract_detailed
    from eval_harness.m1_acceptance import inspect_run

    scenarios, traces, metadata = _case(tmp_path)
    sides = {}
    for config, path in traces.items():
        row = json.loads(path.read_text())
        row.update(agent_text='Dạ, miễn phí thu hộ COD ạ.', user_text='Phí COD thế nào?',
            tool_calls=[{'name': 'pricing.get_quote', 'args': {'sku': 'SKU-LOCAL', 'on': '2026-10-25'},
                'result': {'sku': 'SKU-LOCAL', 'final_price_vnd': 100000,
                    'applied_promos': [{'promo_code': 'COD-0', 'type': 'freecod'}]}}])
        extracted = extract_detailed(row['agent_text'])
        row.update(questions=extracted['questions'], claims=extracted['claims'])
        path.write_text(json.dumps(row) + '\n')
        sides[config] = tmp_path / (config + '.extraction.jsonl')
        write_extraction_sidecar(path, sides[config])
    result = publish_pair(scenarios, traces['full'], traces['baseline_no_memory'],
        tmp_path / 'btc_score.json', metadata, btc_root=BTC, extraction_sidecars=sides)
    run = {'status': result['status'], 'run_id': 'review-fixture', 'score': 'btc_score.json', 'subset': False,
        'conversation_measurement': {}, 'traces': {k: v.name for k, v in traces.items()},
        'manifests': {k: k + '.manifest.json' for k in traces},
        'extraction_report': {'path': 'extraction_report.json',
            'sha256': sha256(tmp_path / 'extraction_report.json')}}
    (tmp_path / 'run.json').write_text(json.dumps(run))
    review = completed_review(tmp_path / 'extraction_report.json')
    if state == 'pending': review['candidates'][0]['decision'] = 'pending'
    if state == 'tampered': review['extraction_report_sha256'] = 'wrong'
    review_path = tmp_path / 'review.json'
    review_path.write_text(json.dumps(review))
    report = inspect_run(tmp_path, btc_root=BTC, extraction_review=review_path)
    gates = {check['name']: check for check in report['checks']}
    assert gates['artifact_integrity']['status'] == 'pass'
    assert gates['extraction_review']['status'] == expected
    assert gates['latency_sample_size']['status'] == 'fail'
    assert report['conversation_accepted'] is False
