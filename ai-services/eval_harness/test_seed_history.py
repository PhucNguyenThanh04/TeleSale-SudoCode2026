import asyncio
from datetime import date
from unittest.mock import AsyncMock
import pytest
from eval_harness.seed_history import parse_seed_history, SeedHistoryGateway

HISTORY = [dict(session_id='old', date='2026-02-01', channel='hotline', summary='Khách thích màu xanh')]


def test_old_crm_history_is_visible_only_for_resolved_identity():
    inner = AsyncMock()
    inner.invoke.return_value = {'found': True, 'customer_id':'C1', 'sessions':[]}
    gateway = SeedHistoryGateway(inner)
    gateway.select('S1', {'hotline': '0900000000'}, HISTORY)
    result = asyncio.run(gateway.invoke('crm.get_customer', {'phone':'0900000000'}))
    assert result['sessions'] == HISTORY
    assert inner.invoke.return_value['sessions'] == []
    inner.invoke.return_value = {'found': False}
    with pytest.raises(RuntimeError):
        asyncio.run(gateway.invoke('crm.get_customer', {'phone':'0900000000'}))
    gateway.select('S2', {}, [])
    assert asyncio.run(gateway.invoke('crm.get_customer', {'phone':'other'})) == {'found':False}


def test_conflicting_history_session_fails_preflight():
    assert parse_seed_history(HISTORY, call_date=date(2026,10,15)) == HISTORY
    for value in ('old', [{**HISTORY[0], 'date':'2027-01-01'}], [HISTORY[0], {**HISTORY[0], 'summary':'khác'}]):
        with pytest.raises(ValueError):
            parse_seed_history(value, call_date=date(2026,10,15))


def test_btc_history_facts_channels_and_dates_are_normalized_without_mutation():
    from copy import deepcopy
    history = [{**HISTORY[0], 'session_id': 'new', 'date': '2026-09-17', 'channel': 'phone',
                'facts': [{'field': 'interest_sku', 'value': 'SKU-AP-X'},
                          {'field': 'budget_vnd', 'value': 5000000, 'as_of': '2026-08-10'}]}, HISTORY[0]]
    before = deepcopy(history)
    parsed = parse_seed_history(history, call_date=date(2026, 10, 15))
    assert [h['session_id'] for h in parsed] == ['old', 'new']
    assert parsed[1]['channel'] == 'hotline'
    assert parsed[1]['facts'][0]['as_of'] == '2026-09-17'
    assert parsed[1]['facts'][1]['as_of'] == '2026-08-10'
    assert history == before


def test_fact_as_of_is_independent_of_session_date_but_must_precede_current_call():
    history = [{**HISTORY[0], 'facts': [{'field': 'budget_vnd', 'value': 5000000, 'as_of': '2026-09-17'}]}]
    assert parse_seed_history(history, call_date=date(2026, 10, 15))[0]['facts'][0]['as_of'] == '2026-09-17'
    with pytest.raises(ValueError, match='not_prior'):
        parse_seed_history(history, call_date=date(2026, 9, 17))


def test_seed_accepts_large_currency_value():
    history = [{**HISTORY[0], 'facts': [{'field': 'budget_vnd', 'value': 1_000_000_000}]}]
    assert parse_seed_history(history, call_date=date(2026, 10, 15))[0]['facts'][0]['value'] == 1_000_000_000


@pytest.mark.parametrize('fact', [
    {'field': 'budget_vnd', 'value': 100, 'as_of': '2027-01-01'},
    {'field': 'budget_vnd', 'value': float('nan')},
    {'field': 'cccd', 'value': '012345678901'},
    {'field': 'bank_account', 'value': '123456789012'},
    {'field': 'budget_vnd', 'value': 100, 'unexpected': True},
    {'field': '', 'value': 100},
    {'field': 'address', 'value': 'STK 123456789012'},
    {'field': 'budget_vnd', 'value': True},
])
def test_history_rejects_invalid_or_forbidden_facts(fact):
    with pytest.raises(ValueError, match='seed_history'):
        parse_seed_history([{**HISTORY[0], 'facts': [fact]}], call_date=date(2026, 10, 15))


def test_gateway_materializes_seed_before_returning_resolved_identity_once():
    inner = AsyncMock()
    inner.invoke.return_value = {'found': True, 'customer_id': 'C1', 'sessions': []}
    materialize = AsyncMock(return_value=HISTORY)
    gateway = SeedHistoryGateway(inner, materialize=materialize)
    gateway.select('S', {'hotline': '0900000000'}, HISTORY)
    async def run():
        for _ in range(2):
            result = await gateway.invoke('crm.get_customer', {'phone': '0900000000'})
            assert result['sessions'] == HISTORY
    asyncio.run(run())
    materialize.assert_awaited_once_with('S', 'C1', HISTORY)
    inner.invoke.return_value = {'found': True, 'ambiguous': True, 'candidates': []}
    gateway.select('other', {'hotline': '0900000000'}, HISTORY)
    assert asyncio.run(gateway.invoke('crm.get_customer', {'phone': '0900000000'})) == inner.invoke.return_value
    assert materialize.await_count == 1


def test_shared_phone_defers_seed_until_trusted_identity_selects_the_owner():
    from uuid import uuid4
    from app.agent.harness.session_identity import initialize_identity
    from app.schemas.agent import TextTurnRequest

    phone = '0900000000'
    raw = {'found': True, 'ambiguous': True, 'candidates': [
        {'customer_id': 'C1', 'sessions': []}, {'customer_id': 'C2', 'sessions': []}]}
    inner = AsyncMock()
    inner.invoke.return_value = raw
    inner.invoke_trusted.return_value = raw
    load = AsyncMock(return_value=HISTORY)
    gateway = SeedHistoryGateway(inner, materialize=load)
    gateway.select('S', {'hotline': phone}, HISTORY)
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel='hotline',
        channel_identity=phone, input_mode='clean', on=date(2026, 10, 15), text='Xin chào')

    async def run():
        await gateway.prepare_history('hotline', phone)
        identity, _ = await initialize_identity(request, gateway)
        assert identity['identity_status'] == 'ambiguous'
        assert identity['crm_sessions'] == []
        load.assert_not_awaited()

        verified = request.model_copy(update={'verified_phone': phone, 'verified_customer_id': 'C1'})
        identity, calls = await initialize_identity(verified, gateway)
        assert identity['crm_sessions'] == HISTORY
        assert calls[0]['result']['candidates'][1]['sessions'] == []
        assert raw['candidates'][0]['sessions'] == []
        load.assert_awaited_once_with('S', 'C1', HISTORY)

    asyncio.run(run())


def test_seed_cannot_change_existing_session_channel():
    inner = AsyncMock()
    inner.invoke.return_value = {'found': True, 'customer_id': 'C1',
                                'sessions': [{**HISTORY[0], 'channel': 'zalo_oa'}]}
    gateway = SeedHistoryGateway(inner)
    gateway.select('S', {'hotline': '0900000000'}, HISTORY)
    with pytest.raises(RuntimeError, match='conflict'):
        asyncio.run(gateway.invoke('crm.get_customer', {'phone': '0900000000'}))


def test_multiple_declared_identities_of_same_channel_cannot_switch_seed_owner():
    inner = AsyncMock()
    inner.invoke.return_value = {'found': True, 'customer_id': 'C1', 'sessions': []}
    load = AsyncMock(return_value=HISTORY)
    gateway = SeedHistoryGateway(inner, materialize=load)
    gateway.select('S', {'hotline': ['0900000000', '0900000001']}, HISTORY)
    async def run():
        for phone in ('0900000000', '0900000001'):
            await gateway.prepare_history('hotline', phone)
        assert load.await_count == 1
        inner.invoke.return_value = {'found': True, 'customer_id': 'C2', 'sessions': []}
        with pytest.raises(RuntimeError, match='identity_conflict'):
            await gateway.prepare_history('hotline', '0900000001')
    asyncio.run(run())


def test_baseline_context_does_not_receive_seeded_crm_sessions():
    from app.agent.harness.context import load_context
    from app.schemas.agent import TextTurnRequest
    from datetime import datetime, timezone
    from uuid import uuid4
    from types import SimpleNamespace
    request=TextTurnRequest(client_msg_id=uuid4(),session_id=uuid4(),channel='hotline',
        channel_identity='0900000000',input_mode='clean',on=date(2026,10,15),text='Tôi gọi lại')
    state={'request':request,'customer_id':'C1','customer_phone':'0900000000','identity_status':'known',
           'received_at_monotonic':0.0,'tool_calls':[],'crm_sessions':HISTORY,'safe_text':request.text}
    for enabled in (True,False):
        memory=SimpleNamespace(include_prior=enabled,max_episodes=5,
            read_context=AsyncMock(return_value={'history':[],'profile':{},'scoped_facts':{},'episodes':[]}))
        result=asyncio.run(load_context(state,memory,SimpleNamespace(invoke=AsyncMock(return_value={})),
            lambda:datetime(2026,10,15,tzinfo=timezone.utc)))
        assert any(e.get('session_id')=='old' for e in result.get('episodes',[])) == enabled
