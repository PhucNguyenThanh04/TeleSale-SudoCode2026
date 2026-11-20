import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from test_text_harness_contract import turn_state, old_lamp_reads, nodes

MODEL_REPLY = 'Em cần xác minh thêm thông tin để hỗ trợ đúng yêu cầu của mình.'


def test_completed_transaction_is_evidence_for_llm_not_a_written_receipt():
    async def run():
        state = turn_state('Tôi đồng ý mua đèn.')
        state['session_tool_calls'] = old_lamp_reads(state)
        state.update(agent_draft='', reply_context={'reason':'model_unavailable'}, tool_calls=[{
            'name':'order.create','args':{'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000},
            'result':{'status':'created','order_id':'OD555001'}}])
        node, _ = nodes()
        node.llm.ainvoke.return_value = AIMessage(content=MODEL_REPLY)
        result = await node.verify_agent(state)
        assert node.llm.ainvoke.await_count == 1
        assert result['agent_text'] == MODEL_REPLY
        assert 'OD555001' in str(node.llm.ainvoke.await_args.args[0])
    asyncio.run(run())


@pytest.mark.parametrize('mode',['known','unknown','blocked'])
def test_privacy_handoff_is_model_proposed_and_identity_bound(mode):
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeToolModel,FakeMemory
    async def run():
        state=turn_state('Tôi yêu cầu xóa toàn bộ hồ sơ cá nhân.')
        request=state['request']
        if mode=='unknown':request=request.model_copy(update={'channel':'web_chat','channel_identity':'anonymous'})
        reply=('Mình vui lòng xác minh kênh liên hệ trước khi chuyển yêu cầu nhé?' if mode=='unknown'
               else 'Em đã chuyển yêu cầu đến nhân viên để xác minh phạm vi xử lý.')
        model=FakeToolModel(replies=[AIMessage(content='',tool_calls=[{
            'name':'handoff_transfer','args':{'brief':{'escalation_reason':'khac','conversation_summary':'Khách yêu cầu nhân viên xác minh phạm vi xử lý hồ sơ.','open_questions':[],'next_action':'Nhân viên xác minh yêu cầu và hướng xử lý.'}},'id':'transfer'}]),
            AIMessage(content=reply)])
        results={'crm.get_customer':({'found':False} if mode=='unknown' else {
            'found':True,'customer_id':'owner-a','phone':'0900000011','orders':[],'sessions':[]}),
            'handoff.transfer':{'status':'queued','ticket_id':'HT123'}}
        gateway=SimpleNamespace(invoke=AsyncMock(side_effect=lambda name,args:results[name]))
        memory=FakeMemory()
        if mode=='blocked':
            memory.read_context=AsyncMock(return_value={'error':'customer_erasure_in_progress'})
            memory.commit_turn=AsyncMock(side_effect=AssertionError('erasure barrier'))
        runtime=AgentHarnessRuntime(model,gateway,memory)
        try:
            with patch('app.agent.harness.authorization.authorize_write',AsyncMock(return_value=True)):
                response=await runtime.run(request)
            assert response.agent_text==reply and len(model.seen)==2
            transfers=[c for c in gateway.invoke.await_args_list if c.args[0]=='handoff.transfer']
            assert len(transfers)==int(mode!='unknown')
            assert response.needs_handoff is (mode!='unknown')
            if mode=='blocked':memory.commit_turn.assert_not_called()
        finally:await runtime.close()
    asyncio.run(run())


def test_context_failure_is_explained_by_llm_without_business_tools():
    async def run():
        state = turn_state('Tôi muốn tiếp tục yêu cầu hôm trước.')
        state['tool_failed'] = True
        node, gateway = nodes()
        node.llm.ainvoke.return_value = AIMessage(content=MODEL_REPLY)
        with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('no business loop')):
            changes = await node.run_agent(state)
        assert changes.get('agent_draft') == ''
        state.update(changes)
        result = await node.verify_agent(state)
        assert result['agent_text'] == MODEL_REPLY
        assert node.llm.ainvoke.await_count == 1 and not gateway.invoke.called
    asyncio.run(run())


@pytest.mark.parametrize('repair', [None, '', '{"tool_calls":[]}'])
def test_failed_or_invalid_llm_repair_has_no_scripted_customer_reply(repair):
    async def run():
        state = turn_state('Đèn bàn Aurora giá bao nhiêu?')
        state['tool_calls'] = old_lamp_reads(state)
        state['agent_draft'] = 'Đèn bàn Aurora giá 999000đ.'
        node, _ = nodes()
        if repair is None:
            node.llm.ainvoke.side_effect = RuntimeError('private provider error')
        else:
            node.llm.ainvoke.return_value = AIMessage(content=repair)
        result = await node.verify_agent(state)
        assert result['agent_text'] == ''
        assert result['reply_error'] == 'agent_reply_unavailable'
        assert node.llm.ainvoke.await_count == 1
    asyncio.run(run())


def test_stream_rejects_internal_output_without_replacing_it_with_a_sentence():
    from app.agent.harness.streaming import GuardedStream

    async def run():
        sink = AsyncMock(return_value=True)
        stream = GuardedStream(sink)
        state = turn_state('Xin chào.')
        assert await stream.finish('{"tool_calls":[]}', state) == ''
        assert state['reply_error'] == 'agent_reply_unavailable'
        assert not sink.called and stream.published == ''
    asyncio.run(run())


def test_model_outage_is_a_cached_protocol_error_and_empty_assistant_memory():
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeToolModel, FakeMemory, FakeGateway

    async def run():
        state = turn_state('Xin tư vấn giúp tôi.')
        model, memory, gateway = FakeToolModel(replies=[]), FakeMemory(), FakeGateway()
        runtime = AgentHarnessRuntime(model, gateway, memory)
        try:
            with pytest.raises(RuntimeError, match='agent_reply_unavailable'):
                await runtime.run(state['request'])
            saved = memory.turns[str(state['request'].session_id)]
            assert len(saved) == 1 and saved[0]['agent'] == ''
            attempts, calls = len(model.seen), len(gateway.calls)
            with pytest.raises(RuntimeError, match='agent_reply_unavailable'):
                await runtime.run(state['request'])
            assert len(saved) == 1 and len(model.seen) == attempts and len(gateway.calls) == calls
            events = [e async for e in runtime.stream(state['request'])]
            assert len(events) == 1 and events[0]['event'] == 'error'
            assert 'agent_text' not in events[0] and 'text' not in events[0]
        finally:
            await runtime.close()
    asyncio.run(run())


def test_cached_turn_memory_failure_is_an_error_without_fake_agent_speech():
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeToolModel, FakeMemory, FakeGateway

    async def run():
        state = turn_state('Xin chào.')
        model, memory = FakeToolModel(replies=[AIMessage(content=MODEL_REPLY)]), FakeMemory()
        runtime = AgentHarnessRuntime(model, FakeGateway(), memory)
        try:
            assert (await runtime.run(state['request'])).agent_text == MODEL_REPLY
            memory.read_context = AsyncMock(return_value={'error':'memory_store_unavailable'})
            with pytest.raises(RuntimeError, match='memory_unavailable'):
                await runtime.run(state['request'])
        finally:
            await runtime.close()
    asyncio.run(run())


def test_call_brief_does_not_inject_a_scripted_opening_into_the_agent():
    from app.agent.harness.context import load_context
    from test_deep_memory import FakeMemory

    async def run():
        state = turn_state('Tôi hỏi tiếp chuyện hôm trước.')
        import time
        state['received_at_monotonic'] = time.perf_counter()
        memory = FakeMemory()
        memory.read_context = AsyncMock(return_value={'history':[],'profile':{},'episodes':[{
            'session_id':str(uuid4()),'on':'2030-04-07','channel':'hotline',
            'summary':'Khách tìm hiểu đèn bàn.','outcome':'khac'}]})
        node, gateway = nodes()
        result = await load_context(state, memory, gateway, node.clock)
        assert result['call_brief']['suggested_opening'] == ''
    asyncio.run(run())


@pytest.mark.parametrize('delivery', ['text','voice'])
def test_completed_order_survives_reply_outage_without_a_scripted_receipt_or_repeat(delivery):
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeToolModel, FakeMemory

    async def run():
        state = turn_state('Tôi đồng ý mua một đèn Aurora giá 199000đ.')
        request = state['request'].model_copy(update={'delivery_mode':delivery})
        model = FakeToolModel(replies=[
            AIMessage(content='', tool_calls=[{'name':'catalog_search','args':{'sku':'SKU-LAMP-A'},'id':'cat'}]),
            AIMessage(content='', tool_calls=[
                {'name':'inventory_check','args':{'sku':'SKU-LAMP-A'},'id':'stock'},
                {'name':'pricing_get_quote','args':{'sku':'SKU-LAMP-A'},'id':'quote'}]),
            AIMessage(content='', tool_calls=[{'name':'order_create','args':{
                'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'},'id':'create'}])])
        results = {c['name']:c['result'] for c in old_lamp_reads(state)}
        results.update({'crm.get_customer':{'found':True,'customer_id':'owner-a',
            'phone':'0900000011','orders':[],'sessions':[]},
            'order.create':{'status':'created','order_id':'OD555001'}})
        gateway = SimpleNamespace(invoke=AsyncMock(side_effect=lambda name,args: results[name]))
        memory = FakeMemory()
        memory.commit_turn = AsyncMock(wraps=memory.commit_turn)
        runtime = AgentHarnessRuntime(model, gateway, memory)
        try:
            with patch('app.agent.harness.authorization.authorize_write', AsyncMock(return_value=True)):
                with pytest.raises(RuntimeError, match='agent_reply_unavailable'):
                    await runtime.run(request)
            saved = memory.turns[str(request.session_id)]
            assert len(saved) == 1 and saved[0]['agent'] == ''
            calls = memory.commit_turn.await_args.kwargs['tool_observations']
            assert any(c['name']=='order.create' and c['result']['order_id']=='OD555001' for c in calls)
            assert not runtime._playback_tasks
            attempts = len(model.seen)
            with pytest.raises(RuntimeError, match='agent_reply_unavailable'):
                await runtime.run(request)
            assert sum(c.args[0]=='order.create' for c in gateway.invoke.await_args_list) == 1
            assert len(model.seen) == attempts and memory.commit_turn.await_count == 1
            with pytest.raises(ValueError, match='Conflicting turn retry'):
                await runtime.run(request.model_copy(update={'text':'Nội dung khác'}))
        finally:
            await runtime.close()
    asyncio.run(run())


def test_http_and_ndjson_failures_do_not_fabricate_agent_messages():
    import json
    import httpx
    from pydantic import SecretStr
    from app.api.chat import get_harness
    from app.main import app
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeToolModel, FakeMemory, FakeGateway

    async def run():
        runtime = AgentHarnessRuntime(FakeToolModel(replies=[]), FakeGateway(), FakeMemory())
        request = turn_state('Xin tư vấn.')['request']
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[get_harness] = lambda: runtime
        try:
            with patch('app.api.chat.get_settings', return_value=SimpleNamespace(ai_internal_token=SecretStr('offline'))):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://offline') as client:
                    headers = {'X-AI-Internal-Token':'offline'}
                    response = await client.post('/v1/chat/turns', json=request.model_dump(mode='json'), headers=headers)
                    assert response.status_code == 503 and 'agent_text' not in response.json()
                    response = await client.post('/v1/chat/turns/stream', json=request.model_dump(mode='json'), headers=headers)
                    events = [json.loads(line) for line in response.text.splitlines()]
                    assert len(events)==1 and events[0]['event']=='error'
                    assert 'text' not in events[0] and 'agent_text' not in events[0]
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
            await runtime.close()
    asyncio.run(run())


def test_unavailable_memory_cannot_supply_cached_private_context_to_reply_model():
    async def run():
        state = turn_state('Tôi hỏi tiếp yêu cầu trước đó.')
        state.update(tool_failed=True, agent_draft='',
            reply_context={'reason':'memory_unavailable'},
            history=[{'customer':'PRIVATE CUSTOMER CONTEXT','agent':'PRIVATE ASSISTANT CONTEXT'}],
            session_tool_calls=old_lamp_reads(state))
        node, _ = nodes()
        node.llm.ainvoke.return_value = AIMessage(content=MODEL_REPLY)
        assert (await node.verify_agent(state))['agent_text'] == MODEL_REPLY
        messages = str(node.llm.ainvoke.await_args.args[0])
        assert 'PRIVATE CUSTOMER CONTEXT' not in messages and 'PRIVATE ASSISTANT CONTEXT' not in messages
        assert 'SKU-LAMP-A' not in messages
    asyncio.run(run())
