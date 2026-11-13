"""Explicitly simulated review of a hash-pinned, human-authored experiment plan."""
import asyncio
import re
import time

from app.knowledge.events.evidence import safe_text
from app.knowledge.events.ingest import record_event
from app.knowledge.events.worker import process_one
from app.knowledge.schemas import KnowledgeError, digest
from app.knowledge.services.lifecycle import command
from app.knowledge.services.permissions import require_permission
from app.knowledge.services.regression import check_offline_retrieval
from app.knowledge.services.source_validation import validate_sources, applicable


def locator(row):
    return row['scenario_id'], row['call'], row['turn']


def answer_passes(row, case):
    text = ' '.join(row.get('agent_text', '').casefold().split())
    return (all(' '.join(s.casefold().split()) in text for s in case['must_say'])
            and not any(' '.join(s.casefold().split()) in text for s in case.get('must_not_say', [])))


def validate_plan(plan):
    if (plan.get('schema_version') != 1 or not plan.get('reviewed_by', '').strip()
            or not plan.get('review_note', '').strip() or not 1 <= len(plan.get('cases', [])) <= 100):
        raise KnowledgeError('Pre-reviewed plan, reviewer, note and 1..100 cases required')
    ids, keys = set(), set()
    for c in plan['cases']:
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', c.get('id', '')) or c['id'] in ids or locator(c) in keys or type(c['turn']) is not int or c['turn'] < 1
                or c.get('kind') not in {'faq', 'aliases'} or c.get('category') not in {'content', 'retrieval'}
                or not c.get('question', '').strip() or not c.get('variations') or not c.get('must_say')
                or not c.get('sources') or len(c['sources']) > 10):
            raise KnowledgeError('Invalid or duplicate review case')
        for strings in (c['variations'], c['must_say'], c.get('must_not_say', []), c.get('aliases', [])):
            if not isinstance(strings, list) or any(not isinstance(s, str) or not s.strip() for s in strings):
                raise KnowledgeError('Nonempty string assertions required')
        if c['kind'] == 'faq' and not c.get('answer', '').strip():
            raise KnowledgeError('Reviewed FAQ answer required')
        if c['kind'] == 'faq' and re.search(r'\d[\d., ]*\s*(?:đ|vnd|triệu|nghìn|k\b)', c['answer'], re.I):
            raise KnowledgeError('FAQ plan cannot contain dynamic price commitments')
        if c['kind'] == 'aliases' and not 1 <= len(c.get('aliases', [])) <= 20:
            raise KnowledgeError('Reviewed aliases required')
        if any(not r.get('chunk_id') or not re.fullmatch('[a-f0-9]{64}', r.get('source_hash', '')) for r in c['sources']):
            raise KnowledgeError('Pinned source hashes required')
        if len({r['chunk_id'] for r in c['sources']}) != len(c['sources']):
            raise KnowledgeError('Duplicate source IDs')
        ids.add(c['id']); keys.add(locator(c))
    return plan


async def check_review_sources(repo, plan, actor):
    validate_plan(plan)
    async with repo.transaction() as tx:
        await require_permission(tx, actor)
        for case in plan['cases']:
            await validate_sources(tx, case['sources'])


def retrieved_ids(row):
    return {e.get('chunk_id') for t in row.get('tool_calls', []) if t.get('name') == 'policy.search'
            for e in t.get('result', {}).get('evidence', []) if isinstance(e.get('chunk_id'), str)}


async def auto_review(repo, worker_repo, plan, rows, *, actor, run_id, timeout=60, score_sha256=None, release_id=None):
    await check_review_sources(repo, plan, actor)
    indexed = {locator(r): r for r in rows}
    result = {'approval_mode': 'simulated_pre_reviewed_plan', 'plan_digest': digest(plan),
              'reviewed_by': plan['reviewed_by'], 'actor_id': actor, 'approved': [], 'skipped': []}
    for case in plan['cases']:
        row = indexed.get(locator(case))
        reason = None
        if row is None: reason = 'missing_turn'
        elif row.get('config') != 'full': reason = 'not_full_k0'
        elif safe_text(row.get('user_text', row.get('customer_text', ''))) != safe_text(case['question']):
            reason = 'question_mismatch'
        elif answer_passes(row, case): reason = 'already_answered'
        else:
            lookups = [t for t in row.get('tool_calls', []) if t.get('name') == 'policy.search']
            if not lookups: reason = 'no_policy_lookup'
            elif any(t.get('result', {}).get('retrieval_status') != 'ok' for t in lookups): reason = 'technical'
            elif retrieved_ids(row) & {r['chunk_id'] for r in case['sources']}:
                reason = 'source_already_retrieved_generation_issue'
            else:
                context = lookups[-1]['result'].get('context', {})
                async with repo.transaction() as tx:
                    validity = await validate_sources(tx, case['sources'])
                if not applicable(validity, context.get('on'), context.get('order_date')):
                    reason = 'source_not_applicable_or_date_unverified'
        if reason:
            result['skipped'].append({'case_id': case['id'], 'reason': reason})
            continue
        event = await record_event(repo, {'source': 'evaluation_result', 'actor_id': actor,
            **({'score_sha256': score_sha256} if score_sha256 else {}), 'release_id': release_id,
            'run_id': row['run_id'], 'scenario_id': row['scenario_id'], 'call': row['call'], 'turn': row['turn'],
            'question': row['user_text'], 'answer': row['agent_text'], 'tool_calls': row['tool_calls'],
            'retrieved_ids': sorted(retrieved_ids(row)), 'rating': False, 'signal': 'no_evidence',
            'reason': 'Simulated operator feedback from pre-reviewed experiment plan',
            'context': digest(row)}, f'{run_id}:{case["id"]}')
        deadline = time.monotonic() + timeout
        while True:
            await process_one(worker_repo, 'experiment-analysis', event_ids={event['id']})
            async with repo.transaction() as tx:
                job = await tx.get('jobs', event['id'])
            if job['status'] == 'completed': break
            if job['status'] == 'failed' or time.monotonic() >= deadline:
                raise KnowledgeError('Scoped knowledge analysis failed or timed out; resume without rerunning K0')
            await asyncio.sleep(0.2)
        async with repo.transaction() as tx:
            gap = await tx.get('gaps', job['gap_id'])
        if gap['category'] in {'technical', 'generation', 'correct_refusal'}:
            result['skipped'].append({'case_id': case['id'], 'gap_id': gap['id'], 'reason': gap['category']})
            continue
        if gap['category'] != case['category']:
            await command(repo, actor, 'classify', {'id': gap['id'], 'version': gap['version'],
                'category': case['category'], 'reason': 'Simulated triage: ' + plan['review_note']})
        payload = {key: case.get(key, '') for key in ('kind', 'question', 'answer')}
        payload.update(aliases=case.get('aliases', []), source_ids=[r['chunk_id'] for r in case['sources']],
                       source_review_note=plan['review_note'], scope='simulated experiment')
        # Reuse an exact revision/test on resume; never auto-approve arbitrary worker drafts.
        async with repo.transaction() as tx:
            matches = [r for r in await tx.rows('revisions') if r['gap_id'] == gap['id']
                and all(r.get(k) == v for k, v in payload.items())]
            revision = None
            for candidate in matches:
                test = await tx.get('regression_cases', candidate['id'])
                if test and test.get('variations') == case['variations']:
                    revision = candidate; break
        if revision is None:
            revision = await command(repo, actor, 'create_revision', dict(payload, gap_id=gap['id']))
            async with repo.transaction() as tx:
                test = await tx.get('regression_cases', revision['id'])
            revision = await command(repo, actor, 'edit_test', {'id': revision['id'], 'test_hash': digest(test),
                'expected': test['expected'], 'variations': case['variations']})
        async with repo.transaction() as tx:
            test = await tx.get('regression_cases', revision['id'])
            check_offline_retrieval(revision, test, await tx.sources())
        revision = await command(repo, actor, 'approve', {'id': revision['id'],
            'content_hash': revision['content_hash'], 'reason': 'SIMULATED REVIEW: ' + plan['review_note'],
            'approve_test': True})
        result['approved'].append({'case_id': case['id'], 'event_id': event['id'], 'gap_id': gap['id'],
            'revision_id': revision['id'], 'content_hash': revision['content_hash'], 'test_hash': revision['test_hash'],
            'sources': revision['sources'], 'kind': revision['kind']})
    return result
