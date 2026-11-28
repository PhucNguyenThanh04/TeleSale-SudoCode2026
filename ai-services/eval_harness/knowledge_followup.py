import argparse
import asyncio
import os
from argparse import Namespace
from pathlib import Path

from app.configs import Settings
from app.knowledge.config import configured_url
from app.knowledge.repos.postgres import KnowledgeRepo
from app.knowledge.schemas import digest
from eval_harness import knowledge_triplet as core
from eval_harness.knowledge_manual import MODE, collect_review, propose, unanswered_feedback
from eval_harness.official_pipeline import atomic_json
from eval_harness.turn_diagnostics import verify_report_turn_diagnostics

WORKFLOW = 'paired_then_published_full'


def review_directory(base_run):
    return Path(str(Path(base_run).resolve())+'.knowledge')


async def detect_after_full(trace, settings, *, actor='local-reviewer'):
    trace = Path(trace)
    report = core.read_json(trace.with_suffix('.report.json'))
    if report.get('status') != 'completed' or report.get('config') != 'full':
        raise core.ExperimentError('Knowledge detection requires a completed Full trace')
    diagnostics = verify_report_turn_diagnostics(trace)
    rows = core.trace_rows(trace)
    events = core.read_json(trace.with_suffix('.events.json'))
    if (not rows or any(row['config'] != 'full' or row['run_id'] != report['run_id'] for row in rows)
            or core.sha(trace) != diagnostics['trace_sha256']
            or core.sha(trace.with_suffix('.events.json')) != diagnostics['events']['sha256']):
        raise core.ExperimentError('Full trace or diagnostics changed')
    release_id = report['knowledge_release_id']
    path = trace.with_suffix('.knowledge-gaps.json')
    provenance = {'run_id': report['run_id'], 'release_id': release_id,
                  'trace_sha256': diagnostics['trace_sha256']}
    if path.is_file():
        existing = core.read_json(path)
        if any(existing.get(k) != v for k, v in provenance.items()):
            raise core.ExperimentError('Knowledge artifact does not match the saved Full run')
        if existing.get('status') == 'proposals_ready':
            return path, 'proposals_ready'
    candidates = unanswered_feedback(rows, events, release_id)
    result = {'status': 'exported', **provenance, 'candidates': candidates}
    if not candidates:
        result['status'] = 'no_eligible_gaps'
    atomic_json(path, result)
    urls = [configured_url(n) for n in ('KNOWLEDGE_DATABASE_URL', 'KNOWLEDGE_WORKER_DATABASE_URL')]
    if (not candidates or not settings.knowledge_enabled or not all(urls)
            or report.get('execution_health') != 'healthy' or settings.app_env == 'production'):
        return path, result['status']
    repo, worker = [KnowledgeRepo(url) for url in urls]
    try:
        for store in (repo, worker):
            if await store.database_identity() != report['database_identity']:
                raise core.ExperimentError('Knowledge and Full must use the same database server')
        async with repo.transaction() as tx:
            active = (await tx.get('active', 'current') or {}).get('release_id')
        if active != release_id:
            raise core.ExperimentError('Active release changed since Full')
        result['proposals'] = await propose(repo, worker, rows, candidates, actor=actor,
            run_id=report['run_id'], release_id=release_id, only_feedback=True)
        result['status'] = 'proposals_ready'
    except Exception as exc:
        result.update(status='proposal_failed', error_type=type(exc).__name__)
        atomic_json(path, result)
        raise
    finally:
        await repo.close()
        await worker.close()
    atomic_json(path, result)
    return path, result['status']


async def prepare_review(base_run, repo, worker, settings, *, actor='local-reviewer', timeout=60):
    base_run = Path(base_run).resolve()
    out = review_directory(base_run)
    if out.exists():
        raise core.ExperimentError('Knowledge proposals already exist for this pair')
    run = core.read_json(base_run/'run.json')
    if run.get('status') != 'validated' or run.get('execution_health') != 'healthy':
        raise core.ExperimentError('Knowledge detection requires a validated healthy pair')
    metadata = core.read_json(base_run/'full.manifest.json')
    params = metadata['model_params']
    expected = metadata['database_identity']['database']
    out.mkdir()
    state = {'kind': 'paired_knowledge_followup', 'workflow': WORKFLOW, 'approval_mode': MODE,
        'status': 'detecting', 'phase': 'k0_complete', 'plan_digest': digest(None),
        'system_boot_id': os.getenv('SYSTEM_BOOT_ID'), 'source_digest': metadata['source_digest'],
        'settings_digest': digest(settings.model_dump(mode='json')),
        'k0': str(base_run), 'k0_digest': core.tree_hash(base_run),
        'k0_release_id': metadata['knowledge_release']['release_id'],
        'arguments': {'scenarios': str(base_run/'scenarios'), 'btc_root': str(run.get('btc_root', base_run/'btc-release')),
            'seed': params['seed'],
            'expected_database': expected, 'actor': actor, 'worker_timeout': timeout}}
    atomic_json(out/'experiment.json', state)
    await core.run_experiment(Namespace(resume=out, expected_database=expected), repo, worker, settings)
    state = core.read_json(out/'experiment.json')
    if state['status'] == 'awaiting_review':
        state['status'] = 'proposals_ready'
        atomic_json(out/'experiment.json', state)
    print(f"[knowledge] {state['status']}: {out}/proposals.json", flush=True)
    return out


async def detect_after_pair(base_run):
    settings = Settings()
    if not settings.knowledge_enabled:
        print('[knowledge] Detection disabled by KNOWLEDGE_ENABLED; paired metrics are complete.', flush=True)
        return None
    urls = [configured_url(n) for n in ('KNOWLEDGE_DATABASE_URL', 'KNOWLEDGE_WORKER_DATABASE_URL')]
    if not all(urls):
        print('[knowledge] Detection not configured: reviewer/worker URLs required. Paired metrics are complete.', flush=True)
        return None
    repo, worker = [KnowledgeRepo(url) for url in urls]
    try:
        return await prepare_review(base_run, repo, worker, settings)
    finally:
        await repo.close(); await worker.close()


async def evaluate_published(base_run, repo, worker, settings):
    out = review_directory(base_run)
    if not (out/'experiment.json').is_file():
        raise core.ExperimentError('No proposals for this pair; run the normal paired eval with detection enabled first')
    state = core.read_json(out/'experiment.json')
    if state.get('workflow') != WORKFLOW:
        raise core.ExperimentError('Not an ordinary paired-evaluation knowledge result')
    if state.get('system_boot_id') and not os.getenv('SYSTEM_BOOT_ID'):
        os.environ['SYSTEM_BOOT_ID'] = state['system_boot_id']
    if state['status'] != 'complete':
        if not state.get('proposals', {}).get('proposed'):
            raise core.ExperimentError('No knowledge proposals to evaluate')
        reviewed = await collect_review(repo, state['proposals'], actor=state['arguments']['actor'],
            run_id=out.name, base=state['k0_release_id'])
        if reviewed is None:
            raise core.ExperimentError('Publish reviewed K1 first; no Full evaluation was started')
    return await core.run_experiment(Namespace(resume=out,
        expected_database=state['arguments'].get('expected_database')), repo, worker, settings)


def main():
    parser = argparse.ArgumentParser(description='Resume knowledge proposals or evaluate a published K1 release')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--base-run', type=Path, help='Completed pair, followed by one live K1 evaluation')
    source.add_argument('--full-trace', type=Path, help='Resume proposals from a completed Full trace without another model run')
    args = parser.parse_args()
    async def run():
        if args.full_trace is not None:
            path, status = await detect_after_full(args.full_trace, Settings())
            print(f'[knowledge] {status}: {path}', flush=True)
            return
        urls = [configured_url(n) for n in ('KNOWLEDGE_DATABASE_URL', 'KNOWLEDGE_WORKER_DATABASE_URL')]
        if not all(urls): raise core.ExperimentError('Reviewer and worker database URLs required')
        repo, worker = [KnowledgeRepo(url) for url in urls]
        try:
            out = await evaluate_published(args.base_run, repo, worker, Settings())
            print((out/'comparison.md').read_text())
        finally:
            await repo.close(); await worker.close()
    try:
        asyncio.run(run())
    except (Exception, SystemExit) as exc:
        message = str(exc) if isinstance(exc, core.ExperimentError) else type(exc).__name__
        parser.exit(1, f'Knowledge evaluation stopped: {message}\n')


if __name__ == '__main__':
    main()
