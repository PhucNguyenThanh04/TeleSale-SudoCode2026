import unittest
from test_knowledge_revisions import fixture
from test_knowledge_releases import approved


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_supplement_requires_valid_order_date_and_source(self):
        from app.knowledge.releases import prepare_release, activate_release
        from app.knowledge.retrieval import supplement_candidates
        repo = await fixture()
        r = await approved(repo)
        release = await prepare_release(repo, [r['id']], None, 'reviewer')
        await activate_release(repo, release['id'], None, 'reviewer')
        async with repo.transaction() as tx:
            no_date = await supplement_candidates(tx, release['id'], '2026-10-15', None)
            before = await supplement_candidates(tx, release['id'], '2026-10-15', '2026-09-30')
            valid = await supplement_candidates(tx, release['id'], '2026-10-15', '2026-10-01')
        self.assertEqual(no_date, [])
        self.assertEqual(before, [])
        self.assertTrue(valid[0]['chunk_id'].startswith('KG-'))
        self.assertEqual(valid[0]['source_chunk_ids'], ['DT-01'])
        repo.source_rows['DT-01']['access_level'] = 'internal'
        async with repo.transaction() as tx:
            self.assertEqual(await supplement_candidates(tx, release['id'], '2026-10-15', '2026-10-01'), [])

    async def test_pin_does_not_follow_active_pointer(self):
        from app.knowledge.releases import prepare_release, activate_release
        from app.knowledge.run_context import release_context, selected_release
        repo = await fixture()
        first = await prepare_release(repo, [(await approved(repo))['id']], None, 'reviewer')
        await activate_release(repo, first['id'], None, 'reviewer')
        with release_context(first['id']):
            second = await prepare_release(repo, [(await approved(repo, 'Question two'))['id']], first['id'], 'reviewer')
            await activate_release(repo, second['id'], first['id'], 'reviewer')
            self.assertEqual(selected_release(), first['id'])
        self.assertIsNone(selected_release())

    async def test_gateway_strips_model_release_and_injects_trusted_pin(self):
        from fastmcp import FastMCP
        from app.agent.mcp.gateway import MCPGateway
        from app.knowledge.run_context import release_context
        server = FastMCP('knowledge-test')
        @server.tool(name='policy.search')
        async def search(query: str, on: str, knowledge_release_id: str | None = None):
            return {'release': knowledge_release_id}
        gateway = MCPGateway(server, None, None)
        with release_context('trusted'):
            result = await gateway.invoke('policy.search', {'query': 'đổi', 'on': '2026-10-15',
                                                           'knowledge_release_id': 'forged'})
        self.assertEqual(result['release'], 'trusted')
