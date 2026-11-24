import asyncio
import json

import pytest

from rag_eval import scoring
from rag_eval.dataset import load_module, read_json, write_json
from rag_eval.runner import collect, read_trace, seal, verify_run
from rag_eval.test_dataset import BTC
from rag_eval.test_runner import Generator, Retriever


@pytest.fixture
def run(tmp_path):
    out = tmp_path / 'run'
    asyncio.run(collect(BTC, out, Retriever()))
    return out


def test_retrieval_score_matches_btc_and_hides_answer_metrics(run, tmp_path):
    out = tmp_path / 'scores'
    report = scoring.score_run(run, out)
    raw = load_module(run / 'btc/eval/reference_eval.py').rag_eval(
        run / 'btc/rag/qa_labeled.json', out / 'rag_results.json')
    assert report['btc']['recall@3'] == raw['recall@3']
    assert report['btc']['abstain_rate_restricted'] is None
    assert report['btc']['false_abstain_rate'] is None
    assert report['coverage']['expected'] == report['coverage']['recorded'] == 60
    assert report['coverage']['execution_failed'] == 1
    assert report['retrieval']['recall_denominator'] == 59
    assert report['answers']['correctness']['measured'] == 0
    assert verify_run(out)['kind'] == 'scores'


def test_btc_counts_retrieved_chunks_for_abstained_restricted_and_unanswerable(tmp_path):
    qa = {'questions': [{'qid': 'R', 'type': 'restricted', 'relevant_chunk_ids': ['NB-01']},
                        {'qid': 'U', 'type': 'unanswerable', 'relevant_chunk_ids': ['FAQ-03']}]}
    result = {'R': {'retrieved_chunk_ids': ['NB-01'], 'abstained': True, 'answer': 'Thông tin nội bộ.'},
              'U': {'retrieved_chunk_ids': ['FAQ-03'], 'abstained': True, 'answer': 'Chưa có thông tin.'}}
    write_json(tmp_path / 'qa.json', qa)
    write_json(tmp_path / 'results.json', result)
    score = load_module(BTC / 'eval/reference_eval.py').rag_eval(tmp_path / 'qa.json', tmp_path / 'results.json')
    assert score['by_type_recall@5']['restricted'] == score['by_type_recall@5']['unanswerable'] == 100
    assert score['abstain_rate_restricted'] == score['abstain_rate_unanswerable'] == 100


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'input'])
def test_resealed_bad_coverage_and_input_binding_are_rejected(run, tmp_path, change):
    manifest = verify_run(run)
    rows = read_trace(run)
    if change == 'missing': rows.pop()
    if change == 'duplicate': rows.append(rows[0])
    if change == 'unknown': rows[-1]['qid'] = 'Q999'
    if change == 'input': rows[0]['input']['query'] = 'another question'
    (run / 'trace.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    seal(run, manifest)
    with pytest.raises(ValueError):
        scoring.score_run(run, tmp_path / 'scores')


def test_tampered_trace_rejected(run, tmp_path):
    with (run / 'trace.jsonl').open('a') as stream:
        stream.write('{}\n')
    with pytest.raises(ValueError, match='hash'):
        scoring.score_run(run, tmp_path / 'scores')


def test_assertions_are_diagnostics_and_comparison_requires_same_dataset(run, tmp_path):
    checks = scoring.literal_checks('639.200đ, trong 15 ngày',
        {'must_all': ['639[.,]?200', '15 ngày'], 'must_not': ['miễn phí']})
    assert checks['passed'] is True
    assert scoring.literal_checks('639.200đ miễn phí',
        {'must_all': ['15 ngày'], 'must_not': ['miễn phí']})['passed'] is False
    scoring.score_run(run, tmp_path / 'a')
    scoring.score_run(run, tmp_path / 'b')
    comparison = scoring.compare(tmp_path / 'a', tmp_path / 'b')
    assert comparison['retrieval_delta']['recall@5'] == 0
    manifest = verify_run(tmp_path / 'b')
    report = read_json(tmp_path / 'b/report.json')
    report['provenance']['dataset_hash'] = 'different'
    write_json(tmp_path / 'b/report.json', report)
    seal(tmp_path / 'b', manifest)
    with pytest.raises(ValueError, match='dataset_hash'):
        scoring.compare(tmp_path / 'a', tmp_path / 'b')


def test_calibration_is_bound_and_reports_kappa():
    judgments = {str(i): {'business': {'correct': i % 2 == 0}} for i in range(20)}
    labels = {'trace_sha256': 'abc', 'reviewer': 'reviewer',
              'cases': {str(i): {'correct': i % 2 == 0} for i in range(20)}}
    result = scoring.calibration(labels, judgments, 'abc')
    assert result['agreement'] == result['cohens_kappa'] == 1
    assert result['sufficient_samples'] is True
    with pytest.raises(ValueError, match='trace'):
        scoring.calibration(labels, judgments, 'changed')


def test_failed_generation_does_not_claim_valid_abstention(tmp_path):
    run = tmp_path / 'run'
    asyncio.run(collect(BTC, run, Retriever(), Generator()))
    report = scoring.score_run(run, tmp_path / 'scores')
    assert report['btc']['false_abstain_rate'] is None
    assert report['btc_abstention_source'] == 'incomplete_generation_unmeasured'


def test_btc_multi_hop_formula_and_link_order_have_known_denominators(tmp_path):
    from rag_eval.dataset import load_cases
    queries = {c['qid']: c['input']['query'] for c in load_cases(BTC)}
    class Ranked(Retriever):
        async def search(self, inputs, release, top_k):
            ids = []
            if inputs['query'] == queries['Q26']:
                ids = ['VC-02', 'NQ-01', 'VC-01']
            if inputs['query'] == queries['Q32']:
                ids = ['CL-04', 'NQ-01', 'BH-01', 'NQ-02', 'BH-02']
            return {'retrieval_status': 'ok' if ids else 'no_evidence',
                'context': {'knowledge_release_id': release['release_id']},
                'evidence': [{'chunk_id': key, 'content': key,
                    'retrieved_via': 'linked' if key == 'BH-02' else 'vector'} for key in ids]}
    run = tmp_path / 'run'
    asyncio.run(collect(BTC, run, Ranked()))
    report = scoring.score_run(run, tmp_path / 'scores')
    assert report['btc']['recall@3'] == report['btc']['recall@5'] == 3.4
    assert report['btc']['multi_hop_full_recall@3'] == 8.3
    assert report['btc']['multi_hop_full_recall@5'] == 16.7
    row = next(c for c in report['cases'] if c['qid'] == 'Q32')
    assert row['retrieved_chunk_ids'][-1] == 'BH-02'
    assert row['full@3'] is False and row['full@5'] is True


def test_comparison_includes_answer_deltas_and_provenance(run, tmp_path):
    first = scoring.score_run(run, tmp_path / 'a')
    scoring.score_run(run, tmp_path / 'b')
    result = scoring.compare(tmp_path / 'a', tmp_path / 'b')
    assert result['answer_delta']['correctness'] is None
    assert result['source_reports']['before_sha256']
    assert result['before_top_k'] == first['provenance']['top_k']


def test_human_calibration_keeps_unjudged_cases_unmeasured():
    labels = {'trace_sha256': 'abc', 'reviewer': 'reviewer', 'cases': {
        'Q01': {'correct': False}, 'Q02': {'correct': True}}}
    result = scoring.calibration(labels, {'Q01': {'business': None},
        'Q02': {'business': {'correct': True}}}, 'abc')
    assert result['samples'] == 1
    assert result['agreement'] == 1
    assert result['sufficient_samples'] is False
