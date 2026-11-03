import unittest
from test_knowledge_revisions import fixture
from app.knowledge.events.ingest import record_event
from app.knowledge.events.worker import process_one
from app.knowledge.services.lifecycle import command, query
from app.knowledge.services.supplements import supplement_candidates


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_feedback_sources_to_reviewed_release_and_verification(self):
        repo = await fixture()
        for source in ('operator_feedback', 'evaluation_result'):
            await record_event(repo, {'source':source, 'question':'đổi hàng còn tem',
                'answer':'Chưa rõ', 'signal':'no_evidence'}, source)
            await process_one(repo, 'worker')
        gaps = [g for g in await repo.rows('gaps') if g['id']!='g']
        self.assertEqual(len(gaps), 2)
        first = gaps[0]
        r = await command(repo, 'reviewer', 'create_revision', {'gap_id':first['id'],
            'kind':'faq', 'question':'đổi hàng còn tem', 'answer':'Cần còn nguyên tem.',
            'source_ids':['DT-01'], 'source_review_note':'Đã đối chiếu điều kiện.'})
        await command(repo, 'reviewer', 'approve', {'id':r['id'], 'content_hash':r['content_hash'],
            'reason':'Đúng nguồn, đã duyệt test', 'approve_test':True})
        release = await command(repo, 'reviewer', 'prepare_release', {'revision_ids':[r['id']], 'expected_active_id':None})
        await command(repo, 'reviewer', 'activate_release', {'id':release['id'], 'expected_active_id':None})
        async with repo.transaction() as tx:
            candidates = await supplement_candidates(tx, release['id'], '2026-10-15', '2026-10-15')
        self.assertEqual(candidates[0]['body'], 'Cần còn nguyên tem.')
        self.assertEqual(candidates[0]['source_chunk_ids'], ['DT-01'])
        current = (await query(repo, 'reviewer', 'gaps', item_id=first['id']))['items'][0]
        self.assertEqual(current['status'], 'awaiting_verification')
        await repo.put('verification_runs', 'verified', {'id':'verified', 'complete':True,
            'comparability_valid':True, 'release_id':release['id']})
        resolved = await command(repo, 'reviewer', 'verify_gap', {'id':current['id'],
            'version':current['version'], 'verification_run_id':'verified', 'resolved':True,
            'reason':'Đã kiểm tra case liên quan và trace trước/sau.'})
        self.assertEqual(resolved['status'], 'resolved')

    async def test_worker_suggests_merge_but_does_not_merge_automatically(self):
        repo = await fixture()
        for k in ('one', 'two'):
            await record_event(repo, {'source':'runtime_signal','question':'đổi hàng còn tem','signal':'no_evidence'}, k)
            await process_one(repo,'worker')
        gaps=[g for g in await repo.rows('gaps') if g['id']!='g']
        self.assertEqual(len(gaps),2)
        self.assertTrue(any(g.get('suggested_merge_ids') for g in gaps))
