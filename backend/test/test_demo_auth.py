import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.configs import VoiceSettings
from app.voice_main import create_app

SECRET = 'offline-test-secret-with-at-least-32-bytes'


@contextmanager
def gateway():
    app = create_app(VoiceSettings(_env_file=None, demo_jwt_secret=SECRET))
    from app.auth import password_hash
    users = {
        'one': dict(id='one', username='one', password_hash=password_hash.hash('password-one'),
                    customer_id='C1', name='Customer One', phone='0900000001', fb_id='fb1', zalo_id='z1', active=True),
        'two': dict(id='two', username='two', password_hash=password_hash.hash('password-two'),
                    customer_id='C2', name='Customer Two', phone='0900000002', fb_id='fb2', zalo_id='z2', active=True),
    }
    class Store:
        async def by_username(self, username):
            return users.get(username)
        async def by_id(self, user_id):
            return users.get(user_id)
    with TestClient(app) as client:
        client.app.state.demo_users = Store()
        yield client, users


def login(client, username='one', password='password-one'):
    return client.post('/api/auth/login', json={'username': username, 'password': password})


def test_login_cookie_me_bad_credentials_and_logout():
    with gateway() as (client, users):
        assert client.get('/api/auth/me').status_code == 401
        assert login(client, password='incorrect').status_code == 401
        assert login(client, username='missing').status_code == 401
        response = login(client)
        assert response.status_code == 200
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie
        assert 'password' not in response.text and 'token' not in response.text
        profile = client.get('/api/auth/me').json()
        assert profile['customer_id'] == 'C1'
        assert profile['identities'] == {'hotline': '0900000001', 'chat_fanpage': 'fb1', 'zalo_oa': 'z1'}
        assert client.post('/api/auth/logout').status_code == 204
        assert client.get('/api/auth/me').status_code == 401


@pytest.mark.parametrize('path', ['/api/chat/stream', '/api/calls/stream'])
def test_socket_requires_login_and_rejects_cross_origin(path):
    with gateway() as (client, _):
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path):
                pass
        assert error.value.code == 4401
        login(client)
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(path, headers={'origin': 'https://evil.example'}):
                pass
        assert error.value.code == 4403


@pytest.mark.parametrize('kind', ['expired', 'wrong_key', 'missing_exp', 'disabled'])
def test_invalid_token_or_disabled_account_is_rejected(kind):
    with gateway() as (client, users):
        claims = {'sub': 'one', 'iat': datetime.now(timezone.utc),
                  'exp': datetime.now(timezone.utc) + timedelta(minutes=5), 'iss': 'telesale-demo', 'aud': 'telesale-demo'}
        if kind == 'expired':
            claims['exp'] = datetime.now(timezone.utc) - timedelta(seconds=1)
        if kind == 'missing_exp':
            del claims['exp']
        if kind == 'disabled':
            users['one']['active'] = False
        token = jwt.encode(claims, SECRET if kind != 'wrong_key' else 'x' * 32, algorithm='HS256')
        client.cookies.set('demo_access', token)
        assert client.get('/api/auth/me').status_code == 401


def test_cookie_writes_require_same_origin_and_knowledge_requires_login():
    with gateway() as (client, _):
        assert client.get('/api/knowledge/gaps').status_code == 401
        assert client.post('/api/auth/login', headers={'origin': 'https://evil.example'},
                           json={'username': 'one', 'password': 'password-one'}).status_code == 403
        login(client)
        assert client.post('/api/auth/logout', headers={'origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/auth/me').status_code == 200


def test_two_simultaneous_text_sessions_bind_server_profiles():
    from test_text_gateway import streamed_response

    with gateway() as (client, _):
        turns = []
        def upstream(request):
            data = json.loads(request.content)
            if request.url.path.endswith('/prepare'):
                return httpx.Response(200, json={'session_id': data['session_id'], 'call_brief': None})
            turns.append(data)
            return streamed_response({'session_id': data['session_id'],
                'client_msg_id': data['client_msg_id'], 'agent_text': 'Dạ.'})
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(upstream))
        login(client)
        with client.websocket_connect('/api/chat/stream') as one:
            login(client, 'two', 'password-two')
            with client.websocket_connect('/api/chat/stream') as two:
                start = {'event': 'start', 'channel': 'hotline', 'channel_identity': 'forged', 'on': '2026-10-15'}
                one.send_json(start)
                two.send_json(start)
                first, second = one.receive_json(), two.receive_json()
                assert first['event'] == second['event'] == 'ready'
                assert first['session_id'] != second['session_id']
                for socket in (one, two):
                    socket.send_json({'event': 'text', 'client_msg_id': str(uuid4()), 'text': 'Hello'})
                    assert socket.receive_json()['event'] == 'agent_delta'
                    assert socket.receive_json()['agent_text'] == 'Dạ.'
                    socket.send_json({'event': 'end'})
        assert [(turn['session_id'], turn['channel_identity']) for turn in turns] == [
            (first['session_id'], '0900000001'), (second['session_id'], '0900000002')]


def test_voice_uses_assigned_profile_before_preparation():
    from test_voice_flow import Speech
    with gateway() as (client, _):
        prepared = []
        def upstream(request):
            payload = json.loads(request.content)
            prepared.append(payload)
            return httpx.Response(200, json={'session_id': payload['session_id']})
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(upstream))
        client.app.state.voice_speech = Speech()
        login(client)
        with client.websocket_connect('/api/calls/stream') as socket:
            socket.send_json({'event': 'start', 'channel': 'hotline', 'channel_identity': 'forged', 'on': '2026-10-15'})
            assert socket.receive_json()['event'] == 'ready'
            assert socket.receive_json()['event'] == 'state'
            socket.send_json({'event': 'end'})
            while socket.receive_json().get('state') != 'closed':
                pass
        assert prepared[0]['channel_identity'] == '0900000001'


@pytest.mark.parametrize('path', ['/api/chat/stream', '/api/calls/stream'])
def test_socket_expires_while_open(path):
    import time
    from app.auth import current_user
    from starlette.requests import HTTPConnection
    with gateway() as (client, users):
        async def almost_expired(connection: HTTPConnection):
            connection.state.auth_expires = time.time() + .1
            return users['one']
        client.app.dependency_overrides[current_user] = almost_expired
        with client.websocket_connect(path) as socket:
            with pytest.raises(WebSocketDisconnect) as error:
                while True:
                    socket.receive_json()
            assert error.value.code == 4401


@pytest.mark.parametrize('path', ['/api/chat/stream', '/api/calls/stream'])
def test_unsupported_channel_does_not_reach_ai(path):
    from test_voice_flow import Speech
    with gateway() as (client, _):
        def unexpected(request):
            pytest.fail('Unsupported profile channel reached the AI service')
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(unexpected))
        client.app.state.voice_speech = Speech()
        login(client)
        with client.websocket_connect(path) as socket:
            socket.send_json({'event': 'start', 'channel': 'web_chat', 'channel_identity': 'forged', 'on': '2026-10-15'})
            error = socket.receive_json()
            assert error['event'] == 'error' and error['fatal'] is True


def test_two_simultaneous_voice_sessions_keep_distinct_profiles():
    from test_voice_flow import Speech
    with gateway() as (client, _):
        prepared = []
        def upstream(request):
            payload = json.loads(request.content)
            prepared.append(payload)
            return httpx.Response(200, json={'session_id': payload['session_id']})
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(upstream))
        client.app.state.voice_speech = Speech()
        login(client)
        with client.websocket_connect('/api/calls/stream') as one:
            login(client, 'two', 'password-two')
            with client.websocket_connect('/api/calls/stream') as two:
                start = {'event': 'start', 'channel': 'hotline', 'channel_identity': 'forged', 'on': '2026-10-15'}
                for socket in (one, two):
                    socket.send_json(start)
                    assert socket.receive_json()['event'] == 'ready'
                    assert socket.receive_json()['state'] == 'listening'
                assert len(client.app.state.voice_speech.sockets) == 2
                for socket in (one, two):
                    socket.send_json({'event': 'end'})
                    while socket.receive_json().get('state') != 'closed':
                        pass
        assert {p['channel_identity'] for p in prepared} == {'0900000001', '0900000002'}
        assert len({p['session_id'] for p in prepared}) == 2
