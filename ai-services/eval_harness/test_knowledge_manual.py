import asyncio
from copy import deepcopy

import pytest

from eval_harness.test_knowledge_auto_review import repo, row


def test_manual_proposals_are_scoped_idempotent_drafts_never_approvals():
    from eval_harness.knowledge_manual import propose
    from app.knowledge.events.ingest import record_event
    from app.knowledge.services.lifecycle import query
    async def run():
        r = repo()
        await r.put('permissions', 'human', {'permissions': ['knowledge_review']})
        other = await record_event(r, {'source': 'operator_feedback', 'question': 'Other'}, 'other')
        value = row()
        value['tool_calls'][0]['result'].update(retrieval_status='no_evidence',
            context={'on': '2026-11-13', 'knowledge_release_id': 'k0'})
        normal = deepcopy(value)
        normal['turn'] = 2
        normal['tool_calls'][0]['result'].update(retrieval_status='ok', evidence=[{'chunk_id': 'PUBLIC'}])
        result = await propose(r, r, [value, normal, value | {'config': 'baseline_no_memory'}],
            [], actor='human', run_id='experiment', release_id='k0', score_sha256='a'*64)
        assert len(result['proposed']) == 1
        item = result['proposed'][0]
        revision = await r.get('revisions', item['draft_revision_id'])
        assert revision['status'] == 'draft'
        assert await r.rows('decisions') == []
        assert await r.rows('releases') == []
        assert (await r.get('jobs', other['id']))['status'] == 'pending'
        event = await r.get('events', item['event_id'])
        assert event['run_id'] == 'experiment' and event['release_id'] == 'k0'
        assert (await query(r, 'human', 'gaps', run_id='experiment'))['total'] == 1
        assert (await query(r, 'human', 'gaps', run_id='different'))['total'] == 0
        again = await propose(r, r, [value], [], actor='human', run_id='experiment',
            release_id='k0', score_sha256='a'*64)
        assert again['proposed'][0]['draft_revision_id'] == revision['id']
    asyncio.run(run())


@pytest.mark.parametrize('bad', [None, 'foreign_gap', 'rejected', 'test_changed', 'decision_missing',
    'manifest_changed', 'wrong_base', 'snapshot_test_changed'])
def test_collect_only_human_reviewed_published_descendants(bad):
    from eval_harness.knowledge_manual import propose, collect_review
    from app.knowledge.services.lifecycle import command
    async def run():
        r = repo()
        await r.put('permissions', 'human', {'permissions': ['knowledge_review']})
        value = row()
        value['tool_calls'][0]['result'].update(retrieval_status='no_evidence',
            context={'knowledge_release_id': 'k0'})
        proposals = await propose(r, r, [value], [], actor='human', run_id='experiment',
            release_id='k0', score_sha256='a'*64)
        draft = await r.get('revisions', proposals['proposed'][0]['draft_revision_id'])
        edited = await command(r, 'human', 'edit_revision', {'id': draft['id'],
            'content_hash': draft['content_hash'], 'changes': {'source_review_note': 'Checked the public policy.'}})
        approved = await command(r, 'human', 'approve', {'id': edited['id'],
            'content_hash': edited['content_hash'], 'reason': 'Checked content and test', 'approve_test': True})
        previous = {'id': 'k0', 'manifest': {'items': []}}
        from app.knowledge.schemas import digest
        ready = {'id': 'k1', 'base_release_id': 'k0', 'status': 'ready',
            'manifest': {'items': [{k: deepcopy(approved[k]) for k in
                ('id', 'gap_id', 'kind', 'sources', 'content_hash', 'test_hash')}]}}
        ready['manifest_hash'] = digest(ready['manifest'])
        if bad == 'manifest_changed': ready['manifest_hash'] = 'different'
        if bad == 'wrong_base': ready['base_release_id'] = 'foreign'
        if bad == 'snapshot_test_changed':
            ready['manifest']['items'][0]['test_hash'] = 'different'
            ready['manifest_hash'] = digest(ready['manifest'])
        await r.put('releases', 'k0', previous)
        await r.put('releases', 'k1', ready)
        await r.put('active', 'current', {'release_id': 'k0'})
        assert await collect_review(r, proposals, actor='human', run_id='experiment', base='k0') is None
        await r.put('active', 'current', {'release_id': 'k1'})
        if bad == 'foreign_gap':
            approved['gap_id'] = 'unrelated'
            await r.put('revisions', approved['id'], approved)
        if bad == 'rejected':
            approved['status'] = 'rejected'
            await r.put('revisions', approved['id'], approved)
        if bad == 'test_changed':
            test = await r.get('regression_cases', approved['id'])
            test['variations'] = ['Different test']
            await r.put('regression_cases', approved['id'], test)
        if bad == 'decision_missing': r.tables['decisions'] = {}
        if bad:
            with pytest.raises(ValueError):
                await collect_review(r, proposals, actor='human', run_id='experiment', base='k0')
        else:
            review, release = await collect_review(r, proposals, actor='human', run_id='experiment', base='k0')
            assert release['id'] == 'k1'
            assert review['approved'][0]['revision_id'] == edited['id'] != draft['id']
            assert review['approved'][0]['approved_by'] == 'human'
            assert review['approved'][0]['approval_reason'] == 'Checked content and test'
            assert len(await r.rows('decisions')) == 1
    asyncio.run(run())


def test_api_scope_paginates_only_experiment_descendants(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.api import knowledge as api
    from app.knowledge.services.lifecycle import command
    from eval_harness.knowledge_manual import propose
    async def run():
        r = repo()
        await r.put('permissions', 'human', {'permissions': ['knowledge_review']})
        value = row()
        value['tool_calls'][0]['result'].update(retrieval_status='no_evidence',
            context={'knowledge_release_id': 'k0'})
        first = await propose(r, r, [value], [], actor='human', run_id='first',
            release_id='k0', score_sha256='a'*64)
        await propose(r, r, [value], [], actor='human', run_id='second', release_id='k0', score_sha256='a'*64)
        draft = await r.get('revisions', first['proposed'][0]['draft_revision_id'])
        edited = await command(r, 'human', 'edit_revision', {'id': draft['id'],
            'content_hash': draft['content_hash'], 'changes': {'source_review_note': 'Reviewed source.'}})
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.get_knowledge_repo] = lambda: r
        app.dependency_overrides[api.authenticate] = lambda: None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            for resource, total in [('gaps', 1), ('events', 1), ('revisions', 2), ('regression_cases', 2)]:
                result = await client.get('/v1/knowledge/'+resource,
                    params={'actor_id': 'human', 'run_id': 'first', 'limit': 1})
                assert result.status_code == 200
                assert result.json()['total'] == total and len(result.json()['items']) == 1
            result = await client.get('/v1/knowledge/revisions', params={
                'actor_id': 'human', 'run_id': 'first', 'item_id': edited['id']})
            assert result.json()['items'][0]['id'] == edited['id']
    asyncio.run(run())


def test_failed_tasks_with_retrieved_evidence_are_triaged_without_knowledge_draft():
    from eval_harness.knowledge_manual import propose
    async def run():
        r = repo()
        await r.put('permissions', 'human', {'permissions': ['knowledge_review']})
        value = row()
        value['tool_calls'][0]['result'].update(context={'knowledge_release_id': 'k0'},
            evidence=[{'chunk_id': 'PUBLIC'}])
        feedback = [{'event': {'source': 'evaluation_result', 'signal': 'evaluation_failure',
            'scenario_id': 'LOCAL', 'call': 'call_1', 'turn': '1', 'question': value['user_text'],
            'answer': value['agent_text'], 'tool_calls': value['tool_calls'], 'reason': 'Task failed'}}]
        result = await propose(r, r, [value], feedback, actor='human', run_id='experiment',
            release_id='k0', score_sha256='a'*64)
        assert result['proposed'][0]['category'] == 'generation'
        assert result['proposed'][0]['draft_revision_id'] is None
        assert await r.rows('revisions') == [] and await r.rows('decisions') == []
    asyncio.run(run())
