"""Headless Chrome + real AudioWorklet/WebSocket, offline speech/agent doubles."""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import httpx
import pytest
import uvicorn
from websockets.sync.client import connect

from app.configs import VoiceSettings
from gateway_fixture import create_app
from test_voice_flow import Speech


@pytest.fixture
def site():
    requests = []
    options = {"tts_error": False, "agent_error": False, "wait_agent": False,
               "memory_status": None, "memory_changes": [], "tts_samples": 1600,
               "playback_receipts": []}
    speech = Speech()

    async def listen():
        from test_voice_flow import ListenSocket
        connection = ListenSocket()
        speech.sockets.append(connection)
        original = connection.send

        async def send(audio):
            await original(audio)
            if len(connection.sent) in {1, 12, 24}:
                turn_id = f"turn-{len(connection.sent)}"
                await connection.event("speech_started", turn_id=turn_id)
                await connection.event("transcript_final", turn_id=turn_id, text="Xin chào")
        connection.send = send
        return connection

    async def tts(text):
        # Audible-clock playback takes 0.1 s + a sentence pause.
        yield {"event": "audio_chunk", "index": 0, "sample_rate": 16000,
               "pcm16_base64": base64.b64encode(b'\x00\x04' * options['tts_samples']).decode()}
        yield {"event": "segment_end", "index": 0}
        if options["tts_error"]:
            raise RuntimeError("offline TTS failure")

    async def agent(request):
        payload = json.loads(request.content)
        if request.url.path == "/v1/chat/sessions/prepare":
            return httpx.Response(200, json={"session_id": payload["session_id"]})
        if request.url.path == "/v1/chat/turns/playback":
            options['playback_receipts'].append(payload)
            return httpx.Response(200, json={"session_id": payload["session_id"],
                "client_msg_id": payload["client_msg_id"], "memory_update": {
                    "turn_saved": True, "status": "pending" if options["memory_status"] else "not_applicable",
                    "changes": []}})
        if request.url.path == "/v1/chat/turns/memory":
            await asyncio.sleep(0.2)
            return httpx.Response(200, json={"session_id": payload["session_id"],
                "client_msg_id": payload["client_msg_id"], "memory_update": {
                    "turn_saved": True, "status": options["memory_status"],
                    "changes": options["memory_changes"]}})
        requests.append(payload)
        if options["wait_agent"]:
            while options["wait_agent"]:
                await asyncio.sleep(0.02)
        if options["agent_error"]:
            return httpx.Response(503)
        body = {"session_id": payload["session_id"], "agent_text": "Xin chào",
                "call_brief": options.get("call_brief")}
        if options["memory_status"]:
            body["memory_update"] = {"turn_saved": True, "status": "pending", "changes": []}
        return httpx.Response(200, json=body)

    speech.connect_listen = listen
    speech.stream_tts = tts
    app = create_app(VoiceSettings(_env_file=None))
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original_lifespan(app):
            async with httpx.AsyncClient(base_url="http://offline-agent",
                                         transport=httpx.MockTransport(agent)) as http:
                app.state.ai_http = http
                app.state.voice_speech = speech
                yield

    app.router.lifespan_context = lifespan
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        assert time.monotonic() < deadline, "Gateway did not start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}", requests, speech, options
    server.should_exit = True
    thread.join(5)
    sock.close()


@pytest.fixture
def browser(tmp_path):
    chrome = os.environ.get("CHROME_BIN") or shutil.which("google-chrome")
    if not chrome and Path("/opt/google/chrome/chrome").exists():
        chrome = "/opt/google/chrome/chrome"
    if not chrome:
        pytest.skip("Google Chrome required (or set CHROME_BIN)")
    process = subprocess.Popen([
        chrome, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        "--remote-debugging-port=0", f"--user-data-dir={tmp_path}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        port_file = tmp_path / "DevToolsActivePort"
        while not port_file.exists():
            assert time.monotonic() < deadline, "Chrome did not start"
            time.sleep(0.03)
        port = port_file.read_text().splitlines()[0]
        pages = httpx.get(f"http://127.0.0.1:{port}/json/list").json()
        page = next(page for page in pages if page["type"] == "page")
        with connect(page["webSocketDebuggerUrl"], max_size=4 * 1024 * 1024) as ws:
            sequence = 0

            def command(method, **params):
                nonlocal sequence
                sequence += 1
                ws.send(json.dumps({"id": sequence, "method": method, "params": params}))
                while True:
                    result = json.loads(ws.recv(timeout=20))
                    if result.get("id") == sequence:
                        assert "error" not in result, result
                        return result.get("result", {})

            def evaluate(code):
                result = command("Runtime.evaluate", expression=code,
                                 awaitPromise=True, returnByValue=True)
                assert "exceptionDetails" not in result, result
                return result.get("result", {}).get("value")

            yield command, evaluate
    finally:
        process.terminate()
        process.wait(timeout=10)


def open_site(browser, url):
    command, evaluate = browser
    response = httpx.get(url)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html'), response.headers
    command("Page.enable")
    navigation = command("Page.navigate", url=url)
    assert "errorText" not in navigation, navigation
    assert httpx.get(url).status_code == 200
    deadline = time.monotonic() + 15
    while not evaluate("!!document.querySelector('#identity')?.readOnly"):
        assert time.monotonic() < deadline, evaluate("document.documentElement.outerHTML")
        time.sleep(0.05)
    evaluate("""window.waitFor = (predicate) => new Promise((resolve, reject) => {
      const start = Date.now();
      const poll = () => {
        if (predicate()) resolve(true);
        else if (Date.now() - start > 8000) reject(Error('Timed out: ' + predicate + ' / ' + document.querySelector('#error').textContent));
        else setTimeout(poll, 30);
      }; poll();
    });
    window.tracks = [];
    window.contexts = [];
    const OriginalContext = window.AudioContext;
    window.AudioContext = class extends OriginalContext {
      constructor(...args) { super(...args); contexts.push(this); }
    };
    const originalMic = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (...args) => {
      const stream = await originalMic(...args); tracks.push(...stream.getTracks()); return stream;
    }; true""")
    return evaluate


def test_browser_continuous_turns_pcm_and_end_restart(site, browser):
    url, requests, speech, options = site
    js = open_site(browser, url)
    assert js("""(async () => {
      const { PCMEncoder } = await import('/assets/audio.js');
      for (const rate of [44100, 48000]) {
        const encoder = new PCMEncoder(rate); let chunks = [];
        for (let i = 0; i < rate; i += 128) {
          chunks.push(...encoder.push(new Float32Array(Math.min(128, rate-i)).fill(1)));
        }
        if (chunks.length < 19 || chunks.length > 20) throw Error('Bad resampling count');
        if (chunks.some(b => b.byteLength !== 1600 || new DataView(b).getInt16(0, true) !== 32767)) throw Error('Bad PCM');
      }
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelectorAll('.message.agent').length >= 2);
      document.querySelector('#end-call').click();
      if (!tracks.every(t => t.readyState === 'ended')) throw Error('Mic leaked');
      await waitFor(() => contexts.every(c => c.state === 'closed'));
      if (document.querySelector('#start-call').disabled) throw Error('Cannot restart');
      return true;
    })()""")
    assert len(requests) >= 2
    assert requests[0]["session_id"] == requests[1]["session_id"]
    assert requests[1]["session_id"]
    assert requests[0]["channel"] == "hotline"
    assert all(len(chunk) == 1600 for connection in speech.sockets for chunk in connection.sent)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelectorAll('.message.agent').length >= 1);
      document.querySelector('#end-call').click();
      return tracks.every(t => t.readyState === 'ended');
    })()""")
    # New WebSocket call starts a fresh harness session request.
    assert len({request["session_id"] for request in requests}) == 2


def test_browser_tts_failure_resumes_listening(site, browser):
    url, requests, speech, options = site
    options["tts_error"] = True
    js = open_site(browser, url)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelectorAll('.message.agent').length >= 2);
      const error = document.querySelector('#error').textContent;
      document.querySelector('#end-call').click();
      return error.includes('Không phát được') && tracks.every(t => t.readyState === 'ended');
    })()""")
    assert len(requests) >= 2


def test_browser_barge_in_stops_playout_and_discards_late_audio(site, browser):
    url, requests, speech, options = site
    options['tts_samples'] = 32000
    js = open_site(browser, url)
    assert js("""(async () => {
      const { PCMPlayer } = await import('/assets/audio.js');
      const enqueued = [], replies = []; let stops = 0;
      const enqueue = PCMPlayer.prototype.enqueue, stop = PCMPlayer.prototype.stop;
      PCMPlayer.prototype.enqueue = function(event) { enqueued.push(event.turn_id); return enqueue.call(this, event); };
      PCMPlayer.prototype.stop = function() { stops++; return stop.call(this); };
      const NativeSocket = window.WebSocket;
      window.WebSocket = class extends NativeSocket {
        constructor(...args) { super(...args); window.voiceSocket = this;
          this.addEventListener('message', message => {
            const event = JSON.parse(message.data);
            if (event.event === 'agent_reply') replies.push(event);
          });
        }
      };
      document.querySelector('#start-call').click();
      await waitFor(() => replies.length >= 2 && enqueued.includes(replies[1].turn_id));
      if (!stops) throw Error('Barge-in did not stop audio');
      const count = enqueued.length;
      voiceSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({
        event: 'audio', turn_id: replies[0].turn_id, index: 0,
        format: {encoding:'pcm_s16le',sample_rate:16000,channels:1}, audio_base64:'AAA='
      }) }));
      if (enqueued.length !== count) throw Error('Late audio reached player');
      document.querySelector('#end-call').click();
      return tracks.every(t => t.readyState === 'ended');
    })()""")
    assert len(requests) >= 2
    assert options['playback_receipts'][0]['interrupted'] is True
    assert options['playback_receipts'][0]['played_chars'] == 0


@pytest.mark.parametrize("status,changes,expected", [
    ("completed", [{"field": "room_area_m2", "action": "added", "value": 25,
                    "source": "customer", "scope_type": "global", "scope_id": ""}], "25 m²"),
    ("completed", [], "Không có thay đổi hồ sơ mới"),
    ("failed", [], "Cập nhật hồ sơ thất bại"),
    ("unavailable", [], "Chưa đọc được kết quả"),
    ("completed", [{"field": "preferred_color", "action": "updated",
                    "value": "<img src=x onerror=alert(1)>", "source": "customer",
                    "scope_type": "global", "scope_id": ""}], "<img"),
])
def test_browser_displays_real_memory_result_as_text(site, browser, status, changes, expected):
    url, requests, speech, options = site
    options.update(memory_status=status, memory_changes=changes)
    js = open_site(browser, url)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelector('.memory-update')?.dataset.status === 'pending');
      await waitFor(() => [...document.querySelectorAll('.memory-update')].some(
        panel => panel.dataset.status !== 'pending'));
      document.querySelector('#end-call').click();
      return document.querySelectorAll('.memory-update img').length === 0;
    })()""")
    assert expected in js("document.querySelector('.memory-update').textContent")


def test_browser_end_while_waiting_for_agent(site, browser):
    url, requests, speech, options = site
    options["wait_agent"] = True
    js = open_site(browser, url)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelector('#visual').dataset.state === 'processing');
      document.querySelector('#end-call').click();
      return tracks.every(t => t.readyState === 'ended') && !document.querySelector('#start-call').disabled;
    })()""")
    options["wait_agent"] = False


def test_browser_late_permission_and_denied_microphone(site, browser):
    js = open_site(browser, site[0])
    assert js("""(async () => {
      const original = navigator.mediaDevices.getUserMedia;
      navigator.mediaDevices.getUserMedia = async (...args) => {
        await new Promise(resolve => { window.releasePermission = resolve; });
        return original(...args);
      };
      document.querySelector('#start-call').click();
      await waitFor(() => !!window.releasePermission);
      document.querySelector('#end-call').click();
      releasePermission();
      await waitFor(() => tracks.length > 0 && tracks.every(t => t.readyState === 'ended'));
      navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError'); };
      document.querySelector('#start-call').click();
      await waitFor(() => !document.querySelector('#start-call').disabled);
      return document.querySelector('#error').textContent.includes('chưa cho phép micro');
    })()""")


def test_browser_fatal_agent_error_releases_microphone(site, browser):
    url, requests, speech, options = site
    options["agent_error"] = True
    js = open_site(browser, url)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => !document.querySelector('#start-call').disabled);
      await waitFor(() => tracks.length > 0 && tracks.every(t => t.readyState === 'ended'));
      return document.querySelector('#error').textContent.includes('Agent chưa trả lời');
    })()""")
    assert len(requests) == 1


def test_browser_shows_returning_call_brief_once_without_raw_trace(site, browser):
    url, requests, speech, options = site
    options['call_brief'] = {
        'is_returning': True, 'n_previous_sessions': 3,
        'customer_phone': '0901234567',
        'last_session': {'date': '2026-10-15', 'outcome': 'chot_don'},
        'products_advised': [{'sku': 'SKU-AP-X', 'price_quoted_vnd': 4890000,
                              'quoted_on': '2026-10-15', 'promo_code': 'GIFT-FILTER'}],
        'orders': [{'order_id': 'OD600004', 'variant_sku': 'SKU-AP-X', 'status': 'created'}],
        'open_blockers': [], 'open_questions': ['<img src=x onerror=alert(1)>'],
        'must_not_ask': ['room_area_m2', 'has_children'],
        'profile_facts': {'has_children': True, 'rooms': {'room_1': {
            'room_area_m2': {'value': 25, 'source': 'private-langmem-source'}}},
            'products': {'SKU-AP-X': {'blocker': {'value': 'đã giải quyết'}}}},
        'stale_warnings': ['Cần kiểm tra lại ưu đãi.'],
        'suggested_next_action': 'Tiếp tục tư vấn theo nhu cầu đã ghi nhận.',
    }
    js = open_site(browser, url)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelectorAll('.message.agent').length >= 2);
      document.querySelector('#end-call').click();
      return document.querySelectorAll('.call-brief').length === 1;
    })()""")
    text = js("document.querySelector('.call-brief').textContent")
    for value in ('3 phiên', 'SKU-AP-X', '4.890.000', 'OD600004', '25 m²', 'Cần kiểm tra lại ưu đãi'):
        assert value in text
    assert '0901234567' not in text and 'private-langmem-source' not in text
    assert 'đã giải quyết' not in text
    assert js("document.querySelectorAll('.call-brief img').length") == 0


@pytest.mark.parametrize('selected', [None, 'SKU-AP-Y'])
def test_brief_distinguishes_discussed_recommended_and_customer_selected_products(site, browser, selected):
    url, requests, speech, options = site
    options['call_brief'] = {
        'is_returning': True, 'n_previous_sessions': 2,
        'last_session': {'date': '2026-11-08', 'outcome': 'hen_goi_lai'},
        'products_advised': [{'sku': 'SKU-AP-X'}, {'sku': 'SKU-AP-Y'}],
        'recommended_sku': 'SKU-AP-Y', 'selected_sku': selected,
        'open_blockers': ['cần hỏi chồng'],
    }
    js = open_site(browser, url)
    assert js("""(async () => {
      document.querySelector('#start-call').click();
      await waitFor(() => document.querySelector('.call-brief'));
      document.querySelector('#end-call').click();
      return true;
    })()""")
    text = js("document.querySelector('.call-brief').textContent")
    assert 'Đã trao đổi: SKU-AP-X' in text and 'Đã trao đổi: SKU-AP-Y' in text
    assert 'Đề xuất gần nhất: SKU-AP-Y' in text
    assert ('Khách đã chọn: ' + (selected or 'Chưa xác nhận')) in text
    assert 'cần hỏi chồng' in text
