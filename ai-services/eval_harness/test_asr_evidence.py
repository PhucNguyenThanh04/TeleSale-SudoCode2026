"""ASR scores require matching artifacts, scope and separate entity evidence."""
import json
from pathlib import Path

from speech.btc import load_reference_eval, text_sha256
from speech.evaluate import score_run
from speech.normalize import rules_fingerprint
from eval_harness.test_official_pipeline import BTC


def asr_score(tmp_path):
    dataset, run = tmp_path / 'dataset', tmp_path / 'run'
    dataset.mkdir()
    run.mkdir()
    gt = {'reference_date': '2026-10-15', 'dialogues': [{'id': 'TEAM1',
        'full_text': 'dạ', 'entities': {'price_vnd': 1000, 'phone': '0900000000'},
        'turns': [{'idx': 1, 'speaker': 'C', 'text': 'dạ'}]}]}
    (dataset / 'ground_truth.json').write_text(json.dumps(gt))
    (run / 'hypotheses.json').write_text(json.dumps({'TEAM1': {'text': 'dạ',
        'entities': {'price_vnd': 1000, 'phone': '0900000000'}}}))
    (run / 'run.json').write_text(json.dumps({**rules_fingerprint(), 'device': 'cpu',
        'model': 'offline-test-model', 'ground_truth_sha256': text_sha256(dataset / 'ground_truth.json')}))
    score_run(dataset, run, load_reference_eval(BTC), ())
    return dataset, run


def test_one_team_file_does_not_prove_required_asr_coverage(tmp_path):
    from eval_harness.asr_evidence import inspect_asr
    dataset, run = asr_score(tmp_path)
    result = inspect_asr(dataset, run, btc_root=BTC, group='team')
    assert result['input_integrity'] is True
    assert result['coverage_sufficient'] is False
    assert result['asr_evidence_ready'] is False
    assert result['metrics']['money']['value'] == 100


def test_edited_hypotheses_invalidate_saved_asr_score(tmp_path):
    from eval_harness.asr_evidence import inspect_asr
    dataset, run = asr_score(tmp_path)
    (run / 'hypotheses.json').write_text('{}')
    result = inspect_asr(dataset, run, btc_root=BTC, group='team')
    assert result['input_integrity'] is False
    assert result['asr_evidence_ready'] is False


def test_team_ground_truth_cannot_be_presented_as_btc_audio(tmp_path):
    from eval_harness.asr_evidence import inspect_asr
    dataset, run = asr_score(tmp_path)
    result = inspect_asr(dataset, run, btc_root=BTC, group='btc')
    assert result['btc_ground_truth_matches'] is False
    assert result['asr_evidence_ready'] is False
