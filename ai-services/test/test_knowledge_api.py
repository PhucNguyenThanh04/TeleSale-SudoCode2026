import unittest
import httpx
from app.main import app
from app.configs import get_settings
from test_knowledge_revisions import fixture


class KnowledgeApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_revision_filter_is_applied_before_pagination(self):
        from app.api.knowledge import get_knowledge_repo
        repo = await fixture()
        async with repo.transaction() as tx:
            await tx.put('revisions', 'r1', {'id': 'r1', 'gap_id': 'g'})
            await tx.put('revisions', 'r2', {'id': 'r2', 'gap_id': 'other'})
        app.dependency_overrides[get_knowledge_repo] = lambda: repo
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await client.get('/v1/knowledge/revisions', params={
                    'actor_id': 'reviewer', 'gap_id': 'g', 'limit': 1}, headers={
                    'X-AI-Internal-Token': get_settings().ai_internal_token.get_secret_value()})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['total'], 1)
            self.assertEqual(response.json()['items'][0]['id'], 'r1')
        finally:
            app.dependency_overrides.clear()

    async def test_internal_token_and_reviewer_required(self):
        from app.api.knowledge import get_knowledge_repo
        repo = await fixture()
        app.dependency_overrides[get_knowledge_repo] = lambda: repo
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                self.assertEqual((await client.get('/v1/knowledge/gaps', params={'actor_id': 'reviewer'})).status_code, 401)
                headers = {'X-AI-Internal-Token': get_settings().ai_internal_token.get_secret_value()}
                denied = await client.get('/v1/knowledge/gaps', params={'actor_id': 'web-visitor:bad'}, headers=headers)
                self.assertEqual(denied.status_code, 403)
                allowed = await client.get('/v1/knowledge/gaps', params={'actor_id': 'reviewer'}, headers=headers)
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(allowed.json()['items'][0]['id'], 'g')
        finally:
            app.dependency_overrides.clear()

    async def test_unsupported_command_and_stale_version(self):
        from app.api.knowledge import get_knowledge_repo
        repo = await fixture()
        app.dependency_overrides[get_knowledge_repo] = lambda: repo
        headers = {'X-AI-Internal-Token': get_settings().ai_internal_token.get_secret_value()}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                result = await client.post('/v1/knowledge/commands', headers=headers, json={
                    'actor_id': 'reviewer', 'action': 'classify', 'payload': {'id': 'g',
                        'version': 0, 'category': 'content', 'reason': 'review'}})
                self.assertEqual(result.status_code, 409)
        finally:
            app.dependency_overrides.clear()
