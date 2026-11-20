import json
from pathlib import Path
import pytest

from speech.btc import load_reference_eval, text_sha256
from speech.evaluate import score_run
from speech.normalize import rules_fingerprint
from eval_harness.test_official_pipeline import BTC


def asr_score(tmp_path, count=1, prefix='TEAM'):
    dataset, run = tmp_path / 'dataset', tmp_path / 'run'
    dataset.mkdir()
    run.mkdir()
    gt = {'reference_date': '2026-10-15', 'dialogues': [{'id': f'{prefix}{index}',
        'full_text': 'dạ', 'entities': {'price_vnd': 1000, 'phone': '0900000000'},
        'turns': [{'idx': 1, 'speaker': 'C', 'text': 'dạ'}]} for index in range(1, count+1)]}
    (dataset / 'ground_truth.json').write_text(json.dumps(gt))
    (run / 'hypotheses.json').write_text(json.dumps({d['id']: {'text': 'dạ',
        'entities': {'price_vnd': 1000, 'phone': '0900000000'}} for d in gt['dialogues']}))
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


def test_btc_public_sample_does_not_prove_twelve_dialogue_coverage(tmp_path):
    from eval_harness.asr_evidence import inspect_asr
    dataset, run = asr_score(tmp_path)
    btc = tmp_path / 'btc'
    (btc / 'asr').mkdir(parents=True)
    (btc / 'eval').mkdir()
    (btc / 'asr/ground_truth.json').write_bytes((dataset / 'ground_truth.json').read_bytes())
    (btc / 'eval/reference_eval.py').write_bytes((BTC / 'eval/reference_eval.py').read_bytes())
    result = inspect_asr(dataset, run, btc_root=btc, group='btc')
    assert result['btc_ground_truth_matches'] is True
    assert result['coverage_sufficient'] is False


@pytest.mark.parametrize('changed', ['score.json', 'hypotheses.json', 'run.json', 'audio'])
def test_asr_attachment_is_rechecked_against_source_artifacts(tmp_path, changed):
    from eval_harness.asr_evidence import collect_asr_evidence, verify_asr_evidence
    dataset, run = asr_score(tmp_path)
    audio = dataset / 'audio'; audio.mkdir()
    (audio / 'TEAM1.wav').write_bytes(b'offline audio fixture')
    score_run(dataset, run, load_reference_eval(BTC), ())
    evidence = collect_asr_evidence({'team': {'dataset': dataset, 'run': run}}, btc_root=BTC)
    assert verify_asr_evidence(evidence, btc_root=BTC) is True
    path = audio / 'TEAM1.wav' if changed == 'audio' else run / changed
    path.write_bytes(path.read_bytes() + b' ')
    assert verify_asr_evidence(evidence, btc_root=BTC) is False


def test_manual_ready_flag_cannot_replace_asr_verification(tmp_path):
    from eval_harness.asr_evidence import collect_asr_evidence, verify_asr_evidence
    dataset, run = asr_score(tmp_path)
    evidence = collect_asr_evidence({'team': {'dataset': dataset, 'run': run}}, btc_root=BTC)
    evidence['groups']['team']['report']['asr_evidence_ready'] = True
    assert verify_asr_evidence(evidence, btc_root=BTC) is False


def test_edited_official_asr_numbers_are_rejected_even_before_attachment(tmp_path):
    from eval_harness.asr_evidence import inspect_asr
    dataset, run = asr_score(tmp_path)
    score = json.loads((run / 'score.json').read_text())
    score['official']['WER'] = 99
    (run / 'score.json').write_text(json.dumps(score))
    report = inspect_asr(dataset, run, btc_root=BTC, group='team')
    assert report['input_integrity'] is False


def test_two_complete_bound_groups_can_pass_asr_evidence_without_transcription(tmp_path):
    from eval_harness.asr_evidence import collect_asr_evidence, verify_asr_evidence
    sources = {}
    btc = tmp_path / 'btc'
    (btc / 'asr').mkdir(parents=True)
    (btc / 'eval').mkdir()
    (btc / 'eval/reference_eval.py').write_bytes((BTC / 'eval/reference_eval.py').read_bytes())
    for group, count in [('btc', 12), ('team', 20)]:
        folder = tmp_path / group / 'fixture'; folder.mkdir(parents=True)
        dataset, run = asr_score(folder, count=count, prefix=group.upper())
        (dataset / 'audio').mkdir()
        for dialogue in json.loads((dataset / 'ground_truth.json').read_text())['dialogues']:
            (dataset / 'audio' / (dialogue['id']+'.wav')).write_bytes(b'offline audio fixture')
        score_run(dataset, run, load_reference_eval(BTC), ())
        sources[group] = {'dataset': dataset, 'run': run}
        if group == 'btc':
            (btc / 'asr/ground_truth.json').write_bytes((dataset / 'ground_truth.json').read_bytes())
    evidence = collect_asr_evidence(sources, btc_root=btc)
    assert verify_asr_evidence(evidence, btc_root=btc) is True
    assert all(g['report']['asr_evidence_ready'] for g in evidence['groups'].values())
