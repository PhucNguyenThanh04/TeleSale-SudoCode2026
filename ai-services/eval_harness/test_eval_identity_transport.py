import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eval_harness.benchmark_runner import run_scenario_call
from eval_harness.test_support import VoiceLifecycleStub


@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
@pytest.mark.parametrize('channel', ['chat_fanpage', 'zalo_oa'])
def test_explicit_verified_actor_reaches_prepare_turns_and_playback(delivery_mode, channel):
    requests = []

    class Runtime(VoiceLifecycleStub):
        async def prepare_session(self, request):
            requests.append(('prepare', request))

        async def run(self, request):
            requests.append(('turn', request))
            return SimpleNamespace(agent_text='Em đã nhận đúng hồ sơ.', call_brief=None)

        async def record_playback(self, request):
            requests.append(('playback', request))

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': []}

    rows = asyncio.run(run_scenario_call(Runtime(), 'INDEPENDENT', 'call_1', {
        'customer_turns': ['Tôi gọi lại.', 'Tiếp nhé.'], 'channel': channel,
        'channel_identity': 'unlinked-account',
        'verified_customer_id': 'OWNER-81', 'verified_phone': '0900000081',
    }, date(2033, 5, 10), '0900000092', delivery_mode=delivery_mode))
    assert len(rows) == 2
    assert [kind for kind, _ in requests] == (
        ['prepare', 'turn', 'playback', 'turn', 'playback'] if delivery_mode == 'voice'
        else ['prepare', 'turn', 'turn'])
    for _, request in requests:
        assert request.verified_customer_id == 'OWNER-81'
        assert request.verified_phone == '0900000081'
        assert request.channel_identity == 'unlinked-account'
        assert request.channel == channel


@pytest.mark.parametrize('channel,expected', [
    ('hotline', '0900000081'), ('chat_fanpage', None), ('zalo_oa', None),
])
def test_missing_social_identity_never_uses_the_descriptive_phone(channel, expected):
    requests = []

    class Runtime(VoiceLifecycleStub):
        async def prepare_session(self, request):
            requests.append(request)

        async def run(self, request):
            requests.append(request)
            return SimpleNamespace(agent_text='Em cần xác minh danh tính.', call_brief=None)

        def state_for(self, request):
            return {'profile': {}, 'tool_calls': []}

    asyncio.run(run_scenario_call(Runtime(), 'INDEPENDENT', 'call_1', {
        'customer_turns': ['Số của tôi là 0900000092.'], 'channel': channel,
    }, date(2033, 5, 10), '0900000081'))
    assert len(requests) == 2
    for request in requests:
        assert request.channel_identity == expected
        assert request.verified_customer_id is None
        assert request.verified_phone is None


@pytest.mark.parametrize('identity', [
    {'verified_customer_id': 'OWNER-81'}, {'verified_phone': '0900000081'},
    {'verified_customer_id': ' ', 'verified_phone': '0900000081'},
    {'verified_customer_id': 'OWNER-81', 'verified_phone': ''},
])
def test_incomplete_verified_identity_stops_before_runtime(identity):
    with pytest.raises(ValueError, match='verified_identity_invalid'):
        asyncio.run(run_scenario_call(object(), 'INDEPENDENT', 'call_1', {
            'customer_turns': ['Xin chào.'], **identity,
        }, date(2033, 5, 10), '0900000081'))


def test_invalid_actor_cannot_materialize_seed_history_before_validation():
    from eval_harness.benchmark_runner import run_scenario_stream
    from eval_harness.seed_history import SeedHistoryGateway
    inner = SimpleNamespace(invoke=AsyncMock(return_value={
        'found': True, 'customer_id': 'OWNER-81', 'sessions': []}))
    materialize = AsyncMock(return_value=[{'session_id': 'prior', 'date': '2026-01-01',
                                          'channel': 'hotline', 'summary': 'Khách đang cân nhắc.'}])
    runtime = SimpleNamespace(tools=SeedHistoryGateway(inner, materialize=materialize))
    scenarios = {'INDEPENDENT': {'customer_phone': '0900000081', 'calls': {'call_1': {
        'customer_turns': ['Xin chào.'], 'verified_customer_id': 'OWNER-81',
        'seed_history': [{'session_id': 'prior', 'date': '2026-01-01',
                          'channel': 'hotline', 'summary': 'Khách đang cân nhắc.'}],
    }}}}
    with pytest.raises(ValueError, match='verified_identity_invalid'):
        asyncio.run(run_scenario_stream(runtime, scenarios))
    materialize.assert_not_awaited()
