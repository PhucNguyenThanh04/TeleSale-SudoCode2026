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
