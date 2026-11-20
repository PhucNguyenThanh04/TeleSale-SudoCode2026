from app.knowledge.config import configured_url
import argparse
import asyncio
import json
from pathlib import Path
from app.knowledge.schemas import digest, timestamp
from eval_harness.dashboard_data import metric_rows
from eval_harness.knowledge_feedback import load_verified_run

FIXED = ('source_digest', 'btc_data_digest', 'seed_digest', 'model_id', 'model_params',
         'guardrails', 'tool_mode', 'scorer_sha256')


def compare_runs(round0, round1):
    old, new = round0['manifests']['full'], round1['manifests']['full']
    for key in FIXED:
        if not old.get(key) or old.get(key) != new.get(key):
            raise ValueError('Rounds differ or lack '+key)
    if not old.get('knowledge_release') or not new.get('knowledge_release'):
        raise ValueError('Pinned knowledge release required')
    if old['knowledge_release'] == new['knowledge_release']:
        raise ValueError('Rounds must compare distinct knowledge releases')
    a = {r['key']: r for r in metric_rows(round0['score'])}
    b = {r['key']: r for r in metric_rows(round1['score'])}
    metrics = {}
    for key in a.keys() & b.keys():
        av, bv = a[key]['value'], b[key]['value']
        metrics[key] = {'round0': a[key], 'round1': b[key],
            'delta_percentage_points': round(bv-av, 3) if av is not None and bv is not None and a[key]['unit'] == '%' else None,
            'delta_count': bv-av if av is not None and bv is not None and a[key]['unit'] != '%' else None}
    def failures(run):
        return {f['scenario'] for f in run['score']['system'].get('task_success_rate', {}).get('failures', [])}
    before, after = failures(round0), failures(round1)
    result = {'complete': True, 'comparability_valid': True, 'release_id': new['knowledge_release']['release_id'],
        'round0': round0['run_id'], 'round1': round1['run_id'], 'fixed': {k: old[k] for k in FIXED},
        'knowledge_releases': [old['knowledge_release'], new['knowledge_release']], 'metrics': metrics,
        'improved_scenarios': sorted(before-after), 'regressed_scenarios': sorted(after-before),
        'note': 'Failure lists use BTC report coverage; review individual traces. Missing denominators remain unmeasured.'}
    result['id'] = digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Compare fixed-suite rounds without changing BTC's authoritative metrics.")
    parser.add_argument('--round0', type=Path, required=True)
    parser.add_argument('--round1', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--register', action='store_true', help='Store verified summary in knowledge DB')
    args = parser.parse_args()
    result = compare_runs(load_verified_run(args.round0), load_verified_run(args.round1))
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    lines = ['# Knowledge improvement comparison', '', '| Metric | Round 0 | Round 1 | Delta (percentage points) |', '|---|---:|---:|---:|']
    for key, row in result['metrics'].items():
        lines.append(f"| {key} | {row['round0']['value']} | {row['round1']['value']} | {row['delta_percentage_points']} |")
    lines += ['', 'Improved scenarios: '+', '.join(result['improved_scenarios']),
              'Regressed scenarios: '+', '.join(result['regressed_scenarios']), '', result['note']]
    (args.out/'report.md').write_text('\n'.join(lines)+'\n')
    if args.register:
        from app.knowledge.repos.postgres import KnowledgeRepo
        async def register():
            repo = KnowledgeRepo(configured_url('KNOWLEDGE_DATABASE_URL'))
            try:
                async with repo.transaction() as tx:
                    await tx.put('verification_runs', result['id'], result | {'created_at': timestamp()})
            finally:
                await repo.close()
        asyncio.run(register())
    print(args.out/'report.md')


if __name__ == '__main__':
    main()
