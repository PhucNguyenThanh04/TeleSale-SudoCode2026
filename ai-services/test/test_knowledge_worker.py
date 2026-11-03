import unittest
from test_knowledge_repo import MemoryRepo
from app.knowledge.events.ingest import record_event


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_and_retry_without_duplicate_gaps(self):
        from app.knowledge.events.worker import process_one
        repo = MemoryRepo()
        await record_event(repo, {'source': 'runtime_signal', 'question': 'đổi hàng',
            'signal': 'no_evidence'}, 'one')
        self.assertTrue(await process_one(repo, 'worker'))
        gaps = await repo.rows('gaps')
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]['category'], 'insufficient_evidence')
        self.assertFalse(await process_one(repo, 'worker'))

    async def test_failed_analysis_retries_and_exhausts(self):
        from app.knowledge.events.worker import process_one
        repo = MemoryRepo()
        out = await record_event(repo, {'source': 'runtime_signal', 'question': 'đổi hàng'}, 'fail')
        async def broken(*args):
            raise ValueError('sensitive raw exception must not be stored')
        for i in range(5):
            self.assertTrue(await process_one(repo, 'w', analyzer=broken, now=10000*i))
        job = await repo.get('jobs', out['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertNotIn('sensitive', str(job))

    async def test_merge_and_split_keep_provenance(self):
        from app.knowledge.events.worker import process_one
        from app.knowledge.services.gaps import update_gap
        repo = MemoryRepo()
        await repo.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
        for k in ('one', 'two'):
            await record_event(repo, {'source': 'runtime_signal', 'question': k}, k)
            await process_one(repo, 'w')
        a, b = await repo.rows('gaps')
        merged = await update_gap(repo, a['id'], 'reviewer', 1, 'merge', {'other_id': b['id']})
        self.assertEqual(len(merged['event_ids']), 2)
        split = await update_gap(repo, a['id'], 'reviewer', merged['version'], 'split', {'event_ids': b['event_ids']})
        self.assertEqual(len(split['event_ids']), 1)
        self.assertEqual(len(await repo.rows('events')), 2)

    async def test_claim_lease_and_erasure_race(self):
        from app.knowledge.events.worker import claim_job, process_one
        repo = MemoryRepo()
        event = await record_event(repo, {'source': 'runtime_signal', 'question': 'đổi', 'customer_id': 'c'}, 'k')
        self.assertIsNotNone(await claim_job(repo, 'w1', 0))
        self.assertIsNone(await claim_job(repo, 'w2', 1))
        await repo.put('erasures', 'c', {'id': 'c'})
        await process_one(repo, 'w2', now=301)
        self.assertEqual(await repo.rows('gaps'), [])
        self.assertEqual((await repo.get('jobs', event['id']))['status'], 'erased')

    async def test_positive_feedback_is_evidence_not_an_automatic_gap(self):
        from app.knowledge.events.worker import process_one
        repo = MemoryRepo()
        await record_event(repo, {'source':'operator_feedback', 'question':'đổi hàng',
                                 'answer':'Còn nguyên tem', 'rating': True}, 'positive')
        await process_one(repo, 'w')
        self.assertEqual(await repo.rows('gaps'), [])
        self.assertEqual(len(await repo.rows('events')), 1)

    async def test_triage_reason_is_masked_before_storage(self):
        from app.knowledge.services.gaps import update_gap
        repo = MemoryRepo()
        await repo.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
        await repo.put('gaps', 'g', {'id':'g', 'version':1, 'status':'new', 'event_ids':[]})
        result = await update_gap(repo, 'g', 'reviewer', 1, 'classify',
                                  {'category':'content', 'reason':'Khách báo số 0123456789'})
        self.assertNotIn('0123456789', str(result))
