"""Detect after an ordinary pair; evaluate published knowledge in a separate command."""
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
from eval_harness.knowledge_manual import MODE, collect_review
from eval_harness.official_pipeline import atomic_json

WORKFLOW = 'paired_then_published_full'


def review_directory(base_run):
    return Path(str(Path(base_run).resolve())+'.knowledge')


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
    # K0 already exists: this only proposes, and the coordinator always returns before C.
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
    parser = argparse.ArgumentParser(description='LIVE: one Full evaluation using published knowledge from a prior pair')
    parser.add_argument('--base-run', required=True, type=Path, help='Completed ordinary No-memory/Full run directory')
    args = parser.parse_args()
    async def run():
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
    except Exception as exc:
        message = str(exc) if isinstance(exc, core.ExperimentError) else type(exc).__name__
        parser.exit(1, f'Knowledge evaluation stopped: {message}\n')


if __name__ == '__main__':
    main()
