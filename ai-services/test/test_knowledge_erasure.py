import unittest
from test_knowledge_revisions import fixture
from app.knowledge.ingest import record_event
from app.knowledge.worker import process_one
from app.knowledge.schemas import digest


class ErasureTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_inflight_does_not_recreate_erased_evidence(self):
        from app.knowledge.erasure import erase_customer
        repo = await fixture()
        await record_event(repo, {'source': 'runtime_signal', 'customer_id': 'c', 'question': 'đổi hàng'}, 'k')
        async def analyzer(*args):
            await erase_customer(repo, 'c')
            return {'category': 'content', 'title': 'must not resurrect', 'suggested_source_ids': []}
        await process_one(repo, 'worker', analyzer=analyzer)
        self.assertFalse(any(g.get('title') == 'must not resurrect' for g in await repo.rows('gaps')))

    async def test_erase_invalidates_active_derived_release_and_outbox(self):
        from app.knowledge.erasure import erase_customer
        from app.knowledge.revisions import create_revision, decide_revision
        from app.knowledge.releases import prepare_release, activate_release
        repo = await fixture()
        event = await record_event(repo, {'source': 'operator_feedback', 'customer_id': 'c',
                                         'question': 'đổi hàng'}, 'k')
        gap = await repo.get('gaps', 'g'); gap['event_ids'] = [event['id']]; await repo.put('gaps', 'g', gap)
        await repo.put('backend_outbox', 'out', {'id': 'out', 'status': 'pending',
            'payload': {'event': {'customer_id': 'c', 'question': 'đổi hàng'}}})
        r = await create_revision(repo, 'reviewer', 'g', {'kind': 'faq', 'question': 'đổi hàng',
            'answer': 'Còn tem', 'source_ids': ['DT-01'], 'source_review_note': 'review'})
        await decide_revision(repo, 'reviewer', r['id'], r['content_hash'], 'approve', 'ok', True)
        release = await prepare_release(repo, [r['id']], None, 'reviewer')
        await activate_release(repo, release['id'], None, 'reviewer')
        await erase_customer(repo, 'c')
        self.assertEqual((await repo.get('active', 'current'))['release_id'], 'btc-only')
        self.assertEqual((await repo.get('backend_outbox', 'out'))['status'], 'erased')
        self.assertNotIn('đổi hàng', str(await repo.rows('revisions')))

    async def test_case_editor_receives_server_hash(self):
        from app.knowledge.revisions import create_revision
        from app.knowledge.service import query, command
        repo = await fixture()
        revision = await create_revision(repo, 'reviewer', 'g', {'kind': 'faq', 'question': 'đổi hàng',
            'answer': 'Còn tem', 'source_ids': ['DT-01'], 'source_review_note': 'review'})
        result = await query(repo, 'reviewer', 'regression_cases', item_id=revision['id'])
        case = result['items'][0]
        expected_hash = case.pop('record_hash')
        self.assertEqual(expected_hash, digest(case))

    async def test_knowledge_erasure_failure_is_reported_partial(self):
        from test_langmem_erasure import Repo
        from app.mcp_servers.mcp_memory.services.erasure_executor import execute_erasure
        from uuid import uuid4
        class FailingRepo(Repo):
            async def purge_knowledge_evidence(self, *args):
                raise OSError('must not leak raw exception')
        result = await execute_erasure(FailingRepo(), str(uuid4()))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['store_results']['knowledge']['status'], 'pending')
