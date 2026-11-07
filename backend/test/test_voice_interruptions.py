"""Full duplex voice races with offline STT, synthesis and harness doubles."""
import asyncio

import httpx
import pytest

from test_voice_flow import setup_call, end_call


@pytest.mark.asyncio
async def test_speech_interrupts_tts_and_keeps_microphone_connected():
    browser, speech, requests, http, task = await setup_call()
    speech.tts_wait = asyncio.Event()
    try:
        socket = speech.sockets[0]
        await socket.event('transcript_final', text='chào')
        first = await browser.until('agent_reply')
        await browser.until('state', state='speaking')
        await browser.audio(b'customer-over-bot')
        await socket.event('speech_started', turn_id='turn-2')
        stop = await browser.until('playback_interrupt')
        assert stop['turn_id'] == first['turn_id']
        assert not socket.closed
        assert b'customer-over-bot' in socket.sent
        await browser.command({'event': 'playback_stopped', 'turn_id': first['turn_id'],
                               'played_chars': 0})
        speech.tts_wait.set()
        await socket.event('transcript_final', turn_id='turn-2', text='đợi đã')
        second = await browser.until('agent_reply')
        assert second['turn_id'] != first['turn_id']
        assert len(speech.sockets) == 1
        await browser.until('audio_complete', turn_id=second['turn_id'])
        assert len(requests) == 2
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_interrupt_during_business_request_does_not_cancel_or_retry_it():
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(request, payload):
        if payload['text'] == 'đặt đơn':
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        return httpx.Response(200, json={'session_id': payload['session_id'], 'agent_text': 'Xin chào'})

    browser, speech, requests, http, task = await setup_call(handler)
    try:
        socket = speech.sockets[0]
        await socket.event('transcript_final', text='đặt đơn')
        await asyncio.wait_for(entered.wait(), 2)
        await socket.event('speech_started', turn_id='turn-2')
        interrupted = await browser.until('playback_interrupt')
        await browser.command({'event': 'playback_stopped', 'turn_id': interrupted['turn_id'],
                               'played_chars': 0})
        await socket.event('transcript_final', turn_id='turn-2', text='tôi muốn hỏi thêm')
        await browser.until('transcript_final', text='tôi muốn hỏi thêm')
        assert len(requests) == 1 and not cancelled.is_set()
        release.set()
        reply = await browser.until('agent_reply')
        assert reply['turn_id'] != interrupted['turn_id']
        assert [r['text'] for r in requests] == ['đặt đơn', 'tôi muốn hỏi thêm']
        assert not cancelled.is_set()
    finally:
        release.set()
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_duplicate_final_is_consumed_once_even_after_playback():
    browser, speech, requests, http, task = await setup_call()
    try:
        socket = speech.sockets[0]
        await socket.event('transcript_final', text='chào')
        reply = await browser.until('agent_reply')
        await browser.until('audio_complete')
        await browser.command({'event': 'playback_finished', 'turn_id': reply['turn_id']})
        await browser.until('state', state='listening')
        await socket.event('transcript_final', text='duplicate')
        await socket.event('speech_started', turn_id='turn-2')
        await browser.until('speech_started')
        assert len(requests) == 1
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_playback_receipt_uses_only_issued_marks_before_next_business_request():
    receipts, sequence = [], []

    async def handler(request, payload):
        sequence.append(payload['text'])
        return httpx.Response(200, json={'session_id': payload['session_id'],
            'agent_text': 'Câu đầu. Câu sau.'})

    async def playback(request, payload):
        receipts.append(payload)
        sequence.append('receipt')
        return httpx.Response(200, json={'session_id': payload['session_id'],
            'client_msg_id': payload['client_msg_id'], 'memory_update': {
                'turn_saved': True, 'status': 'not_applicable', 'changes': []}})

    browser, speech, requests, http, task = await setup_call(handler, playback_handler=playback)
    async def tts(text):
        yield {'event': 'audio_chunk', 'index': 0, 'sample_rate': 48000,
               'pcm16_base64': 'AAA='}
        yield {'event': 'segment_end', 'index': 0}
    speech.stream_tts = tts
    try:
        socket = speech.sockets[0]
        await socket.event('transcript_final', text='chào')
        reply = await browser.until('agent_reply')
        first_mark = await browser.until('audio_mark')
        assert first_mark['played_chars'] == len('Câu đầu.')
        await browser.until('audio_complete')
        await browser.command({'event': 'playback_progress', 'turn_id': reply['turn_id'],
                               'played_chars': 9000})
        await browser.until('error', code='unexpected_playback')
        await browser.command({'event': 'playback_progress', 'turn_id': reply['turn_id'],
                               'played_chars': first_mark['played_chars']})
        await socket.event('speech_started', turn_id='turn-2')
        await browser.until('playback_interrupt')
        await browser.command({'event': 'playback_stopped', 'turn_id': reply['turn_id'],
                               'played_chars': first_mark['played_chars']})
        await socket.event('transcript_final', turn_id='turn-2', text='tiếp')
        await browser.until('agent_reply')
        assert sequence[:3] == ['chào', 'receipt', 'tiếp']
        assert receipts[0]['played_chars'] == len('Câu đầu.')
        assert receipts[0]['client_msg_id'] == requests[0]['client_msg_id']
        assert receipts[0]['interrupted'] is True
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_failed_stt_turn_cannot_reappear_as_late_final():
    browser, speech, requests, http, task = await setup_call()
    try:
        socket = speech.sockets[0]
        await socket.event('speech_started')
        await socket.event('error', code='transcription_failed', fatal=False)
        await browser.until('error', code='transcription_failed')
        await socket.event('transcript_final', text='late rejected transcript')
        await socket.event('speech_started', turn_id='turn-2')
        await browser.until('speech_started')
        assert requests == []
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_missing_stop_receipt_after_barge_in_has_bounded_wait(monkeypatch):
    import app.services.voice_call as voice
    timeout = asyncio.timeout
    monkeypatch.setattr(voice.asyncio, 'timeout', lambda seconds: timeout(0.02 if seconds == 5 else seconds))
    browser, speech, requests, http, task = await setup_call()
    try:
        socket = speech.sockets[0]
        await socket.event('transcript_final', text='chào')
        await browser.until('audio_complete')
        await socket.event('speech_started', turn_id='turn-2')
        await browser.until('playback_interrupt')
        await socket.event('transcript_final', turn_id='turn-2', text='tiếp')
        reply = await browser.until('agent_reply')
        assert len(requests) == 2
        assert reply['turn_id']
    finally:
        await end_call(browser, http, task)


@pytest.mark.asyncio
async def test_disconnect_before_preparation_finishes_does_not_issue_business_request():
    cancelled = asyncio.Event()
    async def prepare(request, payload):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    browser, speech, requests, http, task = await setup_call(prepare_handler=prepare)
    try:
        await speech.sockets[0].event('transcript_final', text='chào')
        await browser.until('state', state='processing')
        await browser.incoming.put({'type': 'websocket.disconnect'})
        await asyncio.wait_for(task, 1)
        assert cancelled.is_set() and requests == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await http.aclose()
