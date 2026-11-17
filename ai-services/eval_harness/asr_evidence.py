"""Verify saved local-ASR reports with the BTC scorer; never transcribe audio."""
import argparse
import json
from pathlib import Path

from eval.score_pair import _sha
from eval_harness.m1_acceptance import _read


def _score_matches(score, gt, hypotheses, dataset, btc_root):
    from speech.btc import load_reference_eval
    from speech.evaluate import _wer_cer, _has_speakers
    segments = dataset/'audio' if _has_speakers(hypotheses) and (dataset/'audio').is_dir() else None
    actual = _wer_cer(load_reference_eval(btc_root), gt, hypotheses, segments)
    actual.pop('per_dialogue', None)
    if actual != score.get('official'):
        return False
    for kind in ('money', 'phone'):
        correct = total = 0
        for dialogue in gt['dialogues']:
            for key, value in dialogue.get('entities', {}).items():
                if not (key.endswith('_vnd') if kind == 'money' else key == 'phone'):
                    continue
                total += 1
                values = value if isinstance(value, list) else [value]
                correct += any(str(hypotheses[dialogue['id']].get('entities', {}).get(key)) == str(v)
                               for v in values)
        expected = {'correct': correct, 'total': total,
                    'value': round(100 * correct / total, 1) if total else None}
        if score.get('entity_accuracy_by_type', {}).get(kind) != expected:
            return False
    return True


def inspect_asr(dataset, run, *, btc_root, group):
    if group not in {'btc', 'team'}:
        raise ValueError('asr_group_invalid')
    dataset, run, btc_root = Path(dataset), Path(run), Path(btc_root)
    result = {'scope': 'saved_asr_report_only', 'group': group, 'asr_evidence_ready': False,
              'input_integrity': False, 'coverage_sufficient': False}
    try:
        score = _read(run / 'score.json')
        inputs = {'ground_truth': dataset / 'ground_truth.json',
                  'hypotheses': run / 'hypotheses.json', 'run_metadata': run / 'run.json'}
        hashes = {key: _sha(path) for key, path in inputs.items()}
        if score.get('input_sha256') != hashes or score.get('scorer_sha256') != _sha(btc_root / 'eval/reference_eval.py'):
            return result
        gt, hypotheses, metadata = [_read(inputs[key]) for key in ('ground_truth', 'hypotheses', 'run_metadata')]
        expected = [d['id'] for d in gt['dialogues']]
        if not expected or len(set(expected)) != len(expected) or set(expected) != set(hypotheses):
            return result
        if not _score_matches(score, gt, hypotheses, dataset, btc_root):
            return result
        result['input_integrity'] = True
        btc_matches = _read(btc_root / 'asr/ground_truth.json') == gt
        enough = btc_matches and len(expected) >= 12 if group == 'btc' else len(expected) >= 20 and not btc_matches
        official = score['official']
        entity = score.get('entity_accuracy_by_type') or {}
        entity_measured = all(type(entity.get(kind, {}).get('value')) in (int, float)
                              and entity[kind].get('total', 0) > 0 for kind in ('money', 'phone'))
        normalized = score.get('ground_truth_match') is True and score.get('rules_stale') is False
        local = metadata.get('device') in {'cpu', 'cuda'} and bool(metadata.get('model'))
        audio_count = sum((dataset / 'audio' / (key + '.wav')).is_file() for key in expected)
        audio_verified = audio_count == len(expected) and score.get('audio_sha256') == {
            key: _sha(dataset / 'audio' / (key + '.wav')) for key in expected
            if (dataset / 'audio' / (key + '.wav')).is_file()}
        measured = all(type(official.get(key)) in (int, float) for key in ('WER', 'CER', 'entity_accuracy'))
        result.update(coverage_sufficient=enough, btc_ground_truth_matches=btc_matches,
            dialogues=len(expected), audio_files_present=audio_count, audio_hashes_verified=audio_verified,
            normalization_verified=normalized,
            local_asr_recorded=local, score_sha256=_sha(run / 'score.json'), input_sha256=hashes,
            metrics={'WER': official.get('WER'), 'CER': official.get('CER'),
                     'entity_accuracy': official.get('entity_accuracy'),
                     'money': entity.get('money'), 'phone': entity.get('phone')})
        result['asr_evidence_ready'] = (enough and measured and entity_measured and normalized and local
                                        and audio_verified)
    except (OSError, ValueError, KeyError, TypeError):
        result['input_integrity'] = False
    return result


def collect_asr_evidence(sources, *, btc_root):
    """Bind optional BTC/team reports after offline score verification; never transcribe."""
    if not sources or set(sources) - {'btc', 'team'}:
        raise ValueError('asr_groups_invalid')
    root = Path(btc_root).resolve()
    groups = {}
    for group, source in sources.items():
        dataset, run = Path(source['dataset']).resolve(), Path(source['run']).resolve()
        if not dataset.is_dir() or not run.is_dir():
            raise ValueError('asr_source_directory_missing')
        groups[group] = {'dataset': str(dataset), 'run': str(run),
                         'report': inspect_asr(dataset, run, btc_root=root, group=group)}
    return {'version': 1, 'btc_root': str(root),
            'scorer_sha256': _sha(root / 'eval/reference_eval.py'),
            'btc_ground_truth_sha256': _sha(root / 'asr/ground_truth.json'), 'groups': groups}


def verify_asr_evidence(evidence, *, btc_root):
    try:
        sources = {group: {'dataset': value['dataset'], 'run': value['run']}
                   for group, value in evidence['groups'].items()}
        return (evidence['scorer_sha256'] == _sha(Path(btc_root) / 'eval/reference_eval.py')
                and evidence == collect_asr_evidence(sources, btc_root=evidence['btc_root']))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def add_asr_arguments(parser):
    for group in ('btc', 'team'):
        parser.add_argument(f'--asr-{group}-dataset', type=Path, help=f'Dataset audio ASR {group} đã chấm')
        parser.add_argument(f'--asr-{group}-run', type=Path, help=f'Thư mục score/hypotheses ASR {group} đã lưu')


def asr_sources_from_args(args):
    sources = {}
    for group in ('btc', 'team'):
        dataset, run = (getattr(args, f'asr_{group}_{key}') for key in ('dataset', 'run'))
        if bool(dataset) != bool(run):
            raise ValueError(f'--asr-{group}-dataset và --asr-{group}-run phải đi cùng nhau')
        if dataset:
            sources[group] = {'dataset': dataset, 'run': run}
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--btc-root', type=Path, required=True)
    parser.add_argument('--group', choices=('btc', 'team'), required=True)
    args = parser.parse_args()
    report = inspect_asr(args.dataset, args.run, btc_root=args.btc_root, group=args.group)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['asr_evidence_ready']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
