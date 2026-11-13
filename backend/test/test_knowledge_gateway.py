"""Admin access and server-bound identity; upstream is an offline transport."""
import json
import httpx
from fastapi.testclient import TestClient
from app.configs import VoiceSettings
from gateway_fixture import create_app


def app_config(**changes):
    return VoiceSettings(_env_file=None, knowledge_reviewer_id='reviewer-1', **changes)


def test_missing_reviewer_never_calls_upstream():
    with TestClient(create_app(VoiceSettings(_env_file=None, knowledge_reviewer_id=''))) as client:
        assert client.get('/api/knowledge/gaps').status_code == 503
        assert client.get('/knowledge').status_code == 200


def test_proxy_binds_actor_and_keeps_internal_token_off_browser():
    seen = []
    def handler(request):
        assert request.headers['X-AI-Internal-Token'] == 'server-secret'
        seen.append(request)
        return httpx.Response(200, json={'items': [], 'total': 0, 'active_release_id': None})
    with TestClient(create_app(app_config())) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', headers={
            'X-AI-Internal-Token': 'server-secret'}, transport=httpx.MockTransport(handler))
        headers = {}
        response = client.get('/api/knowledge/revisions?gap_id=G1&offset=30&actor_id=attacker', headers=headers)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert seen[-1].url.params['actor_id'] == 'reviewer-1'
        assert seen[-1].url.params['gap_id'] == 'G1'
        assert 'server-secret' not in response.text
        assert client.get('/api/knowledge/permissions', headers=headers).status_code == 404
        response = client.post('/api/knowledge/commands', headers=headers, json={
            'actor_id': 'attacker', 'action': 'approve', 'payload': {}})
        assert response.status_code == 422
        response = client.post('/api/knowledge/commands', headers={**headers, 'Origin': 'http://evil'}, json={
            'action': 'approve', 'payload': {}})
        assert response.status_code == 403
        response = client.post('/api/knowledge/commands', headers=headers, json={
            'action': 'approve', 'payload': {'id': 'R1', 'content_hash': 'hash', 'approve_test': True, 'reason': 'Đã đọc'}})
        assert response.status_code == 200
        body = json.loads(seen[-1].content)
        assert body['actor_id'] == 'reviewer-1' and body['payload']['content_hash'] == 'hash'


def test_upstream_errors_preserve_actionable_status_without_raw_content():
    with TestClient(create_app(app_config())) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(
            lambda request: httpx.Response(409, text='server-secret private body')))
        response = client.get('/api/knowledge/gaps')
        assert response.status_code == 409
        assert 'server-secret' not in response.text


def test_proxy_timeout_and_command_allowlist():
    def handler(request):
        raise httpx.ReadTimeout('private server-secret', request=request)
    with TestClient(create_app(app_config())) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(handler))
        headers = {}
        assert client.post('/api/knowledge/commands', headers=headers, json={'action':'grant','payload':{}}).status_code == 422
        response = client.get('/api/knowledge/gaps', headers=headers)
        assert response.status_code == 502 and 'server-secret' not in response.text


def test_default_reviewer_access_needs_no_browser_token():
    with TestClient(create_app(VoiceSettings(_env_file=None, ai_internal_token='server-secret'))) as client:
        def handler(request):
            assert request.url.params['actor_id'] == 'local-reviewer'
            assert request.headers['X-AI-Internal-Token'] == 'server-secret'
            assert 'Authorization' not in request.headers
            return httpx.Response(200, json={'items': [], 'total': 0})
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai',
            headers={'X-AI-Internal-Token': 'server-secret'}, transport=httpx.MockTransport(handler))
        assert client.get('/api/knowledge/gaps').status_code == 200
