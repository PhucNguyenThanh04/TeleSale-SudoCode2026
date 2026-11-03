import unittest
from test_knowledge_revisions import fixture
from app.knowledge.schemas import Conflict, KnowledgeError


async def approved(repo, question='Đổi khi nào?'):
    from app.knowledge.revisions import create_revision, decide_revision
    r = await create_revision(repo, 'reviewer', 'g', {'kind': 'faq', 'question': question,
        'answer': 'Cần còn nguyên tem.', 'source_ids': ['DT-01'], 'source_review_note': 'Đã rà nguồn'})
    await decide_revision(repo, 'reviewer', r['id'], r['content_hash'], 'approve', 'Đúng nguồn', True)
    return r


class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_and_cas_keeps_immutable_release(self):
        from app.knowledge.releases import prepare_release, activate_release
        repo = await fixture()
        r = await approved(repo)
        release = await prepare_release(repo, [r['id']], None, 'reviewer')
        self.assertIsNone(await repo.get('active', 'current'))
        await activate_release(repo, release['id'], None, 'reviewer')
        with self.assertRaises(Conflict):
            await activate_release(repo, release['id'], 'wrong', 'reviewer')
        self.assertEqual((await repo.get('active', 'current'))['release_id'], release['id'])

    async def test_source_changes_after_preparation_prevent_activation(self):
        from app.knowledge.releases import prepare_release, activate_release
        repo = await fixture()
        r = await approved(repo)
        release = await prepare_release(repo, [r['id']], None, 'reviewer')
        repo.source_rows['DT-01']['source_hash'] = 'new'
        with self.assertRaises(KnowledgeError):
            await activate_release(repo, release['id'], None, 'reviewer')
        self.assertIsNone(await repo.get('active', 'current'))

    async def test_draft_not_publishable_and_stale_test_blocked(self):
        from app.knowledge.releases import prepare_release
        repo = await fixture()
        r = await approved(repo)
        case = await repo.get('regression_cases', r['id'])
        case['expected']['answer'] = 'changed'
        await repo.put('regression_cases', r['id'], case)
        with self.assertRaises(Conflict):
            await prepare_release(repo, [r['id']], None, 'reviewer')

    async def test_offline_retrieval_check_blocks_unreachable_variation(self):
        from app.knowledge.releases import prepare_release
        from app.knowledge.revisions import create_revision, decide_revision
        repo = await fixture()
        r = await create_revision(repo, 'reviewer', 'g', {'kind':'faq', 'question':'đổi hàng',
            'answer':'Còn nguyên tem', 'source_ids':['DT-01'], 'source_review_note':'review'})
        case = await repo.get('regression_cases', r['id'])
        case['variations'] = ['zzunreachablezz']
        await repo.put('regression_cases', r['id'], case)
        await decide_revision(repo, 'reviewer', r['id'], r['content_hash'], 'approve', 'ok', True)
        with self.assertRaises(KnowledgeError):
            await prepare_release(repo, [r['id']], None, 'reviewer')

    async def test_first_release_can_roll_back_to_btc_only(self):
        from app.knowledge.releases import prepare_release, activate_release, rollback_release
        repo = await fixture()
        r = await approved(repo)
        release = await prepare_release(repo, [r['id']], None, 'reviewer')
        await activate_release(repo, release['id'], None, 'reviewer')
        await rollback_release(repo, 'btc-only', release['id'], 'reviewer')
        self.assertEqual((await repo.get('active', 'current'))['release_id'], 'btc-only')
        self.assertTrue(any(a['action']=='rollback_release' for a in await repo.rows('audit')))

    async def test_release_retries_are_idempotent_and_prepared_approval_is_locked(self):
        from app.knowledge.releases import prepare_release, activate_release
        from app.knowledge.revisions import decide_revision
        repo = await fixture()
        r = await approved(repo)
        a = await prepare_release(repo, [r['id']], None, 'reviewer')
        b = await prepare_release(repo, [r['id']], None, 'reviewer')
        self.assertEqual(a['id'], b['id'])
        with self.assertRaises(Conflict):
            await decide_revision(repo, 'reviewer', r['id'], r['content_hash'], 'reject', 'Changed mind', False)
        first = await activate_release(repo, a['id'], None, 'reviewer')
        second = await activate_release(repo, a['id'], None, 'reviewer')
        self.assertEqual(first, second)
        self.assertEqual(len([x for x in await repo.rows('audit') if x['action']=='activate_release']), 1)
