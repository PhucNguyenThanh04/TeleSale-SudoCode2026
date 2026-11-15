"""Automatic review consumes worker drafts, never an advance answer plan."""
import asyncio
from copy import deepcopy

import pytest

from eval_harness.test_knowledge_auto_review import repo, row


def test_automatic_review_real_worker_approval_and_idempotent_resume():
    from eval_harness.knowledge_automatic import review_proposals
    async def run():
        r = repo()
        await r.put('permissions', 'robot', {'permissions': ['knowledge_review']})
        result = await review_proposals(r, r, [row()], actor='robot', run_id='experiment')
        assert result['approval_mode'] == 'automatic_source_checked'
        item = result['approved'][0]
        revision = await r.get('revisions', item['revision_id'])
        assert revision['status'] == 'approved' and revision['kind'] == 'aliases'
        assert (await r.get('jobs', item['event_id']))['status'] == 'completed'
        assert (await r.get('regression_cases', revision['id']))['approved'] is True
        assert len(await r.rows('decisions')) == 1
        again = await review_proposals(r, r, [row()], actor='robot', run_id='experiment')
        assert again['approved'][0]['revision_id'] == revision['id']
        assert len(await r.rows('decisions')) == 1
        assert r.source_rows['PUBLIC']['body'] == 'Cần giữ nguyên hộp.'
    asyncio.run(run())


@pytest.mark.parametrize('change,reason', [
    ({'config': 'baseline_no_memory'}, 'not_full_k0'),
    ({'tool_calls': []}, 'no_policy_lookup'),
    ({'user_text': 'Giá và khuyến mãi thế nào?'}, 'dynamic_commerce_topic'),
    ({'tool_calls': [{'name': 'policy.search', 'result': {'retrieval_status': 'timeout'}}]}, 'technical'),
    ({'tool_calls': [{'name': 'policy.search', 'result': {'retrieval_status': 'ok',
        'context': {'on': '2026-11-13'}, 'evidence': [{'chunk_id': 'PUBLIC'}]}}]},
        'source_already_retrieved_generation_issue'),
    ({'tool_calls': [{'name': 'policy.search', 'result': {'retrieval_status': 'ok', 'evidence': []}}]},
        'source_not_applicable_or_date_unverified'),
])
def test_ineligible_proposals_are_logged_not_approved(change, reason):
    from eval_harness.knowledge_automatic import review_proposals
    async def run():
        r = repo(); await r.put('permissions', 'robot', {'permissions': ['knowledge_review']})
        result = await review_proposals(r, r, [row() | change], actor='robot', run_id='experiment')
        assert result['approved'] == []
        assert result['skipped'][0]['reason'] == reason
        assert await r.rows('decisions') == []
    asyncio.run(run())


def test_ambiguous_source_and_unrelated_old_draft_are_not_approved():
    from eval_harness.knowledge_automatic import review_proposals
    async def run():
        r = repo(); await r.put('permissions', 'robot', {'permissions': ['knowledge_review']})
        r.source_rows['OTHER'] = dict(r.source_rows['PUBLIC'], chunk_id='OTHER')
        await r.put('revisions', 'unrelated', {'id': 'unrelated', 'status': 'draft'})
        result = await review_proposals(r, r, [row()], actor='robot', run_id='experiment')
        assert result['approved'] == []
        assert result['skipped'][0]['reason'] == 'ambiguous_or_weak_source_match'
        assert (await r.get('revisions', 'unrelated'))['status'] == 'draft'
    asyncio.run(run())


def test_permissions_checked_before_feedback_writes():
    from eval_harness.knowledge_automatic import review_proposals
    async def run():
        r = repo(); before = deepcopy(r.tables)
        with pytest.raises(ValueError):
            await review_proposals(r, r, [row()], actor='robot', run_id='experiment')
        assert r.tables == before
    asyncio.run(run())


@pytest.mark.parametrize('mode,reason', [
    ('expired', 'source_not_applicable_or_date_unverified'),
    ('unverified_order', 'source_not_applicable_or_date_unverified'),
    ('dynamic_source', 'dynamic_commerce_topic'),
    ('changed_hash', 'source_or_regression_validation_failed'),
    ('unsupported_faq', 'unsupported_proposal_content'),
    ('bad_regression', 'source_or_regression_validation_failed'),
    ('wrong_release', 'lookup_release_mismatch'),
    ('capacity', 'release_revision_limit'),
])
def test_source_content_and_regression_gates(monkeypatch, mode, reason):
    from eval_harness import knowledge_automatic as mod
    from app.knowledge.events.worker import process_one
    from app.knowledge.services.revisions import content_hash
    async def run():
        r = repo(); await r.put('permissions', 'robot', {'permissions': ['knowledge_review']})
        if mode == 'expired': r.source_rows['PUBLIC']['effective_until'] = '2020-01-01'
        if mode == 'unverified_order': r.source_rows['PUBLIC']['date_basis'] = 'order_date'
        if mode == 'dynamic_source': r.source_rows['PUBLIC']['body'] += ' Khuyến mãi 100.000 VND.'
        async def worker(*args, **kwargs):
            await process_one(*args, **kwargs)
            if mode == 'changed_hash': r.source_rows['PUBLIC']['source_hash'] = 'b'*64
            if mode == 'unsupported_faq':
                for revision in await r.rows('revisions'):
                    revision.update(kind='faq', answer='Không cần giữ hộp.')
                    revision['content_hash'] = content_hash(revision)
                    await r.put('revisions', revision['id'], revision)
        monkeypatch.setattr(mod, 'process_one', worker)
        if mode == 'bad_regression':
            def fail(*args): raise ValueError('retrieval failed')
            monkeypatch.setattr(mod, 'check_offline_retrieval', fail)
        result = await mod.review_proposals(r, r, [row()], actor='robot', run_id='experiment',
            release_id='different-release' if mode == 'wrong_release' else None,
            max_approvals=0 if mode == 'capacity' else 100)
        assert result['approved'] == []
        assert result['skipped'][0]['reason'] == reason
        assert await r.rows('decisions') == []
    asyncio.run(run())


def test_real_no_evidence_status_is_analyzed_and_unrelated_job_is_left_pending():
    from eval_harness.knowledge_automatic import review_proposals
    from app.knowledge.events.ingest import record_event
    async def run():
        r = repo(); await r.put('permissions', 'robot', {'permissions': ['knowledge_review']})
        unrelated = await record_event(r, {'source': 'operator_feedback', 'question': 'khác'}, 'unrelated')
        value = row(); value['tool_calls'][0]['result']['retrieval_status'] = 'no_evidence'
        result = await review_proposals(r, r, [value], actor='robot', run_id='experiment')
        assert len(result['approved']) == 1
        assert (await r.get('jobs', unrelated['id']))['status'] == 'pending'
    asyncio.run(run())


def test_automatic_report_counts_retrieval_without_self_scoring_answers():
    from eval_harness.knowledge_triplet import comparison_report, render_report
    before = row(); after = row('Một câu trả lời bất kỳ, chưa được xác minh.')
    after['tool_calls'][0]['result'].update(context={'knowledge_release_id': 'k1'}, evidence=[{'chunk_id': 'PUBLIC'}])
    item = {'case_id': 'case', 'locator': ['LOCAL', 'call_1', 1], 'kind': 'aliases',
            'revision_id': 'rev', 'sources': [{'chunk_id': 'PUBLIC'}]}
    evidence = comparison_report(None, [before], [before], [after], [item], 'k1')
    assert evidence['target_evidence_in_k1'] == {'retrieved': 1, 'total': 1}
    assert 'gap_answer_accuracy' not in evidence and 'fixed_answers' not in evidence
    text = render_report({'approval_mode': 'automatic_source_checked', 'gap_evidence': evidence,
        'btc_metrics': {'no_memory_k0': {}, 'full_k0': {}, 'full_k1': {}}})
    assert 'no human review' in text and 'not measured' in text
    assert 'Answers fixed:' not in text
