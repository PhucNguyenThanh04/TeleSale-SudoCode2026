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
from app.auth import password_hash
from gateway_fixture import USER
from test_voice_browser import browser
from test_text_gateway import streamed_response


@pytest.fixture
def text_site():
    calls = []
    timeline = {'fail': False, 'status': 'available', 'queries': [], 'items': [
        {'session_id': f'past-{n}', 'on': f'2026-10-{n:02}',
         'channel': 'zalo_oa' if n % 2 else 'hotline',
         'summary': 'Khách <img src=x onerror=alert(1)> cần hỏi người nhà' if n == 12 else f'Tư vấn lần {n}',
         'outcome': 'hen_goi_lai', 'summary_status': 'ready'} for n in range(12, 0, -1)]}

    async def handler(request):
        payload = json.loads(request.content)
        if request.url.path == '/v1/chat/sessions/timeline':
            timeline['queries'].append(payload)
            if timeline['fail']:
                return httpx.Response(503, text='PRIVATE UPSTREAM ERROR')
            items = timeline['items'] if timeline['status'] == 'available' else []
            offset, limit = payload['offset'], payload['limit']
            end = min(offset + limit, len(items))
            return httpx.Response(200, json={'session_id': payload['session_id'], 'timeline': {
                'status': timeline['status'], 'items': items[offset:end], 'offset': offset,
                'limit': limit, 'total': len(items), 'next_offset': end if end < len(items) else None}})
        if request.url.path == '/v1/chat/sessions/prepare':
            return httpx.Response(200, json={'session_id': payload['session_id'],
                'call_brief': {'is_returning': True, 'n_previous_sessions': 1,
                    'products_advised': [{'sku': 'SKU-ASTER', 'price_quoted_vnd': 900000}]}})
        if request.url.path == '/v1/chat/turns/memory':
            return httpx.Response(200, json={'session_id': payload['session_id'],
                'client_msg_id': payload['client_msg_id'], 'memory_update': {
                    'turn_saved': True, 'status': 'completed', 'changes': [
                        {'field': 'budget_vnd', 'action': 'updated', 'value': 5000000}]}})
        assert request.url.path == '/v1/chat/turns/stream'
        assert payload['delivery_mode'] == 'text'
        calls.append(payload)
        if timeline.get('stream_gate') is not None:
            class Body(httpx.AsyncByteStream):
                async def __aiter__(self):
                    identity = {k: payload[k] for k in ('session_id', 'client_msg_id')}
                    first = 'Đã kiểm tra <img src=x onerror=alert(1)>.'
                    yield (json.dumps({'event':'delta', **identity, 'seq':1, 'text':first})+'\n').encode()
                    assert await asyncio.to_thread(timeline['stream_gate'].wait, 10)
                    if timeline.get('stream_truncated'):
                        return
                    suffix = ' Mình cần thêm thông tin nào?'
                    yield (json.dumps({'event':'delta', **identity, 'seq':2, 'text':suffix})+'\n').encode()
                    yield (json.dumps({'event':'done', **identity, 'agent_text':first+suffix,
                        'memory_update':{'turn_saved':True, 'status':'completed'}})+'\n').encode()
            return httpx.Response(200, stream=Body(), headers={'content-type':'application/x-ndjson'})
        return streamed_response({'session_id': payload['session_id'],
            'client_msg_id': payload['client_msg_id'], 'agent_text': 'Dạ <b>xin chào</b>',
            'call_brief': {'is_returning': True, 'n_previous_sessions': 1,
                'products_advised': [{'sku': 'SKU-ASTER', 'price_quoted_vnd': 900000}]},
            'memory_update': {'turn_saved': True, 'status': 'pending', 'changes': []}})

    app = create_app(VoiceSettings(_env_file=None, demo_jwt_secret='offline-browser-secret-with-at-least-32-bytes'))
    user = {**USER, 'password_hash': password_hash.hash('browser-password')}
    class Store:
        async def by_username(self, username):
            return user if username == 'offline' else None
        async def by_id(self, user_id):
            return user if user_id == user['id'] else None
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            app.state.demo_users = Store()
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
        yield f'http://127.0.0.1:{port}/chat', calls, timeline
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_chat_shows_brief_and_real_memory_updates_without_microphone(text_site, browser):
    url, calls, _ = text_site
    command, evaluate = browser
    command('Page.enable')
    command('Page.navigate', url=url)
    deadline = time.monotonic() + 10
    while not evaluate("!!document.querySelector('#login-form')"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    evaluate("document.querySelector('#username').value='offline'; document.querySelector('#password').value='browser-password'; document.querySelector('#login-form').requestSubmit()")
    while not evaluate("!!document.querySelector('#identity')?.readOnly"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    assert evaluate("document.cookie.includes('demo_access')") is False
    command('Page.navigate', url=url)
    deadline = time.monotonic() + 10
    while not evaluate("!!document.querySelector('#identity')?.readOnly"):
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

    evaluate("[...document.querySelectorAll('header button')].find(b => b.textContent === 'Đăng xuất').click()")
    deadline = time.monotonic() + 10
    while not evaluate("!!document.querySelector('#login-form')"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    assert evaluate("fetch('/api/auth/me').then(r => r.status)") == 401


def open_text_timeline(text_site, browser):
    url, calls, timeline = text_site
    command, evaluate = browser
    command('Network.enable')
    command('Network.setBlockedURLs', urls=['https://*'])
    command('Page.enable')
    command('Page.navigate', url=url)
    deadline = time.monotonic() + 10
    while not evaluate("!!document.querySelector('#login-form')"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    evaluate("document.querySelector('#username').value='offline'; document.querySelector('#password').value='browser-password'; document.querySelector('#login-form').requestSubmit()")
    while not evaluate("!!document.querySelector('#identity')?.readOnly"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    command('Page.navigate', url=url)
    while not evaluate("!!document.querySelector('#timeline-items') && !!document.querySelector('#identity')?.readOnly"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    evaluate("""window.waitFor = predicate => new Promise((resolve, reject) => {
      const started = Date.now(); const poll = () => {
        if (predicate()) resolve(true);
        else if (Date.now() - started > 5000) reject(Error(document.body.innerText));
        else setTimeout(poll, 20);
      }; poll();
    }); document.querySelector('#scenario-date').value='2026-10-15';""")
    assert evaluate("!!document.querySelector('#timeline-items')")
    evaluate("document.querySelector('#connect').click(); waitFor(() => !document.querySelector('#send').disabled)")
    return command, evaluate, calls, timeline


def test_timeline_browser_pages_refreshes_cross_channel_and_survives_reload(text_site, browser, tmp_path):
    command, js, calls, timeline = open_text_timeline(text_site, browser)
    js("waitFor(() => document.querySelectorAll('#timeline-items li').length === 10)")
    assert js("""(() => {
      const panel = document.querySelector('#timeline-panel').getBoundingClientRect();
      const container = document.querySelector('.conversation').getBoundingClientRect();
      return panel.bottom <= container.bottom && panel.width >= container.width - 40;
    })()""")
    assert calls == []
    assert 'Zalo OA' in js("document.querySelector('#timeline-items').innerText")
    assert js("document.querySelectorAll('#timeline-items img').length") == 0
    js("document.querySelector('#timeline-more').click(); waitFor(() => document.querySelectorAll('#timeline-items li').length === 12)")
    assert js("document.querySelector('#timeline-more').hidden")
    timeline['items'][0]['summary'] = 'Đã cập nhật sau lượt chat'
    js("document.querySelector('#text').value='Xin tư vấn'; document.querySelector('#chat-form').requestSubmit(); waitFor(() => document.querySelector('#timeline-items').innerText.includes('Đã cập nhật sau lượt chat'))")
    assert len(calls) == 1
    old_session = timeline['queries'][-1]['session_id']
    js("document.querySelector('#end').click(); waitFor(() => !document.querySelector('#connect').disabled)")
    js("document.querySelector('#channel').value='zalo_oa'; document.querySelector('#channel').dispatchEvent(new Event('change')); document.querySelector('#connect').click(); waitFor(() => document.querySelectorAll('#timeline-items li').length === 10)")
    assert timeline['queries'][-1]['session_id'] != old_session
    assert timeline['queries'][-1]['channel_identity'] == USER['zalo_id']
    assert len(calls) == 1
    command('Page.navigate', url=text_site[0])
    deadline = time.monotonic() + 5
    while not js("!!document.querySelector('#identity')?.readOnly"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    js("document.querySelector('#scenario-date').value='2026-10-15'; document.querySelector('#connect').click()")
    deadline = time.monotonic() + 5
    while not js("document.querySelectorAll('#timeline-items li').length === 10"):
        assert time.monotonic() < deadline
        time.sleep(.02)
    assert 'Đã cập nhật sau lượt chat' in js("document.querySelector('#timeline-items').innerText")
    import base64
    (tmp_path/'timeline.png').write_bytes(base64.b64decode(command('Page.captureScreenshot', captureBeyondViewport=True)['data']))


def test_browser_displays_a_delta_before_done_in_one_safe_bubble(text_site, browser):
    gate = threading.Event()
    text_site[2]['stream_gate'] = gate
    try:
        _, js, calls, _ = open_text_timeline(text_site, browser)
        js("document.querySelector('#text').value='Xin tư vấn'; document.querySelector('#chat-form').requestSubmit(); waitFor(() => document.querySelector('.message.agent p')?.textContent.includes('Đã kiểm tra'))")
        assert not gate.is_set()
        assert js("document.querySelector('#send').disabled") is True
        assert js("document.querySelectorAll('.message.agent').length") == 1
        assert js("document.querySelectorAll('#messages img').length") == 0
        gate.set()
        js("waitFor(() => !document.querySelector('#send').disabled)")
        assert js("document.querySelectorAll('.message.agent').length") == 1
        assert 'Mình cần thêm thông tin nào?' in js("document.querySelector('.message.agent p').textContent")
        assert len(calls) == 1
    finally:
        gate.set()


def test_browser_preserves_partial_text_and_reports_interrupted_stream(text_site, browser):
    gate = threading.Event()
    text_site[2].update(stream_gate=gate, stream_truncated=True)
    try:
        _, js, calls, _ = open_text_timeline(text_site, browser)
        js("document.querySelector('#text').value='Xin tư vấn'; document.querySelector('#chat-form').requestSubmit(); waitFor(() => !!document.querySelector('.message.agent'))")
        gate.set()
        js("waitFor(() => !document.querySelector('#send').disabled)")
        assert 'Phản hồi bị ngắt' in js("document.querySelector('#error').textContent")
        assert 'Đã kiểm tra' in js("document.querySelector('.message.agent p').textContent")
        assert js("document.querySelectorAll('.message.agent').length") == 1
        assert len(calls) == 1
    finally:
        gate.set()


def test_timeline_browser_error_retry_empty_and_stale_response(text_site, browser):
    text_site[2]['fail'] = True
    _, js, calls, timeline = open_text_timeline(text_site, browser)
    js("waitFor(() => document.querySelector('#timeline-status').textContent.includes('Chưa tải được'))")
    assert js("document.querySelectorAll('#timeline-items li').length") == 0
    assert js("document.querySelector('#send').disabled") is False
    timeline['fail'] = False
    js("document.querySelector('#timeline-reload').click(); waitFor(() => document.querySelectorAll('#timeline-items li').length === 10)")
    js("""const originalFetch = window.fetch; let holdOnce = true;
      window.fetch = (url, options) => {
        if (url === '/api/chat/timeline' && holdOnce) {
          holdOnce = false; const request = JSON.parse(options.body);
          return new Promise(resolve => window.releaseOldTimeline = () => resolve(new Response(JSON.stringify({
            session_id: request.session_id, timeline: {status:'available',offset:0,limit:10,total:1,next_offset:null,
              items:[{session_id:'old',on:'2026-10-01',channel:'hotline',summary:'STALE_OLD_SESSION',outcome:'khac',summary_status:'ready'}]}
          }), {status:200})));
        }
        return originalFetch(url, options);
      }; document.querySelector('#timeline-reload').click(); waitFor(() => !!window.releaseOldTimeline);""")
    js("document.querySelector('#text').value='Chat khi lịch sử đang tải'; document.querySelector('#chat-form').requestSubmit(); waitFor(() => document.querySelectorAll('.message.agent').length === 1 && !document.querySelector('#send').disabled)")
    assert len(calls) == 1
    js("""(async () => {
      document.querySelector('#end').click();
      await waitFor(() => !document.querySelector('#connect').disabled);
      document.querySelector('#connect').click();
      await waitFor(() => document.querySelectorAll('#timeline-items li').length === 10);
    })()""")
    js("releaseOldTimeline(); new Promise(resolve => setTimeout(resolve,100))")
    assert 'STALE_OLD_SESSION' not in js("document.querySelector('#timeline-items').innerText")
    timeline['status'] = 'not_applicable'
    js("document.querySelector('#timeline-reload').click(); waitFor(() => document.querySelector('#timeline-status').textContent.includes('Chưa xác minh'))")
    assert js("document.querySelectorAll('#timeline-items li').length") == 0
    timeline['status'], timeline['items'] = 'available', []
    js("document.querySelector('#timeline-reload').click(); waitFor(() => document.querySelector('#timeline-status').textContent.includes('Chưa có tương tác'))")
    assert len(calls) == 1
