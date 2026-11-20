from app.knowledge.config import configured_url
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from app.knowledge.schemas import digest
from app.knowledge.events.ingest import record_event
from eval_harness.dashboard_data import load_run

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.trace_audit import audit_pair, audit_trace, _btc_digest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_verified_run(path):
    run = load_run(path)
    manifests = run['manifests']
    errors = audit_pair(manifests['full'], manifests['baseline_no_memory'])
    if errors:
        raise ValueError('Invalid pair: '+', '.join(errors))
    index = run['index']
    for key in ('scenarios', 'btc_root', 'traces'):
        if not index.get(key):
            raise ValueError('Run lacks audit provenance: '+key)
    for config in ('full', 'baseline_no_memory'):
        trace = path/index['traces'][config]
        if trace.resolve().parent != path.resolve():
            raise ValueError('Trace escapes run directory')
        audit = audit_trace(Path(index['scenarios']), trace, config, btc_root=Path(index['btc_root']))
        if audit['errors']:
            raise ValueError('Trace coverage/schema audit failed')
        report = trace.with_suffix('.report.json')
        if not report.is_file() or sha(report) != manifests[config]['runner_report_sha256']:
            raise ValueError('Runner report changed')
    if _btc_digest(Path(index['scenarios']), Path(index['btc_root'])) != manifests['full']['btc_data_digest']:
        raise ValueError('Scenario/BTC source changed after the run')
    scorer = Path(index['btc_root'])/'eval/reference_eval.py'
    inputs = path/'btc_score.inputs.json'
    if (not scorer.is_file() or sha(scorer) != manifests['full']['scorer_sha256'] or
            not inputs.is_file() or sha(inputs) != manifests['full']['score_inputs_sha256']):
        raise ValueError('Scorer provenance changed')
    run['rows'] = [json.loads(line) for line in (path/index['traces']['full']).read_text().splitlines() if line.strip()]
    return run


def feedback_events(run):
    failures = {}
    system = run['score']['system']
    for fail in (system.get('task_success_rate') or {}).get('failures', []):
        failures.setdefault((fail['scenario'], fail['call']), []).extend(fail.get('reasons', []))
    for metric in ('repeat_question_rate', 'hallucination_rate', 'guardrail_violations'):
        for item in (system.get(metric) or {}).get('examples', []):
            if item.get('scenario') and item.get('call'):
                failures.setdefault((item['scenario'], item['call']), []).append(metric)
    out = []
    for row in run['rows']:
        reasons = failures.get((row['scenario_id'], row['call']))
        if not reasons:
            continue
        key = digest([run['run_id'], row['scenario_id'], row['call'], row['turn']])
        out.append({'idempotency_key': key, 'event': {
            'source': 'evaluation_result', 'run_id': run['run_id'],
            'session_id': row.get('session_id'), 'message_id': key,
            'scenario_id': row['scenario_id'], 'call': row['call'], 'turn': row['turn'],
            'question': row['customer_text'], 'answer': row['agent_text'],
            'reason': '; '.join(sorted(set(reasons))), 'signal': 'evaluation_failure',
            'tool_calls': row.get('tool_calls', []),
            'release_id': (run.get('manifests', {}).get('full', {}).get('knowledge_release') or {}).get('release_id')}})
    return out


async def import_run(repo, run_dir):
    events = feedback_events(load_verified_run(run_dir))
    for item in events:
        await record_event(repo, item['event'], item['idempotency_key'])
    return {'imported_events': len(events)}


def main():
    ap = argparse.ArgumentParser(description='Import failures only from complete, provenance-checked BTC runs (offline).')
    ap.add_argument('--run', type=Path, required=True)
    args = ap.parse_args()
    from app.knowledge.repos.postgres import KnowledgeRepo
    dsn = configured_url('KNOWLEDGE_DATABASE_URL')
    if not dsn:
        ap.error('KNOWLEDGE_DATABASE_URL required')
    async def execute():
        repo = KnowledgeRepo(dsn)
        try:
            return await import_run(repo, args.run)
        finally:
            await repo.close()
    print(json.dumps(asyncio.run(execute())))


if __name__ == '__main__':
    main()
