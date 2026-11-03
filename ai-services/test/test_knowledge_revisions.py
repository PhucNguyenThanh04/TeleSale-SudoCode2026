import unittest
from test_knowledge_repo import MemoryRepo
from app.knowledge.schemas import Conflict, KnowledgeError

SOURCE = {'chunk_id': 'DT-01', 'source_hash': 'hash1', 'access_level': 'public',
          'date_basis': 'order_date', 'effective_from': '2026-10-01',
          'effective_until': None, 'title': 'Đổi trả', 'body': 'Đổi khi còn nguyên tem.'}


async def fixture():
    repo = MemoryRepo([dict(SOURCE)])
    await repo.put('permissions', 'reviewer', {'permissions': ['knowledge_review']})
    await repo.put('gaps', 'g', {'id': 'g', 'event_ids': [], 'version': 1, 'status': 'triaged',
                               'category': 'content', 'title': 'Đổi hàng'})
    return repo


class RevisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_validation_dates_hash_and_access(self):
        from app.knowledge.services.source_validation import validate_sources
        repo = await fixture()
        refs = [{'chunk_id': 'DT-01', 'source_hash': 'hash1'}]
        result = await validate_sources(repo, refs)
        self.assertEqual(result['date_basis'], 'order_date')
        repo.source_rows['DT-01']['access_level'] = 'internal'
        with self.assertRaises(KnowledgeError):
            await validate_sources(repo, refs)

    async def test_revision_approval_bound_to_hash_and_test(self):
        from app.knowledge.services.revisions import create_revision, decide_revision, edit_revision
        repo = await fixture()
        revision = await create_revision(repo, 'reviewer', 'g', {'kind': 'faq',
            'question': 'Đổi khi nào?', 'answer': 'Cần còn nguyên tem.',
            'source_ids': ['DT-01'], 'source_review_note': 'Đã kiểm toàn bộ tài liệu liên quan.'})
        self.assertEqual(revision['status'], 'draft')
        approved = await decide_revision(repo, 'reviewer', revision['id'], revision['content_hash'],
                                          'approve', 'Đúng điều khoản', True)
        self.assertEqual(approved['status'], 'approved')
        changed = await edit_revision(repo, 'reviewer', revision['id'], revision['content_hash'],
                                      {'answer': 'Vui lòng giữ tem.'})
        self.assertEqual(changed['status'], 'draft')
        with self.assertRaises(Conflict):
            await decide_revision(repo, 'reviewer', changed['id'], revision['content_hash'], 'approve', 'ok', True)
        case = await repo.get('regression_cases', changed['id'])
        self.assertNotIn('expected', str(case['input']))
        self.assertFalse(case['approved'])

    async def test_restricted_dynamic_price_and_unknown_sources_rejected(self):
        from app.knowledge.services.revisions import create_revision
        repo = await fixture()
        for answer, sources in [('Giá 4.890.000đ', ['DT-01']), ('Không rõ', ['missing'])]:
            with self.assertRaises(KnowledgeError):
                await create_revision(repo, 'reviewer', 'g', {'kind': 'faq', 'question': 'Giá?',
                    'answer': answer, 'source_ids': sources, 'source_review_note': 'review'})

    async def test_no_source_waits_and_does_not_publish(self):
        from app.knowledge.services.revisions import create_revision
        repo = await fixture()
        with self.assertRaises(KnowledgeError):
            await create_revision(repo, 'reviewer', 'g', {'kind': 'faq', 'question': 'Q',
                'answer': 'A', 'source_ids': [], 'source_review_note': 'review'})
        self.assertEqual(await repo.rows('revisions'), [])
