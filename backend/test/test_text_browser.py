"""Real Chrome and text WebSocket; no model, speech service or database."""
import asyncio
from contextlib import asynccontextmanager
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.configs import VoiceSettings
from app.voice_main import create_app
from test_voice_browser import browser


@pytest.fixture
def text_site():
    calls = []

    async def handler(request):
        payload = json.loads(request.content)
        if request.url.path == '/v1/chat/sessions/prepare':
            return httpx.Response(200, json={'session_id': payload['session_id'],
                'call_brief': {'is_returning': True, 'n_previous_sessions': 1,
                    'products_advised': [{'sku': 'SKU-ASTER', 'price_quoted_vnd': 900000}]}})
        if request.url.path == '/v1/chat/turns/memory':
            return httpx.Response(200, json={'session_id': payload['session_id'],
                'client_msg_id': payload['client_msg_id'], 'memory_update': {
                    'turn_saved': True, 'status': 'completed', 'changes': [
                        {'field': 'budget_vnd', 'action': 'updated', 'value': 5000000}]}})
        assert request.url.path == '/v1/chat/turns'
        assert payload['delivery_mode'] == 'text'
        calls.append(payload)
        return httpx.Response(200, json={'session_id': payload['session_id'],
            'client_msg_id': payload['client_msg_id'], 'agent_text': 'Dạ <b>xin chào</b>',
            'call_brief': {'is_returning': True, 'n_previous_sessions': 1,
                'products_advised': [{'sku': 'SKU-ASTER', 'price_quoted_vnd': 900000}]},
            'memory_update': {'turn_saved': True, 'status': 'pending', 'changes': []}})

    app = create_app(VoiceSettings(_env_file=None))
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            async with httpx.AsyncClient(base_url='http://offline', transport=httpx.MockTransport(handler)) as http:
                app.state.ai_http = http
                yield

    app.router.lifespan_context = lifespan
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline
        time.sleep(.02)
    try:
        yield f'http://127.0.0.1:{port}/chat', calls
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_chat_shows_brief_and_real_memory_updates_without_microphone(text_site, browser):
    url, calls = text_site
    command, evaluate = browser
    command('Page.enable')
    command('Page.navigate', url=url)
    deadline = time.monotonic() + 10
    while not evaluate("!!document.querySelector('#scenario-date')?.value"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    evaluate("""window.waitFor = predicate => new Promise((resolve, reject) => {
      const started = Date.now(); const poll = () => {
        if (predicate()) resolve(true);
        else if (Date.now() - started > 5000) reject(Error(document.body.innerText));
        else setTimeout(poll, 20);
      }; poll();
    });
    navigator.mediaDevices.getUserMedia = () => { throw Error('Text must not use mic'); };
    document.querySelector('#identity').value = '0984726714';
    document.querySelector('#scenario-date').value = '2026-10-15';
    document.querySelector('#connect').click();
    waitFor(() => !document.querySelector('#send').disabled);
    """)
    assert evaluate("document.querySelectorAll('#brief .call-brief').length") == 1
    assert calls == []
    for count in (1, 2):
        evaluate("""document.querySelector('#text').value = '<img src=x onerror=alert(1)>';
          document.querySelector('#chat-form').requestSubmit();""")
        evaluate(f"waitFor(() => document.querySelectorAll('.message.agent').length === {count} && !document.querySelector('#send').disabled)")
    evaluate("waitFor(() => [...document.querySelectorAll('.memory-update')].every(p => p.dataset.status === 'completed'))")
    assert evaluate("document.querySelectorAll('#brief .call-brief').length") == 1
    assert 'Giá lịch sử: 900.000' in evaluate("document.querySelector('#brief').innerText")
    assert '5.000.000' in evaluate("document.querySelector('.memory-update').innerText")
    assert evaluate("document.querySelectorAll('#messages img, #messages b').length") == 0
    assert calls[0]['session_id'] == calls[1]['session_id']
    evaluate("document.querySelector('#end').click(); waitFor(() => !document.querySelector('#connect').disabled)")
    evaluate("document.querySelector('#connect').click(); waitFor(() => !document.querySelector('#send').disabled)")
    evaluate("document.querySelector('#text').value = 'Gọi lại'; document.querySelector('#chat-form').requestSubmit();")
    evaluate("waitFor(() => !document.querySelector('#send').disabled)")
    assert calls[-1]['session_id'] != calls[0]['session_id']
