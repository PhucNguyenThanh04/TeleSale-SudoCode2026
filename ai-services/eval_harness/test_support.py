

class VoiceLifecycleStub:
    async def stream(self, request):
        from app.schemas.agent import TextTurnResponse, MemoryUpdate
        response = await self.run(request)
        identity = {'client_msg_id': str(request.client_msg_id), 'session_id': str(request.session_id)}
        yield {'event': 'delta', **identity, 'seq': 1, 'text': response.agent_text}
        yield {'event': 'done', **TextTurnResponse(
            client_msg_id=request.client_msg_id, session_id=request.session_id,
            agent_text=response.agent_text, call_brief=response.call_brief,
            memory_update=getattr(response, 'memory_update', MemoryUpdate(turn_saved=True, status='pending'))
        ).model_dump(mode='json')}

    async def prepare_session(self, request):
        pass

    async def record_playback(self, request):
        pass


LEGACY_TEXT_MEASUREMENT = {
    'lifecycle': 'prepare_session -> run(text, including persistence); drain_enrichment_at_call_end',
    'delivery_mode': 'text', 'playback': 'not_applicable',
    'response_scope': 'chat_to_complete_reply',
    'excluded': ['prepare', 'memory_worker_wait', 'asr', 'tts', 'http_transport'],
    'ttft_is_proxy': False, 'ttft_basis': 'nonstreaming_total_btc_rule_7',
}
