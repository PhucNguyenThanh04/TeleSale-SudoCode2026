"""Playback receipts are an authenticated backend-only operation."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
import httpx
from pydantic import SecretStr

from app.api.chat import get_harness, router
from app.schemas.agent import MemoryUpdate


class VoicePlaybackApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_token_validation_and_receipt_conflicts(self):
        calls = []
        class Harness:
            async def record_playback(self, request):
                calls.append(request)
                if request.played_chars == 999:
                    raise ValueError('private identity detail')
                return MemoryUpdate(turn_saved=True, status='pending')
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_harness] = lambda: Harness()
        payload = {'session_id': '11111111-1111-4111-8111-111111111111',
                   'client_msg_id': '22222222-2222-4222-8222-222222222222',
                   'channel': 'web_chat', 'channel_identity': 'customer', 'on': '2026-11-08',
                   'played_chars': 9, 'interrupted': True}
        with patch('app.api.chat.get_settings', return_value=SimpleNamespace(ai_internal_token=SecretStr('test'))):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                endpoint = '/v1/chat/turns/playback'
                assert (await client.post(endpoint, json=payload)).status_code == 401
                assert calls == []
                headers = {'X-AI-Internal-Token': 'test'}
                response = await client.post(endpoint, json=payload, headers=headers)
                assert response.status_code == 200
                assert response.json()['memory_update']['turn_saved'] is True
                assert response.json()['client_msg_id'] == payload['client_msg_id']
                invalid = await client.post(endpoint, json=payload | {'played_chars': -1}, headers=headers)
                assert invalid.status_code == 422
                conflict = await client.post(endpoint, json=payload | {'played_chars': 999}, headers=headers)
                assert conflict.status_code == 409 and 'private' not in conflict.text
