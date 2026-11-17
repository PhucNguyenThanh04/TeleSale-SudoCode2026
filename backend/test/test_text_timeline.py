import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.configs import VoiceSettings
from app.voice_main import create_app as production_app
from gateway_fixture import USER, create_app


def query():
    return {'session_id': str(uuid4()), 'channel': 'hotline', 'on': '2026-10-15', 'offset': 0, 'limit': 10}


def response(payload):
    return {'session_id': payload['session_id'], 'timeline': {'status':'available', 'items':[
        {'session_id':'past','on':'2026-10-10','channel':'zalo_oa','summary':'Khách cần hỏi người nhà',
         'outcome':'hen_goi_lai','summary_status':'ready'}], 'offset':0,'limit':10,'total':1,'next_offset':None}}


def test_timeline_is_cookie_authenticated_before_any_ai_request():
    with TestClient(production_app(VoiceSettings(_env_file=None,
                    demo_jwt_secret='offline-auth-secret-with-at-least-32-bytes'))) as client:
        result = client.post('/api/chat/timeline', json=query())
        assert result.status_code == 401


def test_timeline_binds_identity_to_account_and_preserves_page_without_model():
    calls = []
    def handler(request):
        assert request.url.path == '/v1/chat/sessions/timeline'
        assert request.headers['X-AI-Internal-Token'] == 'internal-only'
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(200, json=response(payload))
    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai',
            headers={'X-AI-Internal-Token':'internal-only'}, transport=httpx.MockTransport(handler))
        payload = query()
        result = client.post('/api/chat/timeline', json=payload)
        assert result.status_code == 200
        assert result.json()['timeline']['items'][0]['channel'] == 'zalo_oa'
        assert result.headers['cache-control'] == 'no-store'
        assert calls == [payload | {'channel_identity': USER['phone']}]
        for injected in ({'customer_id':'OTHER'}, {'channel_identity':'OTHER'},
                         {'verified_customer_id':'OTHER'}, {'crm_sessions':[]}):
            assert client.post('/api/chat/timeline', json=payload|injected).status_code == 422
        assert len(calls) == 1


@pytest.mark.parametrize('bad', ['wrong_session','malformed','bad_page','error'])
def test_timeline_upstream_failure_is_safe_and_cannot_show_other_history(bad):
    def handler(request):
        payload = json.loads(request.content)
        value = response(payload)
        if bad == 'wrong_session': value['session_id'] = str(uuid4())
        if bad == 'malformed': value['timeline']['items'] = 'PRIVATE 0901234567'
        if bad == 'bad_page': value['timeline']['next_offset'] = 0
        if bad == 'error': return httpx.Response(503, text='PRIVATE 0901234567')
        return httpx.Response(200, json=value)
    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(handler))
        result = client.post('/api/chat/timeline', json=query())
        assert result.status_code == 503
        assert 'PRIVATE' not in result.text and '0901234567' not in result.text


def test_bad_pagination_is_rejected_before_upstream():
    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        for values in ({'limit':21}, {'offset':-1}, {'limit':True}):
            assert client.post('/api/chat/timeline', json=query()|values).status_code == 422
