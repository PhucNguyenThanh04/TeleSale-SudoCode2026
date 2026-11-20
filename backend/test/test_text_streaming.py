import asyncio
import json
import threading
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.configs import VoiceSettings
from gateway_fixture import create_app
from test_text_gateway import START, preparation


def encoded(event):
    return (json.dumps(event, ensure_ascii=False) + '\n').encode()


def test_delta_reaches_browser_before_upstream_done_without_a_second_request():
    release = threading.Event()
    requests = []

    class Body(httpx.AsyncByteStream):
        def __init__(self, payload): self.payload = payload
        async def __aiter__(self):
            identity = {k: self.payload[k] for k in ('session_id', 'client_msg_id')}
            yield encoded({'event': 'delta', **identity, 'seq': 1, 'text': 'Đã kiểm tra. '})
            assert await asyncio.to_thread(release.wait, 5)
            yield encoded({'event': 'delta', **identity, 'seq': 2, 'text': 'Nội dung tiếp theo.'})
            yield encoded({'event': 'done', **identity, 'agent_text': 'Đã kiểm tra. Nội dung tiếp theo.',
                           'memory_update': {'turn_saved': True, 'status': 'completed'}})

    def handler(request):
        if request.url.path == '/v1/chat/sessions/prepare': return preparation(request)
        assert request.url.path == '/v1/chat/turns/stream'
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, stream=Body(payload), headers={'content-type': 'application/x-ndjson'})

    try:
        with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
            client.app.state.ai_http = httpx.AsyncClient(base_url='http://offline', transport=httpx.MockTransport(handler))
            with client.websocket_connect('/api/chat/stream') as socket:
                socket.send_json(START)
                assert socket.receive_json()['event'] == 'ready'
                msg_id = str(uuid4())
                socket.send_json({'event': 'text', 'client_msg_id': msg_id, 'text': 'Xin tư vấn'})
                first = socket.receive_json()
                assert first['event'] == 'agent_delta' and first['text'] == 'Đã kiểm tra. '
                assert first['client_msg_id'] == msg_id and not release.is_set()
                release.set()
                second = socket.receive_json()
                assert second['event'] == 'agent_delta'
                final = socket.receive_json()
                assert final['event'] == 'agent_reply'
                assert final['agent_text'] == first['text'] + second['text']
                assert len(requests) == 1
                socket.send_json({'event': 'end'})
    finally:
        release.set()


@pytest.mark.parametrize('fault', ['identity', 'sequence', 'missing_done', 'mismatched_done', 'upstream_error'])
def test_corrupt_or_truncated_stream_is_an_error_without_automatic_retry(fault):
    calls = []
    def handler(request):
        if request.url.path == '/v1/chat/sessions/prepare': return preparation(request)
        payload = json.loads(request.content)
        calls.append(payload)
        identity = {k: payload[k] for k in ('session_id', 'client_msg_id')}
        delta = {'event': 'delta', **identity, 'seq': 1, 'text': 'Đã kiểm tra.'}
        done = {'event': 'done', **identity, 'agent_text': delta['text'],
                'memory_update': {'turn_saved': True, 'status': 'completed'}}
        if fault == 'identity': delta['session_id'] = str(uuid4())
        if fault == 'sequence': delta['seq'] = 2
        if fault == 'mismatched_done': done['agent_text'] = 'OTHER UNCHECKED RESPONSE'
        frames = [delta] + ([] if fault == 'missing_done' else [done])
        if fault == 'upstream_error': frames = [{'event': 'error', **identity, 'code': 'PRIVATE 0901234567'}]
        return httpx.Response(200, content=b''.join(encoded(e) for e in frames),
                              headers={'content-type': 'application/x-ndjson'})

    with TestClient(create_app(VoiceSettings(_env_file=None))) as client:
        client.app.state.ai_http = httpx.AsyncClient(base_url='http://offline', transport=httpx.MockTransport(handler))
        with client.websocket_connect('/api/chat/stream') as socket:
            socket.send_json(START)
            socket.receive_json()
            socket.send_json({'event': 'text', 'client_msg_id': str(uuid4()), 'text': 'Xin tư vấn'})
            event = socket.receive_json()
            if event['event'] == 'agent_delta': event = socket.receive_json()
            assert event['event'] == 'error'
            assert 'PRIVATE' not in json.dumps(event) and '0901234567' not in json.dumps(event)
            assert len(calls) == 1
