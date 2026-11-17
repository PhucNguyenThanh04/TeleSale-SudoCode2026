"""LIVE three-arm experiment with manual, automatic or pre-reviewed approval."""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.configs import Settings
from app.bootstrap.database import require_ready
from app.knowledge.config import configured_url
from app.knowledge.repos.postgres import KnowledgeRepo
from app.knowledge.schemas import digest, KnowledgeError
from app.knowledge.services.lifecycle import command
from app.knowledge.services.permissions import require_permission
from app.mcp_servers.mcp_shared.config import database_url
from eval_harness.knowledge_auto_review import (answer_passes, auto_review, check_review_sources,
                                               locator, retrieved_ids, validate_plan)
from eval_harness.knowledge_automatic import MODE, review_proposals, source_catalog_digest
from eval_harness.knowledge_manual import MODE as MANUAL_MODE, propose, collect_review
from eval_harness.evaluation_feedback import build_feedback
from eval_harness.official_pipeline import atomic_json
from eval_harness.extraction_report import write_extraction_sidecar, summarize_extraction
from eval_harness.run_official import PROJECT, _run_one, run_pair, source_snapshot_digest
from eval_harness.scenario_contract import load_scenarios
from eval_harness.seed_fingerprint import fingerprint_btc_source
from eval_harness.turn_diagnostics import verify_report_turn_diagnostics, trace_execution_health
from eval.score_pair import score_pair, _scenario_sha
from eval.trace_audit import audit_trace, build_manifest


class ExperimentError(ValueError):
    """Static operator-facing diagnostics; never raw provider/DB exceptions."""


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hash(root):
    return digest([(str(p.relative_to(root)), sha(p)) for p in sorted(Path(root).rglob('*')) if p.is_file()])


def trace_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


async def export_sources(repo, actor, output):
    if output.exists(): raise ExperimentError('Source export already exists; choose a new path')
    async with repo.transaction() as tx:
        await require_permission(tx, actor)
        sources = [s for s in await tx.sources() if s.get('access_level') == 'public']
    atomic_json(output, {'kind': 'public_source_catalog_not_an_approval', 'sources': sources})


def check_plan_scenarios(plan, scenarios, btc_root):
    inputs = load_scenarios(scenarios, btc_root=btc_root)
    for case in plan['cases']:
        scenario = inputs.get(case['scenario_id'], {})
        spec = scenario.get('calls', {}).get(case['call'], {})
        turns = spec.get('customer_turns_asr') or spec.get('customer_turns', [])
        if case['turn'] > len(turns) or turns[case['turn'] - 1] != case['question']:
            raise ExperimentError('Review plan locator/question does not match the dataset')


def check_release_extension(previous, ready, approved):
    old, new = previous['manifest'], ready['manifest']
    if old.get('index_kind') != 'hybrid' or new.get('index_kind') != 'hybrid':
        raise ExperimentError('Experiment requires immutable hybrid policy releases')
    for field in ('config_hash', 'model_fingerprint', 'metadata_hash'):
        if old.get(field) != new.get(field):
            raise ExperimentError('Policy runtime configuration changed between releases')
    for field in ('source_hashes', 'content_hashes'):
        if not old.get(field) or any(new.get(field, {}).get(k) != v for k, v in old[field].items()):
            raise ExperimentError('K1 changed or removed existing policy content')
    expected = {'KG-' + a['revision_id'] for a in approved if a['kind'] == 'faq'}
    if set(new['source_hashes']) - set(old['source_hashes']) != expected:
        raise ExperimentError('K1 contains unexpected or missing policy additions')
    expected_ids = {i['id'] for i in old['items']} | {a['revision_id'] for a in approved}
    if {i['id'] for i in new['items']} != expected_ids:
        raise ExperimentError('K1 did not retain exactly the intended revisions')
    new_items = {i['id']: i for i in new['items']}
    if any(new_items[i['id']] != i for i in old['items']):
        raise ExperimentError('K1 changed an existing revision snapshot')


def comparison_report(plan, baseline, full, after, approved, release_id, *, manual=False):
    if plan is None:
        indexed = {name: {locator(r): r for r in rows} for name, rows in
                   [('no_memory_k0', baseline), ('full_k0', full), ('full_k1', after)]}
        cases = []
        for item in approved:
            key = tuple(item['locator'])
            expected = ({'KG-'+item['revision_id']} if item['kind'] == 'faq'
                        else {s['chunk_id'] for s in item['sources']})
            turns = {name: rows.get(key, {}) for name, rows in indexed.items()}
            hit = any(t.get('name') == 'policy.search'
                and t.get('result', {}).get('context', {}).get('knowledge_release_id') == release_id
                and expected & {e.get('chunk_id') for e in t.get('result', {}).get('evidence', [])}
                for t in turns['full_k1'].get('tool_calls', []))
            cases.append(dict(item, answers={name: r.get('agent_text') for name, r in turns.items()},
                target_evidence_in_k1=hit, retrieved_ids={name: sorted(retrieved_ids(r)) for name, r in turns.items()}))
        return {'assertion_kind': 'not_measured_no_independent_answer_labels', 'cases': cases,
            'target_evidence_in_k1': {'retrieved': sum(c['target_evidence_in_k1'] for c in cases),
                                      'total': len(cases)},
            'limitations': ['Target-source retrieval in K1 does not prove answer correctness or causality.',
                           ('Review decisions are recorded; independent answer correctness is not measured.' if manual
                            else 'Automatic source checks are not human review.')]}
    arms = {name: {locator(r): r for r in rows} for name, rows in
            [('no_memory_k0', baseline), ('full_k0', full), ('full_k1', after)]}
    decisions = {a['case_id']: a for a in approved}
    cases = []
    for c in plan['cases']:
        item = {'case_id': c['id'], 'locator': list(locator(c)), 'answers': {}, 'passed': {}}
        for name, rows in arms.items():
            r = rows.get(locator(c), {})
            item['answers'][name] = r.get('agent_text')
            item['passed'][name] = bool(r and answer_passes(r, c))
        reviewed = decisions.get(c['id'])
        r = arms['full_k1'].get(locator(c), {})
        expected = ({'KG-' + reviewed['revision_id']} if reviewed and reviewed['kind'] == 'faq'
                    else {s['chunk_id'] for s in reviewed['sources']} if reviewed else set())
        used = any(t.get('name') == 'policy.search'
            and t.get('result', {}).get('context', {}).get('knowledge_release_id') == release_id
            and expected & {e.get('chunk_id') for e in t.get('result', {}).get('evidence', [])}
            for t in r.get('tool_calls', []))
        item.update(review=reviewed, retrieved_ids=sorted(retrieved_ids(r)), new_revision_retrieved=used,
                    grounded_success=bool(used and item['passed']['full_k1']))
        cases.append(item)
    def rate(n, total):
        return {'passed': n, 'total': total, 'percent': round(100 * n / total, 2) if total else None}
    return {'assertion_kind': 'pre_reviewed_literal_answer_checks_not_llm_judge', 'cases': cases,
        'gap_answer_accuracy': {name: rate(sum(c['passed'][name] for c in cases), len(cases)) for name in arms},
        'new_revision_used': rate(sum(c['grounded_success'] for c in cases), len(approved)),
        'fixed_answers': sum(not c['passed']['full_k0'] and c['passed']['full_k1'] for c in cases),
        'regressed_answers': sum(c['passed']['full_k0'] and not c['passed']['full_k1'] for c in cases)}


def render_report(report):
    automatic = report['approval_mode'] == MODE
    manual = report['approval_mode'] == MANUAL_MODE
    lines = ['# Knowledge experiment — ' + ('manual review' if manual else 'automatic approval' if automatic else 'simulated approval'), '',
        'K0 is an audited official pair. K1 is a full-only, cross-release experiment.',
        ('Approval decisions, configured reviewer actor, reasons and reviewed test hashes were collected from the published K1.' if manual else
         'Approval uses automatic source/lexical/regression checks; no human review is claimed.' if automatic else
         'Approval follows a pre-reviewed plan; this is not a human review performed during the run.'), '',
        '| Metric | No memory K0 | Full K0 | Full K1 |', '|---|---:|---:|---:|']
    arms = report['btc_metrics']
    for label, field in [('RQR ↓', 'repeat_question_rate'), ('CCR ↑', 'context_carryover_rate'),
                         ('TSR ↑', 'task_success_rate'), ('HR ↓', 'hallucination_rate')]:
        values = [str(arms[a].get(field, {}).get('value', 'N/A')) for a in arms]
        lines.append('| ' + label + ' (%) | ' + ' | '.join(values) + ' |')
    values = [str(arms[a].get('hallucination_rate', {}).get('price_promo_only', {}).get('value', 'N/A')) for a in arms]
    lines.append('| HR price/promo (%) | ' + ' | '.join(values) + ' |')
    if automatic or manual:
        lines.extend(['', f"Target evidence retrieved in K1: {report['gap_evidence']['target_evidence_in_k1']}.",
            'Independent gap-answer accuracy: not measured. Generated tests are not answer ground truth.',
            'Retrieval alone does not prove a correct answer or an effect caused by the new revision.'])
    else:
        rates = report['gap_evidence']['gap_answer_accuracy']
        lines.extend(['| Reviewed answer checks (%) | ' + ' | '.join(str(rates[a]['percent']) for a in arms) + ' |', '',
        'Answer checks use the same assertions in all three arms. Retrieval alone is not answer correctness.',
        f"Answers fixed: {report['gap_evidence']['fixed_answers']}; regressed: {report['gap_evidence']['regressed_answers']}.",
        f"New revision retrieved AND answer checks passed: {report['gap_evidence']['new_revision_used']}."])
    lines.extend(['',
        f"Approved revisions: {len(report.get('review', {}).get('approved', []))}; skipped K0 turns: {len(report.get('review', {}).get('skipped', []))}.",
        f"Extraction status: {report.get('extraction_status', {})}.", '',
        'Full per-case answers, source/revision lineage and skipped reasons are in comparison.json.',
        'No new official same-release pair is claimed for the cross-release K1 comparison.', ''])
    return '\n'.join(lines)


async def run_experiment(args, repo, worker_repo, settings):
    if settings.app_env == 'production' or not settings.agent_guardrails_enabled or not settings.knowledge_enabled:
        raise ExperimentError('Non-production, guardrails and knowledge must be enabled')
    if not args.expected_database and not args.resume:
        raise ExperimentError('Explicit expected database required')
    state = read_json(args.resume/'experiment.json') if args.resume else None
    if state:
        for key, value in state['arguments'].items():
            setattr(args, key, Path(value) if key in {'scenarios', 'btc_root'} else value)
        out = args.resume
        plan = None if state['approval_mode'] in {MODE, MANUAL_MODE} else validate_plan(read_json(out/'review-plan.json'))
    else:
        plan = validate_plan(read_json(args.approval_plan)) if args.approval_plan else None
        if plan: check_plan_scenarios(plan, args.scenarios, args.btc_root)
        out = args.out_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
        out.mkdir(parents=True, exist_ok=False)
        if plan: atomic_json(out/'review-plan.json', plan)
        state = {'kind': 'three_arm_knowledge_experiment', 'approval_mode': ('simulated_pre_reviewed_plan' if plan else
                MANUAL_MODE if getattr(args, 'manual_review', False) else MODE),
            'status': 'running', 'phase': 'initial', 'plan_digest': digest(plan),
            'system_boot_id': os.getenv('SYSTEM_BOOT_ID'),
            'source_digest': source_snapshot_digest(PROJECT), 'settings_digest': digest(settings.model_dump(mode='json')),
            'arguments': {k: str(getattr(args, k)) if k in {'scenarios', 'btc_root'} else getattr(args, k)
                          for k in ('scenarios', 'btc_root', 'agent', 'seed', 'delivery_mode', 'expected_database', 'actor', 'worker_timeout')}}
        atomic_json(out/'experiment.json', state)
    def save(**updates):
        state.update(updates); atomic_json(out/'experiment.json', state)
    lock = (out/'.resume.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ExperimentError('This experiment is already running; wait for the current process') from None
    try:
        if state.get('system_boot_id') and state['system_boot_id'] != os.getenv('SYSTEM_BOOT_ID'):
            raise ExperimentError('Resume must use the original managed system boot; do not reset knowledge between K0 and K1')
        if state.get('system_boot_id'):
            await require_ready(database_url(settings), state['system_boot_id'])
        if (state['plan_digest'] != digest(plan) or state['source_digest'] != source_snapshot_digest(PROJECT)
                or state['settings_digest'] != digest(settings.model_dump(mode='json'))):
            raise ExperimentError('Plan/source/settings changed; refusing incompatible resume')
        if plan:
            await check_review_sources(repo, plan, args.actor)
        else:
            catalog = await source_catalog_digest(repo, args.actor)
            if state.get('catalog_digest', catalog) != catalog:
                raise ExperimentError('Public source catalog changed; refusing incompatible automatic review/resume')
            if 'catalog_digest' not in state: save(catalog_digest=catalog)
        identities = [await connection.database_identity() for connection in (repo, worker_repo)]
        for identity in identities:
            if identity['database'] != args.expected_database:
                raise ExperimentError('Knowledge database identity differs from expected database')
        if 'k0' not in state:
            print('[knowledge] A: baseline K0; B: full K0', flush=True)
            k0 = await run_pair(scenarios=args.scenarios, btc_root=args.btc_root, agent=args.agent, seed=args.seed,
                out_root=out/'k0', expected_database=args.expected_database, delivery_mode=args.delivery_mode, baseline_first=True)
            save(k0=str(k0.resolve()), k0_digest=tree_hash(k0), phase='k0_finished')
        k0 = Path(state['k0'])
        if state['k0_digest'] != tree_hash(k0):
            raise ExperimentError('Frozen K0 artifacts changed')
        run = read_json(k0/'run.json')
        if run['status'] != 'validated' or run.get('execution_health') != 'healthy':
            raise ExperimentError(f"K0 must be validated and healthy: phase={run.get('phase')} "
                f"code={run.get('error_code')} service={run.get('service')}; inspect {k0}/run.json")
        if state['phase'] == 'k0_finished': save(phase='k0_complete')
        metadata = read_json(k0/'full.manifest.json')
        if metadata['source_digest'] != state['source_digest']:
            raise ExperimentError('K0 source differs from experiment source')
        if any(identity != metadata['database_identity'] for identity in identities):
            raise ExperimentError('Knowledge and runtime must use the same database server')
        if await fingerprint_btc_source(database_url(settings)) != metadata['seed_digest']:
            raise ExperimentError('BTC seed changed between arms')
        if state.get('review_digest') and state['review_digest'] != sha(out/'review.json'):
            raise ExperimentError('Review artifact changed')
        if state['phase'] == 'compared':
            if (state['comparison_digest'] != sha(out/'comparison.json')
                    or state['k1_digest'] != tree_hash(out/'k1')):
                raise ExperimentError('Comparison artifact changed')
            return out
        full = trace_rows(k0/run['traces']['full']); baseline = trace_rows(k0/run['traces']['baseline_no_memory'])
        base = metadata['knowledge_release']['release_id']
        manual = state['approval_mode'] == MANUAL_MODE
        if manual:
            new_proposals = 'proposals' not in state
            if state.get('proposals_digest') and state['proposals_digest'] != sha(out/'proposals.json'):
                raise ExperimentError('Proposal artifact changed')
            if 'proposals' not in state:
                async with repo.transaction() as tx:
                    active = (await tx.get('active', 'current') or {}).get('release_id')
                if active != base: raise ExperimentError('Active release changed since K0')
                feedback = build_feedback(k0, btc_root=k0/'btc-release')
                proposals = await propose(repo, worker_repo, full, feedback, actor=args.actor, run_id=out.name,
                    timeout=args.worker_timeout, score_sha256=sha(k0/'btc_score.json'), release_id=base)
                atomic_json(out/'proposals.json', proposals)
                save(proposals=proposals, proposals_digest=sha(out/'proposals.json'), phase='awaiting_review')
            if not state['proposals']['proposed']:
                save(status='no_eligible_gaps', phase='proposed')
                return out
            if 'review' not in state:
                collected = None if new_proposals else await collect_review(
                    repo, state['proposals'], actor=args.actor, run_id=out.name, base=base)
                if collected is None:
                    save(status='awaiting_review', phase='awaiting_review',
                        review_url='http://127.0.0.1:8000/knowledge?run_id='+out.name)
                    print('[knowledge] Review/edit/reject proposals and publish K1: '+state['review_url'], flush=True)
                    separate = state.get('workflow') == 'paired_then_published_full'
                    resume = ([str(PROJECT/'ai-services/.venv/bin/python'), str(PROJECT/'run_knowledge_eval.py'),
                               '--base-run', str(k0.resolve())] if separate else
                              [str(PROJECT/'ai-services/.venv/bin/python'), '-m',
                               'eval_harness.knowledge_triplet', '--resume', str(out.resolve())])
                    prefix = 'AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true PYTHONPATH='+shlex.quote(str(PROJECT/'ai-services')+os.pathsep+str(PROJECT))
                    if state.get('system_boot_id'):
                        prefix += ' SYSTEM_BOOT_ID='+shlex.quote(state['system_boot_id'])
                    pin = getattr(settings, 'knowledge_release_id', None)
                    if pin is not None:
                        prefix += ' KNOWLEDGE_RELEASE_ID='+shlex.quote(pin)
                    print(('[knowledge] Run the separate file after publication: ' if separate else
                           '[knowledge] Resume in another terminal: ')+prefix+' '+shlex.join(resume), flush=True)
                    return out
                review, ready = collected
                async with repo.transaction() as tx:
                    previous = await tx.get('releases', base)
                check_release_extension(previous, ready, review['approved'])
                atomic_json(out/'review.json', review)
                save(review=review, review_digest=sha(out/'review.json'), status='running', phase='published',
                    k1_release={'release_id': ready['id'], 'manifest_hash': ready['manifest_hash']})
        if 'review' not in state:
            async with repo.transaction() as tx:
                active = (await tx.get('active', 'current') or {}).get('release_id')
            if active != base: raise ExperimentError('Active release changed since K0')
            print('[knowledge] ' + ('simulated pre-reviewed plan' if plan else 'automatic source-checked worker proposals'), flush=True)
            if plan:
                review = await auto_review(repo, worker_repo, plan, full, actor=args.actor,
                    run_id=out.name, timeout=args.worker_timeout, score_sha256=sha(k0/'btc_score.json'), release_id=base)
            else:
                if await source_catalog_digest(repo, args.actor) != state['catalog_digest']:
                    raise ExperimentError('Public source catalog changed during K0')
                async with repo.transaction() as tx:
                    previous = await tx.get('releases', base)
                review = await review_proposals(repo, worker_repo, full, actor=args.actor,
                    run_id=out.name, timeout=args.worker_timeout, score_sha256=sha(k0/'btc_score.json'), release_id=base,
                    max_approvals=max(0, 100-len(previous['manifest']['items'])))
            atomic_json(out/'review.json', review)
            save(review=review, review_digest=sha(out/'review.json'), phase='reviewed')
        review = state['review']
        print(f"[knowledge] approved={len(review['approved'])}; skipped={len(review['skipped'])}; review: {out}/review.json", flush=True)
        if not review['approved']:
            save(status='no_eligible_gaps', phase='reviewed')
            return out
        if 'k1_release' not in state:
            async with repo.transaction() as tx:
                previous = await tx.get('releases', base)
            ids = sorted({item['id'] for item in previous['manifest']['items']} |
                         {item['revision_id'] for item in review['approved']})
            ready = await command(repo, args.actor, 'prepare_release', {'revision_ids': ids, 'expected_active_id': base})
            check_release_extension(previous, ready, review['approved'])
            save(k1_release={'release_id': ready['id'], 'manifest_hash': ready['manifest_hash']}, phase='prepared')
        release = state['k1_release']
        if state['phase'] == 'prepared':
            await command(repo, args.actor, 'activate_release', {'id': release['release_id'], 'expected_active_id': base})
            save(phase='published')
        async with repo.transaction() as tx:
            active = (await tx.get('active', 'current') or {}).get('release_id')
        if active != release['release_id']: raise ExperimentError('K1 is no longer active')
        k1 = out/'k1'; k1.mkdir(exist_ok=True)
        if 'k1_started_at' not in state:
            save(k1_started_at=datetime.now(timezone.utc).isoformat())
        trace = k1/'full.diagnostics_full.jsonl'
        if not trace.exists():
            print('[knowledge] C: full memory with published K1 (no fourth baseline)', flush=True)
            trace = _run_one('full', k0/'scenarios', args.agent, args.seed, out.name+'-k1', k1,
                btc_root=k0/'btc-release', expected_database=args.expected_database, release=release, delivery_mode=args.delivery_mode)
        runner = read_json(trace.with_suffix('.report.json'))
        if (runner.get('status') != 'completed' or runner.get('safety_issues')
                or runner.get('database_identity') != metadata['database_identity']
                or runner.get('knowledge_release_id') != release['release_id']):
            raise ExperimentError('K1 execution invalid; refusing partial or mismatched evidence')
        if audit_trace(k0/'scenarios', trace, 'full', btc_root=k0/'btc-release')['errors']:
            raise ExperimentError('K1 trace audit failed')
        verify_report_turn_diagnostics(trace)
        if trace_execution_health(trace) != 'healthy': raise ExperimentError('K1 execution unhealthy')
        if state['source_digest'] != source_snapshot_digest(PROJECT) or state['k0_digest'] != tree_hash(k0):
            raise ExperimentError('Source or K0 artifacts changed during K1')
        if await fingerprint_btc_source(database_url(settings)) != metadata['seed_digest']:
            raise ExperimentError('BTC seed changed during K1')
        score_path = k1/'btc_cross_release_score.json'
        if not score_path.exists():
            score_pair(k0/'scenarios', trace, k0/run['traces']['baseline_no_memory'], score_path, btc_root=k0/'btc-release')
        else:
            pins = read_json(score_path.with_suffix('.inputs.json'))
            if (pins.get('full_trace_sha256') != sha(trace) or pins.get('score_sha256') != sha(score_path)
                    or pins.get('baseline_trace_sha256') != sha(k0/run['traces']['baseline_no_memory'])
                    or pins.get('scenario_sha256') != _scenario_sha(k0/'scenarios')
                    or pins.get('scorer_sha256') != sha(k0/'btc-release/eval/reference_eval.py')):
                raise ExperimentError('Cross-release score provenance changed')
        fields = ('source_digest', 'seed_id', 'seed_digest', 'model_id', 'model_params', 'tool_mode',
                  'guardrails', 'database_identity', 'hardware')
        manifest = build_manifest(trace_path=trace, scenarios_dir=k0/'scenarios', config='full',
            scorer_report_path=score_path, btc_root=k0/'btc-release', expected_database=args.expected_database,
            app_env=settings.app_env, knowledge_release=release, started_at_utc=state['k1_started_at'],
            **{key: metadata[key] for key in fields if key in metadata})
        atomic_json(k1/'full.manifest.json', manifest)
        before_score = read_json(k0/'btc_score.json'); after_score = read_json(score_path)
        sidecar = k1/'full.extraction.jsonl'
        if not sidecar.exists(): write_extraction_sidecar(trace, sidecar)
        extraction = summarize_extraction({'full': trace, 'baseline_no_memory': k0/run['traces']['baseline_no_memory']},
            {'full': sidecar, 'baseline_no_memory': k0/'baseline.extraction.jsonl'}, after_score)
        atomic_json(k1/'extraction_report.json', extraction)
        comparison = {'kind': 'cross_release_experiment_not_official_same_release_pair',
            'approval_mode': state['approval_mode'], 'k0_release': metadata['knowledge_release'], 'k1_release': release,
            'btc_metrics': {'no_memory_k0': before_score['baseline'], 'full_k0': before_score['system'], 'full_k1': after_score['system']},
            'gap_evidence': comparison_report(plan, baseline, full, trace_rows(trace), review['approved'], release['release_id'], manual=manual),
            'review': review, 'k0_run': str(k0), 'k1_trace_sha256': sha(trace),
            'k1_score_sha256': sha(score_path), 'extraction_status': {
                'k0': run.get('extraction_status', 'needs_review'), 'k1': extraction['extraction_status']}}
        atomic_json(out/'comparison.json', comparison)
        (out/'comparison.md').write_text(render_report(comparison), encoding='utf-8')
        save(status='complete', phase='compared', comparison_digest=sha(out/'comparison.json'), k1_digest=tree_hash(k1))
        return out
    except Exception as exc:
        save(status='failed', error_type=type(exc).__name__)
        print(f'[knowledge] stopped ({type(exc).__name__}); checkpoint: {out}/experiment.json', flush=True)
        raise
    finally:
        lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scenarios', type=Path, default=PROJECT/'ai-services/eval_harness/scenarios')
    p.add_argument('--btc-root', type=Path)
    review_mode = p.add_mutually_exclusive_group()
    review_mode.add_argument('--approval-plan', type=Path, help='Optional pre-reviewed plan instead of automatic approval')
    review_mode.add_argument('--auto-review', action='store_true', help='Automatic source-checked proposal review (default without a plan)')
    p.add_argument('--expected-database')
    p.add_argument('--actor', default='local-reviewer')
    p.add_argument('--agent', choices=['deep', 'react'], default='deep')
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--delivery-mode', choices=['text'], default='text')
    p.add_argument('--worker-timeout', type=float, default=60)
    p.add_argument('--out-root', type=Path, default=PROJECT/'ai-services/eval_harness/results/knowledge-triplet')
    p.add_argument('--resume', type=Path)
    p.add_argument('--export-sources', type=Path, help='Read-only public source/hash export; no model or worker calls')
    args = p.parse_args()
    if args.resume and args.export_sources:
        p.error('--resume and --export-sources are mutually exclusive')
    if not args.resume and not args.export_sources and not all((args.btc_root, args.expected_database)):
        p.error('--btc-root and --expected-database are required for a new experiment')
    async def run():
        if args.export_sources:
            url = configured_url('KNOWLEDGE_DATABASE_URL')
            if not url: raise ExperimentError('KNOWLEDGE_DATABASE_URL required')
            repo = KnowledgeRepo(url)
            try:
                await export_sources(repo, args.actor, args.export_sources)
                print(f'public sources exported: {args.export_sources}')
            finally:
                await repo.close()
            return
        urls = [configured_url(name) for name in ('KNOWLEDGE_DATABASE_URL', 'KNOWLEDGE_WORKER_DATABASE_URL')]
        if not all(urls): raise ExperimentError('Knowledge reviewer and restricted worker database URLs required')
        repo, worker = [KnowledgeRepo(url) for url in urls]
        try:
            out = await run_experiment(args, repo, worker, Settings())
            print(f"{read_json(out/'experiment.json')['status']}: {out}/experiment.json")
            if (out/'comparison.md').exists(): print((out/'comparison.md').read_text())
            if read_json(out/'experiment.json')['status'] == 'awaiting_review':
                raise SystemExit(3)
            if read_json(out/'experiment.json')['status'] != 'complete':
                print('No eligible gaps: C was not run; inspect proposals.json/review.json. No improvement is claimed.')
                raise SystemExit(2)
        finally:
            await repo.close(); await worker.close()
    try:
        asyncio.run(run())
    except Exception as exc:
        reason = str(exc) if isinstance(exc, (ExperimentError, KnowledgeError)) else type(exc).__name__
        raise SystemExit(f'knowledge experiment failed: {reason}; inspect checkpoint and service logs') from None


if __name__ == '__main__':
    main()
