import json
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.configs import VoiceSettings
from gateway_fixture import create_app


START = {'event': 'start', 'channel': 'hotline', 'channel_identity': '0984726714', 'on': '2026-10-15'}


def preparation(request):
    payload = json.loads(request.content)
    return httpx.Response(200, json={'session_id': payload['session_id'],
        'call_brief': {'is_returning': True, 'n_previous_sessions': 1}})


def streamed_response(body):
    identity = {k: body[k] for k in ('session_id', 'client_msg_id')}
    events = [{'event': 'delta', **identity, 'seq': 1, 'text': body['agent_text']},
              {'event': 'done', **body}]
    return httpx.Response(200, content=''.join(json.dumps(e) + '\n' for e in events),
                          headers={'content-type': 'application/x-ndjson'})


def test_text_page_and_asset_are_served():
    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        page = client.get('/chat')
        assert page.status_code == 200
        assert 'id="chat-form"' in page.text
        assert 'id="messages"' in page.text
        assert client.get('/assets/chat.js').status_code == 200


def test_text_socket_keeps_session_identity_and_forwards_memory_without_playback():
    calls = []
    ids = [str(uuid4()), str(uuid4())]

    def handler(request):
        assert request.headers['X-AI-Internal-Token'] == 'internal-only'
        if request.url.path == '/v1/chat/sessions/prepare':
            return preparation(request)
        payload = json.loads(request.content)
        calls.append(payload)
        assert request.url.path == '/v1/chat/turns/stream'
        assert payload['delivery_mode'] == 'text'
        assert payload['channel_identity'] == START['channel_identity']
        return streamed_response({'session_id': payload['session_id'],
            'client_msg_id': payload['client_msg_id'], 'agent_text': 'Dạ.',
            'call_brief': {'is_returning': True, 'n_previous_sessions': 1},
            'memory_update': {'turn_saved': True, 'status': 'completed', 'changes': []}})

    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai',
            headers={'X-AI-Internal-Token': 'internal-only'}, transport=httpx.MockTransport(handler))
        with client.websocket_connect('/api/chat/stream') as socket:
            socket.send_json(START)
            ready = socket.receive_json()
            assert ready['event'] == 'ready' and ready['call_brief']['is_returning'] is True
            assert calls == []
            for msg_id in ids:
                socket.send_json({'event': 'text', 'client_msg_id': msg_id, 'text': 'Xin chào'})
                assert socket.receive_json()['event'] == 'agent_delta'
                reply = socket.receive_json()
                assert reply['event'] == 'agent_reply'
                assert reply['client_msg_id'] == msg_id
                assert reply['memory_update']['status'] == 'completed'
                assert reply['call_brief']['is_returning'] is True
            socket.send_json({'event': 'end'})
        assert calls[0]['session_id'] == calls[1]['session_id']


def test_browser_cannot_change_identity_or_inject_verified_customer():
    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(preparation))
        with client.websocket_connect('/api/chat/stream') as socket:
            socket.send_json(START)
            assert socket.receive_json()['event'] == 'ready'
            socket.send_json({'event': 'text', 'client_msg_id': str(uuid4()), 'text': 'Hello',
                              'verified_customer_id': 'OTHER'})
            error = socket.receive_json()
            assert error['event'] == 'error'
            assert error['code'] == 'invalid_text_command'


def test_upstream_failure_is_safe_and_never_becomes_an_agent_reply():
    def handler(request):
        if request.url.path == '/v1/chat/sessions/prepare':
            return preparation(request)
        return httpx.Response(400, text='private upstream 0901234567')

    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(handler))
        with client.websocket_connect('/api/chat/stream') as socket:
            socket.send_json(START)
            socket.receive_json()
            socket.send_json({'event': 'text', 'client_msg_id': str(uuid4()), 'text': 'Hello'})
            error = socket.receive_json()
            assert error['event'] == 'error'
            assert '0901234567' not in json.dumps(error)


def test_wrong_response_identity_is_not_sent_to_browser():
    def handler(request):
        if request.url.path == '/v1/chat/sessions/prepare':
            return preparation(request)
        payload = json.loads(request.content)
        return streamed_response({'session_id': str(uuid4()),
            'client_msg_id': payload['client_msg_id'], 'agent_text': 'Other customer'})

    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(handler))
        with client.websocket_connect('/api/chat/stream') as socket:
            socket.send_json(START)
            socket.receive_json()
            socket.send_json({'event': 'text', 'client_msg_id': str(uuid4()), 'text': 'Hello'})
            assert socket.receive_json()['code'] == 'harness_failed'


def test_malformed_memory_result_does_not_crash_the_text_connection():
    def handler(request):
        if request.url.path == '/v1/chat/sessions/prepare':
            return preparation(request)
        payload = json.loads(request.content)
        return streamed_response({'session_id': payload['session_id'],
            'client_msg_id': payload['client_msg_id'], 'agent_text': 'Dạ.',
            'memory_update': 'invalid'})

    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://ai', transport=httpx.MockTransport(handler))
        with client.websocket_connect('/api/chat/stream') as socket:
            socket.send_json(START)
            socket.receive_json()
            socket.send_json({'event': 'text', 'client_msg_id': str(uuid4()), 'text': 'Hello'})
            assert socket.receive_json()['event'] == 'agent_delta'
            assert socket.receive_json()['code'] == 'harness_failed'
