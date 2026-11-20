import asyncio
import json
from uuid import uuid4

import httpx
from pydantic import SecretStr
from unittest.mock import patch

from app.api.chat import get_harness
from app.main import app
from app.configs import get_settings


def test_stream_route_authentication_identity_framing_and_safe_errors():
    class Harness:
        fail = False
        calls = []

        async def stream(self, turn):
            self.calls.append(turn)
            yield {'event': 'delta', 'session_id': str(turn.session_id),
                   'client_msg_id': str(turn.client_msg_id), 'seq': 1, 'text': 'Xin tư vấn.\n'}
            if self.fail:
                raise RuntimeError('PRIVATE KEY 0901234567')
            yield {'event': 'done', 'session_id': str(turn.session_id),
                   'client_msg_id': str(turn.client_msg_id), 'agent_text': 'Xin tư vấn.\n'}

    async def run():
        harness = Harness()
        app.dependency_overrides[get_harness] = lambda: harness
        payload = {'client_msg_id': str(uuid4()), 'channel': 'hotline', 'channel_identity': '0900000000',
                   'on': '2026-11-17', 'text': 'Xin tư vấn', 'input_mode': 'clean'}
        headers = {'X-AI-Internal-Token': 'offline-api-token'}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
                denied = await client.post('/v1/chat/turns/stream', json=payload)
                assert denied.status_code == 401 and not harness.calls
                rejected = await client.post('/v1/chat/turns/stream', json={**payload, 'delivery_mode': 'voice'}, headers=headers)
                assert rejected.status_code == 422 and not harness.calls
                response = await client.post('/v1/chat/turns/stream', json=payload, headers=headers)
                assert response.status_code == 200
                assert response.headers['content-type'].startswith('application/x-ndjson')
                events = [json.loads(line) for line in response.text.splitlines()]
                assert [e['event'] for e in events] == ['delta', 'done']
                assert all(e['client_msg_id'] == payload['client_msg_id'] for e in events)
                assert events[0]['session_id'] == events[1]['session_id']
                assert events[0]['text'] == 'Xin tư vấn.\n'
                harness.fail = True
                response = await client.post('/v1/chat/turns/stream', json=payload, headers=headers)
                assert 'PRIVATE' not in response.text and '0901234567' not in response.text
                assert json.loads(response.text.splitlines()[-1])['event'] == 'error'
        finally:
            app.dependency_overrides.clear()
    with patch.object(get_settings(), 'ai_internal_token', SecretStr('offline-api-token')):
        asyncio.run(run())
