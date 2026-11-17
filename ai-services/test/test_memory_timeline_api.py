import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.agent.harness.runtime import AgentHarnessRuntime
from app.api.chat import get_harness
from app.main import app
from app.schemas.agent import PrepareSessionRequest
from app.schemas.timeline import TimelineRequest
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


def page():
    return {'status': 'available', 'items': [{'session_id': 'past', 'on': '2026-10-10',
        'channel': 'chat_fanpage', 'summary': 'Khách cần hỏi người nhà', 'outcome': 'hen_goi_lai',
        'summary_status': 'ready'}], 'offset': 0, 'limit': 10, 'total': 1, 'next_offset': None}


async def prepared():
    model, memory = FakeToolModel(replies=[]), FakeMemory()
    memory.read_timeline = AsyncMock(return_value=page())
    runtime = AgentHarnessRuntime(model, FakeGateway(), memory)
    request = TimelineRequest.model_validate(turn('Alo').model_dump(include={
        'session_id', 'channel', 'channel_identity', 'on'}))
    await runtime.prepare_session(PrepareSessionRequest.model_validate(request.model_dump(exclude={'offset','limit'})))
    return runtime, memory, model, request


def test_runtime_only_reads_prepared_identity_without_model_or_new_crm_lookup():
    async def run():
        runtime, memory, model, request = await prepared()
        before = list(runtime.tools.calls)
        result = await runtime.memory_timeline(request)
        assert result.items[0].channel == 'chat_fanpage'
        args, kwargs = memory.read_timeline.await_args
        assert args[:2] == (str(request.session_id), 'C001')
        assert kwargs['offset'] == 0 and kwargs['limit'] == 10
        assert runtime.tools.calls == before and model.seen == []
        assert len(runtime.memory.turns) == 0  # reading timeline never commits a turn
    asyncio.run(run())


@pytest.mark.parametrize('mismatch', ['unprepared', 'identity', 'channel', 'date', 'verified_customer'])
def test_runtime_rejects_conflicting_bindings_before_read(mismatch):
    async def run():
        runtime, memory, _, request = await prepared()
        changes = {'unprepared': {'session_id': uuid4()}, 'identity': {'channel_identity': 'OTHER'},
                   'channel': {'channel': 'zalo_oa'}, 'date': {'on': request.on.replace(day=1)},
                   'verified_customer': {'verified_customer_id': 'OTHER'}}[mismatch]
        with pytest.raises(ValueError):
            await runtime.memory_timeline(request.model_copy(update=changes))
        memory.read_timeline.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('status', ['unknown', 'ambiguous', 'no_prior'])
def test_unknown_ambiguous_or_baseline_has_no_customer_history(status):
    async def run():
        runtime, memory, _, request = await prepared()
        if status == 'no_prior':
            memory.include_prior = False
        else:
            bound = runtime._session_identities[str(request.session_id)][1]
            bound.update(identity_status=status, customer_id=None)
        result = await runtime.memory_timeline(request)
        assert result.status == 'not_applicable' and result.items == []
        memory.read_timeline.assert_not_awaited()
    asyncio.run(run())


def test_internal_api_authentication_validation_and_fail_closed(monkeypatch):
    monkeypatch.setattr('app.api.chat.get_settings', lambda: SimpleNamespace(ai_internal_token=SecretStr('offline-timeline')))
    async def run():
        runtime, memory, model, request = await prepared()
        async def harness(): return runtime
        app.dependency_overrides[get_harness] = harness
        headers = {'X-AI-Internal-Token': 'offline-timeline'}
        data = request.model_dump(mode='json')
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://offline') as client:
                assert (await client.post('/v1/chat/sessions/timeline', json=data)).status_code == 401
                result = await client.post('/v1/chat/sessions/timeline', json=data, headers=headers)
                assert result.status_code == 200
                assert result.json()['session_id'] == str(request.session_id)
                assert result.json()['timeline']['items'][0]['session_id'] == 'past'
                for changes, code in [({'channel_identity':'OTHER'},409), ({'limit':21},422),
                                      ({'customer_id':'OTHER'},422), ({'crm_sessions':[]},422)]:
                    assert (await client.post('/v1/chat/sessions/timeline', json=data|changes, headers=headers)).status_code == code
                for bad in ({'error':'customer_erasure_in_progress'}, {'items':[{'summary':'PRIVATE'}]}):
                    memory.read_timeline.return_value = bad
                    rejected = await client.post('/v1/chat/sessions/timeline', json=data, headers=headers)
                    assert rejected.status_code == 503 and 'PRIVATE' not in rejected.text
        finally:
            app.dependency_overrides.clear()
        assert model.seen == []
    asyncio.run(run())
