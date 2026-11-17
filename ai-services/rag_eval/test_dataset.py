import json
from pathlib import Path

import pytest

from rag_eval import dataset

BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'


def test_btc_cases_keep_labels_out_of_runtime_inputs():
    cases = dataset.load_cases(BTC)
    assert len(cases) == 60
    case = next(c for c in cases if c['qid'] == 'Q43')
    assert case['input']['verified_order_date'] == '2026-09-28'
    assert case['input']['date_source'] == 'eval_fixture'
    assert case['input']['on'] == '2026-10-09'
    assert not {'expected_answer', 'relevant_chunk_ids', 'type', 'qid'} & case['input'].keys()
    assert 'DT-OLD-01' in case['labels']['relevant_chunk_ids']


def test_contexts_reject_unproven_dates_and_label_injection(tmp_path):
    config = json.loads(dataset.DEFAULT_CONTEXTS.read_text())
    config['defaults'].pop('date_source')
    path = tmp_path / 'contexts.json'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        dataset.load_cases(BTC, path)
    config['defaults']['date_source'] = 'eval_fixture'
    config['defaults']['expected_answer'] = 'leaked'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        dataset.load_cases(BTC, path)


def test_duplicate_qa_rejected(tmp_path):
    (tmp_path / 'rag').mkdir()
    qa = json.loads((BTC / 'rag/qa_labeled.json').read_text())
    qa['questions'].append(qa['questions'][0])
    (tmp_path / 'rag/qa_labeled.json').write_text(json.dumps(qa))
    with pytest.raises(ValueError, match='duplicate'):
        dataset.load_cases(tmp_path)


def test_frozen_inputs_and_read_tools_are_safe(tmp_path):
    dataset.freeze_inputs(BTC, tmp_path)
    cases = dataset.load_cases(tmp_path / 'btc', tmp_path / 'contexts.json')
    c = next(c for c in cases if c['qid'] == 'Q57')
    observations = dataset.reference_observations(tmp_path / 'btc', c['input'])
    assert observations and observations[0]['name'] == 'pricing.quote_order'
    assert '_internal' not in json.dumps(observations)
    assert observations[0]['result']
    for qid in ('Q27', 'Q31', 'Q58'):
        c = next(c for c in cases if c['qid'] == qid)
        observations = dataset.reference_observations(tmp_path / 'btc', c['input'])
        assert observations and 'error' not in observations[0]['result']
        assert 'customer_phone' not in json.dumps(observations)
    with pytest.raises(ValueError, match='read tool'):
        dataset.reference_observations(tmp_path / 'btc', {'on': '2026-10-15',
            'read_tools': [{'name': 'order.create', 'args': {}}]})
