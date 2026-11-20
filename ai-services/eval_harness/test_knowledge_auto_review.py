import asyncio
from copy import deepcopy

import pytest

from test_knowledge_repo import MemoryRepo


def plan():
    return {'schema_version': 1, 'reviewed_by': 'domain-reviewer', 'review_note': 'Checked public source.',
        'cases': [{'id': 'condition', 'scenario_id': 'LOCAL', 'call': 'call_1', 'turn': 1,
            'question': 'Điều kiện giữ hộp đổi hàng?', 'kind': 'faq', 'category': 'content',
            'answer': 'Cần giữ nguyên hộp.', 'aliases': [],
            'sources': [{'chunk_id': 'PUBLIC', 'source_hash': 'a' * 64}],
            'variations': ['Đổi hàng phải giữ hộp không?'], 'must_say': ['nguyên hộp'], 'must_not_say': []}]}


def row(answer='Em chưa có thông tin.'):
    return {'scenario_id': 'LOCAL', 'call': 'call_1', 'turn': 1, 'config': 'full',
        'run_id': 'k0-full', 'user_text': plan()['cases'][0]['question'], 'agent_text': answer,
        'tool_calls': [{'name': 'policy.search', 'args': {},
                        'result': {'retrieval_status': 'ok', 'context': {'on': '2026-11-13'}, 'evidence': []}}]}


def repo():
    return MemoryRepo([{'chunk_id': 'PUBLIC', 'source_hash': 'a' * 64, 'access_level': 'public',
        'date_basis': 'call_date', 'title': 'Điều kiện giữ hộp đổi hàng', 'body': 'Cần giữ nguyên hộp.'}])


def test_plan_requires_pinned_sources_and_nonempty_answer_assertions():
    from eval_harness.knowledge_auto_review import validate_plan
    assert validate_plan(plan())['cases'][0]['id'] == 'condition'
    for change in [{'sources': []}, {'must_say': []}, {'sources': [{'chunk_id': 'PUBLIC', 'source_hash': 'wrong'}]}]:
        bad = plan(); bad['cases'][0].update(change)
        with pytest.raises(ValueError): validate_plan(bad)


def test_scoped_worker_does_not_claim_unrelated_jobs():
    from app.knowledge.events.ingest import record_event
    from app.knowledge.events.worker import process_one
    async def run():
        r = repo()
        unrelated = await record_event(r, {'source': 'operator_feedback', 'question': 'Other question'}, 'other')
        selected = await record_event(r, {'source': 'operator_feedback', 'question': 'giữ hộp đổi hàng'}, 'selected')
        await process_one(r, 'worker', event_ids={selected['id']})
        assert (await r.get('jobs', unrelated['id']))['status'] == 'pending'
        assert (await r.get('jobs', selected['id']))['status'] == 'completed'
    asyncio.run(run())


def test_review_enforces_permissions_and_source_hash_before_writes():
    from eval_harness.knowledge_auto_review import auto_review
    async def run():
        r = repo(); before = deepcopy(r.tables)
        with pytest.raises(ValueError):
            await auto_review(r, r, plan(), [row()], actor='simulated-reviewer', run_id='experiment')
        assert r.tables == before
        await r.put('permissions', 'simulated-reviewer', {'permissions': ['knowledge_review']})
        r.source_rows['PUBLIC']['source_hash'] = 'b' * 64
        before = deepcopy(r.tables)
        with pytest.raises(ValueError):
            await auto_review(r, r, plan(), [row()], actor='simulated-reviewer', run_id='experiment')
        assert r.tables == before
    asyncio.run(run())


def test_simulated_review_has_real_feedback_job_decision_and_reviewed_test():
    from eval_harness.knowledge_auto_review import auto_review
    async def run():
        r = repo()
        await r.put('permissions', 'simulated-reviewer', {'permissions': ['knowledge_review']})
        result = await auto_review(r, r, plan(), [row()], actor='simulated-reviewer', run_id='experiment')
        item = result['approved'][0]
        rev = await r.get('revisions', item['revision_id'])
        assert rev['status'] == 'approved'
        assert (await r.get('regression_cases', rev['id']))['variations'] == plan()['cases'][0]['variations']
        assert (await r.get('events', item['event_id']))['run_id'] == 'k0-full'
        assert (await r.get('jobs', item['event_id']))['status'] == 'completed'
        assert result['approval_mode'] == 'simulated_pre_reviewed_plan'
        again = await auto_review(r, r, plan(), [row()], actor='simulated-reviewer', run_id='experiment')
        assert again['approved'][0]['revision_id'] == rev['id']
    asyncio.run(run())


@pytest.mark.parametrize('case_row,reason', [
    (row('Cần giữ nguyên hộp.'), 'already_answered'),
    (row() | {'config': 'baseline_no_memory'}, 'not_full_k0'),
    (row() | {'tool_calls': []}, 'no_policy_lookup'),
    (row() | {'tool_calls': [{'name': 'policy.search', 'args': {}, 'result': {'retrieval_status': 'timeout'}}]}, 'technical'),
    (row() | {'tool_calls': [{'name': 'policy.search', 'args': {}, 'result': {'retrieval_status': 'ok',
        'context': {'on': '2026-11-13'}, 'evidence': [{'chunk_id': 'PUBLIC'}]}}]}, 'source_already_retrieved_generation_issue'),
    (row() | {'tool_calls': [{'name': 'policy.search', 'args': {}, 'result': {'retrieval_status': 'ok',
        'evidence': []}}]}, 'source_not_applicable_or_date_unverified'),
])
def test_ineligible_turns_never_become_approved_gap(case_row, reason):
    from eval_harness.knowledge_auto_review import auto_review
    async def run():
        r = repo(); await r.put('permissions', 'simulated-reviewer', {'permissions': ['knowledge_review']})
        result = await auto_review(r, r, plan(), [case_row], actor='simulated-reviewer', run_id='experiment')
        assert result['approved'] == []
        assert result['skipped'][0]['reason'] == reason
        assert await r.rows('events') == []
    asyncio.run(run())


def test_public_source_export_is_read_only_and_cannot_overwrite(tmp_path):
    from eval_harness.knowledge_triplet import export_sources
    async def run():
        r = repo(); await r.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
        r.source_rows['private'] = {'chunk_id': 'private', 'access_level': 'internal'}
        before = deepcopy(r.tables)
        output = tmp_path/'public.json'
        await export_sources(r, 'reviewer', output)
        assert 'private' not in output.read_text()
        assert r.tables == before
        with pytest.raises(ValueError): await export_sources(r, 'reviewer', output)
    asyncio.run(run())
