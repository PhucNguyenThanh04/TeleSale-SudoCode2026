import asyncio
import re
import time
import unicodedata

from app.knowledge.events.evidence import safe_text
from app.knowledge.events.ingest import record_event
from app.knowledge.events.worker import process_one
from app.knowledge.schemas import KnowledgeError, digest
from app.knowledge.services.lifecycle import command
from app.knowledge.services.permissions import require_permission
from app.knowledge.services.regression import check_offline_retrieval
from app.knowledge.services.revisions import content_hash
from app.knowledge.services.source_validation import applicable, validate_sources
from eval_harness.knowledge_auto_review import locator, retrieved_ids

MODE = 'automatic_source_checked'


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def dynamic_commerce(text):
    return bool(re.search(r'\b(gia|price|pricing|promo\w*|discount\w*|stock|inventory|ton kho|'
        r'khuyen mai|uu dai|giam gia|coupon|voucher|phi|cuoc|sku)\b|'
        r'\d[\d., ]*\s*(?:vnd|dong|trieu|nghin|k\b)', normalized(text)))


def source_match(question, sources, selected):
    stop = set('toi em anh chi la co khong va thi cho cua voi mot cac nay do a nhe nao duoc can'.split())
    def words(text): return set(re.findall(r'\w+', normalized(text))) - stop
    query = words(question)
    ranks = sorted([(len(query & words(s.get('title', '')+' '+s.get('body', ''))), s['chunk_id'])
                    for s in sources if s.get('access_level') == 'public'], reverse=True)
    return bool(ranks and ranks[0][1] == selected and ranks[0][0] >= max(2, len(query)*0.5)
                and (len(ranks) == 1 or ranks[0][0] > ranks[1][0]))


async def source_catalog_digest(repo, actor):
    async with repo.transaction() as tx:
        await require_permission(tx, actor)
        sources = [s for s in await tx.sources() if s.get('access_level') == 'public']
    return digest(sorted(sources, key=lambda s: s['chunk_id']))


async def review_proposals(repo, worker_repo, rows, *, actor, run_id, timeout=60,
                           score_sha256=None, release_id=None, max_approvals=100):
    async with repo.transaction() as tx:
        await require_permission(tx, actor)
    result = {'approval_mode': MODE, 'actor_id': actor, 'approved': [], 'skipped': [],
              'limitations': ['Lexical relevance is not semantic verification.',
                              'Generated regression checks do not measure LLM answer correctness.']}
    for row in rows:
        key = digest(list(locator(row)))[:24]
        item = {'case_id': key, 'locator': list(locator(row))}
        reason = None
        lookups = [t for t in row.get('tool_calls', []) if t.get('name') == 'policy.search']
        question = safe_text(row.get('user_text', row.get('customer_text', ''))).strip()
        if row.get('config') != 'full': reason = 'not_full_k0'
        elif not lookups: reason = 'no_policy_lookup'
        elif any(t.get('result', {}).get('retrieval_status') not in {'ok', 'no_evidence'} for t in lookups): reason = 'technical'
        elif release_id and any(t.get('result', {}).get('context', {}).get('knowledge_release_id') != release_id for t in lookups):
            reason = 'lookup_release_mismatch'
        elif any(e.get('applicability', {}).get('status') in {'conditional', 'conflict'}
                 for t in lookups for e in t.get('result', {}).get('evidence', [])):
            reason = 'conditional_or_conflicting_evidence'
        elif not question: reason = 'missing_question'
        elif dynamic_commerce(question): reason = 'dynamic_commerce_topic'
        elif len(result['approved']) >= max_approvals: reason = 'release_revision_limit'
        if reason:
            result['skipped'].append(item | {'reason': reason}); continue
        event = await record_event(repo, {'source': 'evaluation_result', 'actor_id': actor,
            **({'score_sha256': score_sha256} if score_sha256 else {}), 'release_id': release_id,
            'run_id': row['run_id'], 'scenario_id': row['scenario_id'], 'call': row['call'], 'turn': row['turn'],
            'question': question, 'answer': row['agent_text'], 'tool_calls': row['tool_calls'],
            'retrieved_ids': sorted(retrieved_ids(row)), 'signal': 'no_evidence',
            'reason': 'Automatic experimental triage of K0 policy lookup; no human rating or correctness label',
            'context': digest(row)}, f'{run_id}:automatic:{key}')
        item['event_id'] = event['id']
        deadline = time.monotonic() + timeout
        while True:
            await process_one(worker_repo, 'experiment-analysis', event_ids={event['id']})
            async with repo.transaction() as tx:
                job = await tx.get('jobs', event['id'])
            if job['status'] == 'completed': break
            if job['status'] in {'failed', 'erased'} or time.monotonic() >= deadline:
                raise KnowledgeError('Scoped knowledge analysis failed or timed out; resume without rerunning K0')
            await asyncio.sleep(0.2)
        async with repo.transaction() as tx:
            gap = await tx.get('gaps', job['gap_id'])
            revision = await tx.get('revisions', gap.get('draft_revision_id', ''))
            sources = await tx.sources()
            test = await tx.get('regression_cases', revision['id']) if revision else None
            item['gap_id'] = gap['id']
            if gap['category'] not in {'retrieval', 'content', 'insufficient_evidence'}:
                reason = gap['category']
            elif not revision or revision.get('gap_id') != gap['id']:
                reason = 'no_worker_draft'
            elif revision.get('content_hash') != content_hash(revision):
                reason = 'proposal_hash_mismatch'
            elif len(revision['source_ids']) != 1:
                reason = 'multiple_sources_require_manual_review'
            elif set(revision['source_ids']) & retrieved_ids(row):
                reason = 'source_already_retrieved_generation_issue'
            else:
                try:
                    metadata = await validate_sources(tx, revision['sources'])
                    source = next(s for s in sources if s['chunk_id'] == revision['source_ids'][0])
                    context = lookups[-1]['result'].get('context', {})
                    if not applicable(metadata, context.get('on'), context.get('order_date')):
                        reason = 'source_not_applicable_or_date_unverified'
                    elif dynamic_commerce(source.get('title', '')+' '+source.get('body', '')):
                        reason = 'dynamic_commerce_topic'
                    elif not source_match(question, sources, source['chunk_id']):
                        reason = 'ambiguous_or_weak_source_match'
                    elif (revision['question'] != question or revision['kind'] not in {'faq', 'aliases'}
                          or revision['kind'] == 'faq' and revision['answer'] != source.get('body', '').strip()
                          or revision['kind'] == 'aliases' and revision['aliases'] != [question]):
                        reason = 'unsupported_proposal_content'
                    elif (not test or test['expected'].get('source_ids') != revision['source_ids']
                          or test['expected'].get('answer') != revision.get('answer', '')):
                        reason = 'invalid_regression_case'
                    else:
                        check_offline_retrieval(revision, test, sources)
                except ValueError:
                    reason = 'source_or_regression_validation_failed'
        if reason:
            result['skipped'].append(item | {'reason': reason}); continue
        revision = await command(repo, actor, 'approve', {'id': revision['id'],
            'content_hash': revision['content_hash'], 'approve_test': True,
            'reason': 'AUTOMATIC EXPERIMENT: public source hash/date, lexical relevance, source-bound content and offline retrieval checked; no human review'})
        result['approved'].append(item | {'revision_id': revision['id'], 'content_hash': revision['content_hash'],
            'test_hash': revision['test_hash'], 'sources': revision['sources'], 'kind': revision['kind'],
            'question': question})
    return result
