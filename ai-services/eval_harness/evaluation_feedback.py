import argparse
import asyncio
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path

from app.knowledge.events.evidence import snapshot
from eval.score_pair import _sha
from eval_harness.m1_acceptance import load_pair


def build_feedback(directory, *, btc_root):
    directory = Path(directory)
    run, score, manifests, traces, rows = load_pair(directory, btc_root=btc_root)
    from eval_harness.turn_diagnostics import verify_report_turn_diagnostics, trace_execution_health
    try:
        verify_report_turn_diagnostics(traces['full'])
        healthy = trace_execution_health(traces['full']) == 'healthy'
    except (OSError, ValueError, KeyError, TypeError):
        healthy = False
    dates = {}
    for path in sorted((directory / 'scenarios').glob('*.json')):
        scenario = json.loads(path.read_text())
        on = date(2026, 10, 15)
        for call, spec in scenario['calls'].items():
            on = date.fromisoformat(spec['call_date']) if 'call_date' in spec else on + timedelta(days=spec.get('days_later', 0))
            dates[(scenario['scenario_id'], call)] = on.isoformat()
    failures = []
    system = score['system']
    for failure in system.get('task_success_rate', {}).get('failures', []):
        failures.append(('task', failure, '; '.join(failure.get('reasons', []))))
    for failure in system.get('hallucination_rate', {}).get('examples', []):
        failures.append(('claim', failure, 'Claim mismatch: ' + str(failure.get('field'))))
    score_hash = _sha(directory / run['score'])
    output = []
    for kind, failure, reason in failures:
        matching = [r for r in rows['full'] if r['scenario_id'] == failure['scenario']
                    and r['call'] == failure['call']
                    and ('turn' not in failure or r['turn'] == failure['turn'])]
        if not matching:
            raise ValueError('evaluation_feedback_turn_missing')
        row = matching[-1]
        event = snapshot({'source': 'evaluation_result', 'rating': False,
            'score_sha256': score_hash,
            'run_id': run.get('run_id'), 'scenario_id': row['scenario_id'], 'call': row['call'],
            'turn': row['turn'], 'on': dates[(row['scenario_id'], row['call'])],
            'release_id': (manifests['full'].get('knowledge_release') or {}).get('release_id'),
            'signal': 'evaluation_failure' if healthy else 'execution_unverified',
            'question': row.get('customer_text', ''), 'answer': row['agent_text'],
            'reason': reason[:2000], 'tool_calls': row['tool_calls'],
            'context': f'{kind}; review source applicability before any change.'})
        key = sha256(json.dumps([score_hash, kind, row['scenario_id'], row['call'], row['turn'], reason],
                                ensure_ascii=False).encode()).hexdigest()
        output.append({'event': event, 'idempotency_key': key})
    return output


async def ingest(events):
    import httpx
    from app.configs import Settings
    settings = Settings()
    if not settings.ai_internal_token:
        raise ValueError('internal_token_required')
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{settings.port}',
            headers={'X-AI-Internal-Token': settings.ai_internal_token.get_secret_value()}, timeout=30) as client:
        for event in events:
            response = await client.post('/v1/knowledge/events', json=event)
            response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description='Export audited evaluation failures; optional explicit ingestion into the gap queue.')
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--btc-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--ingest', action='store_true', help='Write feedback to the configured local AI service; no auto approval')
    args = parser.parse_args()
    try:
        events = build_feedback(args.run, btc_root=args.btc_root)
        with args.out.open('x') as stream:
            for event in events:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
        if args.ingest:
            asyncio.run(ingest(events))
    except (OSError, ValueError, KeyError, TypeError):
        parser.error('Feedback inputs/output invalid; existing artifacts are not overwritten.')
    except Exception:
        parser.error('Feedback ingestion failed; exported events can be retried with their idempotency keys.')
    print(json.dumps({'events': len(events), 'ingested': args.ingest}))


if __name__ == '__main__':
    main()
