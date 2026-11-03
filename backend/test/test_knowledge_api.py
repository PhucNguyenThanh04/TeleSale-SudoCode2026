import unittest
from unittest.mock import AsyncMock
import httpx
from app.main import app
from app.api.deps import get_current_user_id, get_ai_http


class KnowledgeApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_visitor_cannot_query_or_mutate_knowledge(self):
        from app.api.knowledge import router
        app.dependency_overrides[get_current_user_id] = lambda: 'web-visitor:fake'
        app.dependency_overrides[get_ai_http] = lambda: AsyncMock()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
                self.assertEqual((await c.get('/api/knowledge/gaps')).status_code, 403)
                self.assertEqual((await c.post('/api/knowledge/commands', json={
                    'action': 'approve', 'payload': {}, 'actor_id': 'reviewer'})).status_code, 403)
        finally:
            app.dependency_overrides.clear()

    async def test_server_actor_overrides_forged_client_actor(self):
        from app.api.knowledge import router
        ai = AsyncMock()
        ai.post.return_value = httpx.Response(200, json={'status': 'approved'}, request=httpx.Request('POST', 'http://ai'))
        app.dependency_overrides[get_current_user_id] = lambda: 'staff'
        app.dependency_overrides[get_ai_http] = lambda: ai
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
                response = await c.post('/api/knowledge/commands', json={
                    'action': 'approve', 'payload': {}, 'actor_id': 'forged'})
                self.assertEqual(response.status_code, 200)
            self.assertEqual(ai.post.call_args.kwargs['json']['actor_id'], 'staff')
        finally:
            app.dependency_overrides.clear()
