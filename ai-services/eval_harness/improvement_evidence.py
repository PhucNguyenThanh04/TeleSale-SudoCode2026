"""Compare fixed-test Knowledge Gap rounds from saved, hash-bound artifacts."""
import argparse
from datetime import datetime
import json
from pathlib import Path

from eval.score_pair import _sha, _scenario_sha
from eval_harness.m1_acceptance import inspect_run, load_pair


def compare_runs(before, after, *, btc_root):
    before, after = Path(before), Path(after)
    result = {'scope': 'knowledge_gap_rounds', 'complete': False, 'comparability_valid': False,
              'improvement_demonstrated': False, 'incompatible_controls': [],
              'delta_percentage_points': {}}
    try:
        pairs = [load_pair(path, btc_root=btc_root) for path in (before, after)]
    except (OSError, ValueError, KeyError, TypeError):
        result['incompatible_controls'] = ['artifact_integrity']
        return result
    old, new = [pair[2]['full'] for pair in pairs]
    controls = ('model_id', 'model_params', 'seed_id', 'seed_digest', 'source_digest',
                'guardrails', 'hardware', 'tool_mode', 'scorer_sha256')
    incompatible = [key for key in controls if key not in old or old[key] != new.get(key)]
    if _scenario_sha(before / 'scenarios') != _scenario_sha(after / 'scenarios'):
        incompatible.append('dataset')
    try:
        if datetime.fromisoformat(new['started_at_utc']) <= datetime.fromisoformat(old['started_at_utc']):
            incompatible.append('round_chronology')
    except (ValueError, KeyError, TypeError):
        incompatible.append('round_chronology')
    releases = [m.get('knowledge_release') for m in (old, new)]
    if not all(isinstance(r, dict) and r.get('release_id') and r.get('manifest_hash') for r in releases):
        incompatible.append('knowledge_release_missing')
    elif releases[0] == releases[1] or releases[0]['release_id'] == releases[1]['release_id']:
        incompatible.append('knowledge_release_unchanged')
    result['incompatible_controls'] = incompatible
    result['comparability_valid'] = not incompatible
    result['evidence_hashes'] = {label: {'run': _sha(path / 'run.json'),
        'full_manifest': _sha(path / 'full.manifest.json'),
        'score': _sha(path / 'btc_score.json'), 'dataset': _scenario_sha(path / 'scenarios')}
        for label, path in [('before', before), ('after', after)]}
    if incompatible:
        return result
    reports = [inspect_run(path, btc_root=btc_root) for path in (before, after)]
    required = {'artifact_integrity', 'execution_health', 'extraction_review',
                'm1_text_lifecycle', 'guardrails_enabled', 'safety'}
    verified = all(all(c['status'] == 'pass' for c in report['checks'] if c['name'] in required)
                   and required <= {c['name'] for c in report['checks']} for report in reports)
    metrics = ('repeat_question_rate', 'context_carryover_rate', 'task_success_rate', 'hallucination_rate')
    deltas = {}
    for metric in metrics:
        values = [pair[1]['system'].get(metric, {}).get('value') for pair in pairs]
        deltas[metric] = round(values[1] - values[0], 3) if all(type(v) in (int, float) for v in values) else None
    result['delta_percentage_points'] = deltas
    # Also protect the separately required price/promotion hallucination metric.
    hr = [pair[1]['system'].get('hallucination_rate', {}).get('price_promo_only', {}).get('value')
          for pair in pairs]
    deltas['price_promo_hallucination_rate'] = (round(hr[1] - hr[0], 3)
        if all(type(v) in (int, float) for v in hr) else None)
    lower_is_better = {'repeat_question_rate', 'hallucination_rate', 'price_promo_hallucination_rate'}
    normalized = {key: (-value if key in lower_is_better else value)
                  for key, value in deltas.items() if value is not None}
    regressions = [key for key, value in normalized.items() if value < 0]
    result.update(complete=verified and len(normalized) == len(deltas), regressions=regressions,
                  release_id=releases[1]['release_id'],
                  review_required='Reviewer must inspect changed-case traces and approved release provenance.')
    result['improvement_demonstrated'] = (result['complete'] and not regressions
                                          and any(value > 0 for value in normalized.values()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--btc-root', type=Path, required=True)
    args = parser.parse_args()
    report = compare_runs(args.before, args.after, btc_root=args.btc_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['improvement_demonstrated']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
