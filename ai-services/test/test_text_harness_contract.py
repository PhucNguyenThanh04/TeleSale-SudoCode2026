import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.context import _build_brief_orders, prompt_context
from app.schemas.agent import TextTurnRequest


def turn_state(text):
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
        channel='hotline', channel_identity='0900000011', on=date(2030, 4, 8),
        text=text, input_mode='clean')
    return {'request': request, 'safe_text': text, 'customer_id': 'owner-a',
        'customer_phone': request.channel_identity, 'identity_status': 'known',
        'history': [], 'profile': {}, 'scoped_facts': {'product': {}, 'room': {}},
        'episodes': [], 'current_episode': None, 'crm_orders': [], 'crm_sessions': [],
        'owned_order_ids': [], 'remembered_order_ids': [],
        'tool_calls': [], 'session_tool_calls': [], 'tool_count': 0}


def old_lamp_reads(state):
    on = state['request'].on.isoformat()
    return [
        {'name':'catalog.search', 'args':{'sku':'SKU-LAMP-A'}, 'result':{'total':1,
            'items':[{'sku':'SKU-LAMP-A','name':'Đèn bàn Aurora','category':'gia-dung/den',
                      'list_price_vnd':199000,'attributes':{},'variants':[]}]}},
        {'name':'pricing.get_quote', 'args':{'sku':'SKU-LAMP-A','on':on,'qty':1,
                                           'customer_phone':state['customer_phone']},
            'result':{'sku':'SKU-LAMP-A','list_price_vnd':199000,'final_price_vnd':199000,
                      'applied_promos':[], 'freeship':False}},
        {'name':'inventory.check','args':{'sku':'SKU-LAMP-A','on':on},
            'result':{'sku':'SKU-LAMP-A','in_stock':True,'qty':4}},
    ]


def nodes():
    gateway = SimpleNamespace(invoke=AsyncMock(return_value={'error':'unexpected_tool'}))
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(
        content='Mình cần làm rõ yêu cầu nào trước ạ?')),
        with_structured_output=Mock(return_value=SimpleNamespace(ainvoke=AsyncMock(
            return_value={'supported':True, 'reason':'supported', 'unsupported_claim':''}))))
    return AgentNodes(llm, gateway, object(), 6, 6,
                      lambda: datetime(2030, 4, 8, tzinfo=timezone.utc)), gateway


class AgentReply:
    def __init__(self):
        self.response = AsyncMock(return_value={
            'messages':[AIMessage(content='Em đang trao đổi yêu cầu hiện tại với mình ạ.')]})

    async def astream(self, inputs, **kwargs):
        yield 'values', await self.response(inputs)


@pytest.mark.parametrize('text', [
    'Đèn bàn Aurora giá bao nhiêu?',
    'Tôi chọn SKU-LAMP-A, giá 199000đ; đồng ý mua một chiếc.',
    'Ngày 9 tháng 4 lúc 10 giờ gọi lại cho tôi nhé.',
    'Tôi muốn nói chuyện với nhân viên phụ trách.',
])
def test_current_request_reaches_model_before_any_business_action(text):
    async def run():
        state = turn_state(text)
        state['session_tool_calls'] = old_lamp_reads(state)
        node, gateway = nodes()
        agent = AgentReply()
        with patch('app.agent.harness.agent_nodes.build_agent', return_value=agent), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='business contract'):
            result = await node.run_agent(state)
        assert agent.response.await_count == 1
        assert agent.response.await_args.args[0]['messages'][-1].content == text
        assert not gateway.invoke.called
        assert result['agent_draft'] == 'Em đang trao đổi yêu cầu hiện tại với mình ạ.'
    asyncio.run(run())


def test_prompt_does_not_present_a_heuristic_decision_as_customer_authority():
    state = turn_state('Tôi đang tìm hiểu, chưa quyết định thao tác nào.')
    state['session_tool_calls'] = old_lamp_reads(state)
    context = prompt_context(state, 6)
    assert 'consultation' not in context
    assert context['customer_text'] == state['safe_text']
    assert context['tool_observations']


def test_order_ids_without_details_do_not_fabricate_status_or_variant():
    state = turn_state('Kiểm tra đơn giúp tôi.')
    state['remembered_order_ids'] = ['ORDER-A', 'ORDER-B']
    products = {'SKU-LAMP-A': {'variant_sku': {'value':'SKU-LAMP-A-WHITE'}}}
    orders = _build_brief_orders(state, state['remembered_order_ids'], {}, products)
    assert orders == [{'order_id':'ORDER-A','status':'unknown'},
                      {'order_id':'ORDER-B','status':'unknown'}]


def test_rejected_answer_does_not_turn_into_an_unrequested_cached_price():
    async def run():
        state = turn_state('Mình cần làm rõ cách xử lý yêu cầu này.')
        state['session_tool_calls'] = old_lamp_reads(state)
        state['agent_draft'] = 'Em đã xóa toàn bộ dữ liệu cá nhân của mình.'
        node, _ = nodes()
        result = await node.verify_agent(state)
        assert '199.000' not in result['agent_text']
        assert node.llm.ainvoke.await_count == 1
        assert result['agent_text'] == 'Mình cần làm rõ yêu cầu nào trước ạ?'
    asyncio.run(run())


@pytest.mark.parametrize('name,args', [
    ('order.create', {'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'}),
    ('order.update', {'order_id':'ORDER-A','action':'return','reason':'customer request'}),
    ('schedule.callback', {'callback_at':'2030-04-09T10:00'}),
])
def test_every_customer_write_requires_current_semantic_authorization(name, args):
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Tôi chọn SKU-LAMP-A giá 199000đ, đồng ý mua một chiếc.')
        state['session_tool_calls'] = old_lamp_reads(state)
        state['owned_order_ids'] = ['ORDER-A']
        node, gateway = nodes()
        business = BusinessTools(gateway, state, 6, node.clock)
        business.authorize_write = AsyncMock(return_value=False)
        result = await business.invoke(name, args)
        assert result['error'] == 'customer_authorization_required'
        assert business.authorize_write.await_count == 1
        assert not gateway.invoke.called
    asyncio.run(run())


def test_missing_authorization_service_fails_closed_for_writes():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Gọi lại vào sáng mai nhé.')
        node, gateway = nodes()
        business = BusinessTools(gateway, state, 6, node.clock)
        result = await business.invoke('schedule.callback', {'callback_at':'2030-04-09T10:00'})
        assert result['error'] == 'customer_authorization_required'
        assert not gateway.invoke.called
    asyncio.run(run())


def test_write_retry_key_does_not_depend_on_number_of_read_tools():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Gọi lại vào sáng mai lúc 10 giờ nhé.')
        node, _ = nodes()
        gateway = SimpleNamespace(invoke_trusted=AsyncMock(return_value={
            'callback_id':'CALLBACK-A','callback_at':'2030-04-09T10:00'}))
        for count in (0, 3):
            current = {**state, 'tool_calls':[], 'tool_count':count}
            business = BusinessTools(gateway, current, 6, node.clock)
            business.authorize_write = AsyncMock(return_value=True)
            await business.invoke('schedule.callback', {'callback_at':'2030-04-09T10:00'})
        first, second = gateway.invoke_trusted.await_args_list
        assert first.args[5] == second.args[5]
    asyncio.run(run())


@pytest.mark.parametrize('allowed', [False, True])
def test_agent_write_is_checked_against_the_entire_current_customer_turn(allowed):
    async def run():
        text = 'Ngày mai lúc 10 giờ gọi lại cho tôi; không tự đặt mua hàng.'
        state = turn_state(text)
        node, gateway = nodes()
        assessment = SimpleNamespace(ainvoke=AsyncMock(return_value={
            'allowed':allowed, 'basis':'customer_request' if allowed else 'none',
            'customer_quote':text, 'reason':'current request'}))
        node.llm.with_structured_output = Mock(return_value=assessment)

        class CallbackAgent:
            def __init__(self, business):
                self.business = business

            async def astream(self, inputs, **kwargs):
                await self.business.invoke('schedule.callback', {'callback_at':'2030-04-09T10:00'})
                yield 'values', {'messages':[AIMessage(content='Em đã tiếp nhận yêu cầu hiện tại.')]}

        with patch('app.agent.harness.agent_nodes.build_agent',
                   side_effect=lambda kind, llm, business, prompt: CallbackAgent(business)), \
             patch('app.agent.harness.agent_nodes.text_prompt', return_value='business contract'):
            await node.run_agent(state)
        assert assessment.ainvoke.await_count == 1
        assert text in assessment.ainvoke.await_args.args[0][-1].content
        assert gateway.invoke.await_count == int(allowed)
    asyncio.run(run())


def test_approved_order_uses_tool_evidence_without_a_second_language_rule_engine():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Please place my lamp order.')
        state['session_tool_calls'] = old_lamp_reads(state)
        node, gateway = nodes()
        gateway.invoke.return_value = {'status':'created','order_id':'ORDER-NEW'}
        business = BusinessTools(gateway, state, 6, node.clock)
        business.authorize_write = AsyncMock(return_value=True)
        result = await business.invoke('order.create', {
            'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'})
        assert result.get('status') == 'created'
        assert gateway.invoke.await_count == 1
    asyncio.run(run())


def test_missing_catalog_evidence_returns_to_agent_without_an_implicit_lookup():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Tôi đồng ý mua SKU-LAMP-A giá 199000đ.')
        node, gateway = nodes()
        business = BusinessTools(gateway, state, 6, node.clock)
        business.authorize_write = AsyncMock(return_value=True)
        result = await business.invoke('order.create', {
            'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'})
        assert 'error' in result
        assert not gateway.invoke.called
    asyncio.run(run())


@pytest.mark.parametrize('missing', ['pricing.get_quote','inventory.check'])
def test_semantic_approval_never_bypasses_missing_commercial_evidence(missing):
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Please place my lamp order.')
        state['session_tool_calls'] = [r for r in old_lamp_reads(state) if r['name'] != missing]
        node, gateway = nodes()
        business = BusinessTools(gateway, state, 6, node.clock)
        business.authorize_write = AsyncMock(return_value=True)
        result = await business.invoke('order.create', {
            'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'})
        assert 'error' in result
        assert not gateway.invoke.called
    asyncio.run(run())


def test_expired_or_inactive_memory_is_not_presented_as_active_customer_facts():
    state = turn_state('Tôi muốn tiếp tục trao đổi.')
    state['profile'] = {
        'budget_vnd': {'value':2000000,'source_kind':'customer','on':'2029-01-01',
                       'valid_until':'2030-04-07','status':'active'},
        'payment': {'value':'COD','source_kind':'customer','status':'deleted'},
    }
    context = prompt_context(state, 6)
    assert 'budget_vnd' not in context['customer_facts']
    assert 'payment' not in context['customer_facts']


def test_langmem_cannot_turn_agent_advice_into_customer_goal():
    from app.mcp_servers.mcp_memory.services.langmem_admission import admit_episode_candidate
    from app.schemas.langmem import CustomerCallEpisodeCandidate

    customer_id, session_id, turn_id = str(uuid4()), str(uuid4()), str(uuid4())
    quote = 'Tôi muốn mua chiếc đèn này.'
    candidate = CustomerCallEpisodeCandidate(customer_id=customer_id, session_id=session_id,
        on=date(2030, 4, 8), channel='hotline', source_turn_ids=[turn_id],
        customer_goal={'text':quote,'evidence_quote':quote})
    committed = [{'customer_id':customer_id,'session_id':session_id,'turn_id':turn_id,
                  'customer_text':'Tôi chỉ đang tìm hiểu.', 'agent_text':quote}]
    assert admit_episode_candidate(customer_id, session_id, candidate, committed, []) is None


def test_default_tool_budget_allows_a_normal_verified_order():
    from app.agent.implementations.business_agent import BusinessTools
    from app.constants import DEFAULT_MAX_TOOL_CALLS

    async def run():
        state = turn_state('Tôi đồng ý mua đúng chiếc đèn đã chọn.')
        results = {r['name']:r['result'] for r in old_lamp_reads(state)}
        results['order.create'] = {'status':'created','order_id':'ORDER-NEW'}
        gateway = SimpleNamespace(invoke=AsyncMock(side_effect=lambda name, args: results[name]))
        node, _ = nodes()
        business = BusinessTools(gateway, state, DEFAULT_MAX_TOOL_CALLS, node.clock)
        business.authorize_write = AsyncMock(return_value=True)
        for name in ['catalog.search','inventory.check','pricing.get_quote']:
            result = await business.invoke(name, {'sku':'SKU-LAMP-A'})
            assert 'error' not in result
        result = await business.invoke('order.create', {
            'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'})
        assert result.get('status') == 'created'
    asyncio.run(run())


def test_partial_model_text_is_not_published_before_late_tool_calls_are_known():
    from app.agent.harness.streaming import GuardedStream
    from langchain_core.messages import AIMessageChunk

    async def run():
        state = turn_state('Xin chào.')
        sink = AsyncMock(return_value=True)
        stream = GuardedStream(sink)
        await stream.feed(AIMessageChunk(content='Em sẵn sàng hỗ trợ mình. ', id='message-a'), state)
        await stream.feed(AIMessageChunk(content='', id='message-a', tool_call_chunks=[{
            'name':'catalog_search','args':'{"sku":"SKU-LAMP-A"}','id':'call-a','index':0}]), state)
        assert not sink.called
        assert stream.published == ''
    asyncio.run(run())


def test_http_text_turn_requires_internal_auth_even_without_verified_identity():
    from fastapi import HTTPException
    from app.api.chat import create_text_turn
    from app.schemas.agent import ChatRequest

    async def run():
        request = turn_state('Xin chào.')['request']
        turn = ChatRequest.model_validate(request.model_dump())
        with patch('app.api.chat.get_settings', return_value=SimpleNamespace(ai_internal_token=None)), \
             patch('app.api.chat.chat', new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await create_text_turn(turn, SimpleNamespace(headers={}), object())
        assert exc.value.status_code == 401
    asyncio.run(run())


def test_quote_for_another_customer_cannot_authorize_an_order():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Tôi chọn SKU-LAMP-A giá 199000đ, đồng ý mua một chiếc.')
        state['session_tool_calls'] = old_lamp_reads(state)
        state['session_tool_calls'][1]['args']['customer_phone'] = '0900000099'
        node, gateway = nodes()
        gateway.invoke.return_value = {'status':'created','order_id':'ORDER-NEW'}
        business = BusinessTools(gateway, state, 8, node.clock)
        business.authorize_write = AsyncMock(return_value=True)
        result = await business.invoke('order.create', {
            'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000,'payment':'COD'})
        assert 'error' in result
        assert not gateway.invoke.called
    asyncio.run(run())


def test_previous_purchase_invalidates_cached_quotes_for_the_next_turn():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence

    state = turn_state('Tôi đang cân nhắc mua thêm một chiếc nữa.')
    state['session_tool_calls'] = old_lamp_reads(state) + [{
        'name':'order.create','args':{'sku':'SKU-LAMP-A','price_vnd':199000},
        'result':{'order_id':'ORDER-EARLIER','status':'created'},
    }]
    assert not any(c['name'] == 'pricing.get_quote' for c in build_commerce_evidence(state))


def test_new_owned_quote_survives_discarding_foreign_observations():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence

    state = turn_state('Kiểm tra lại báo giá cho tôi.')
    state['session_tool_calls'] = [
        {**read, 'customer_id':'other-owner'} for read in old_lamp_reads(state)
    ] + [{'name':'order.create','args':{},'result':{'status':'created','order_id':'ORDER-OLD'}}]
    fresh = old_lamp_reads(state)[1]
    state['tool_calls'] = [fresh]
    assert fresh in build_commerce_evidence(state)


def test_completed_write_is_reported_by_llm_when_initial_generation_fails():

    async def run():
        state = turn_state('Tôi đã đồng ý đơn mua đèn.')
        state['session_tool_calls'] = old_lamp_reads(state)
        state['tool_calls'] = [{
            'name':'order.create','args':{'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000},
            'result':{'order_id':'ORDER-COMMITTED','status':'created'},
        }]
        state['agent_draft'] = ''
        node, _ = nodes()
        node.llm.ainvoke.return_value = AIMessage(content='Em đã tạo đơn ORDER-COMMITTED cho mình.')
        result = await node.verify_agent(state)
        assert 'ORDER-COMMITTED' in result['agent_text']
        assert node.llm.ainvoke.await_count == 1
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['business', 'policy', 'release'])
def test_mcp_transport_has_a_bounded_deadline(kind):
    from app.agent.mcp.gateway import MCPGateway

    class SlowClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            await asyncio.sleep(0.03)
            return self

        async def __aexit__(self, *args):
            pass

        async def call_tool(self, *args, **kwargs):
            return SimpleNamespace(is_error=False, data={'items':[]})

    async def run():
        gateway = MCPGateway('catalog', 'order', 'memory', knowledge='knowledge', context_secret='secret')
        real_timeout = asyncio.timeout
        with patch('app.agent.mcp.gateway.Client', SlowClient), \
             patch('app.agent.mcp.gateway.asyncio.timeout', side_effect=lambda _: real_timeout(0.002)):
            if kind == 'release':
                with pytest.raises(RuntimeError, match='Knowledge release cannot be pinned'):
                    await gateway.knowledge_release()
            else:
                name, args = (('catalog.search', {'query':'lamp'}) if kind == 'business' else
                              ('policy.search', {'query':'warranty','on':'2030-04-08'}))
                result = await gateway.invoke(name, args)
                assert result.get('error') == ('mcp_unavailable' if kind == 'business'
                                               else 'knowledge_unavailable')
    asyncio.run(run())


def test_anonymous_evidence_is_durable_and_used_after_identity_verification():
    from test_mcp_memory import TurnRepo
    from app.mcp_servers.mcp_memory.services.memory import write

    async def run():
        repo = TurnRepo()
        sid, tid = str(uuid4()), str(uuid4())
        observed = [{'name':'catalog.search','args':{'sku':'SKU-LAMP-A'},
                     'result':{'items':[{'sku':'SKU-LAMP-A','name':'Đèn Aurora'}]}}]
        data = {'customer_text':'Tôi đang tìm hiểu đèn bàn.', 'agent_text':'Em có thể tư vấn.',
                'on':'2030-04-08','channel':'hotline','client_msg_id':tid,
                'tool_observations':observed}
        await write(repo, 'commit_turn', None, sid, data)
        assert repo.rows[sid][0]['tool_observations'] == observed
        reopened = TurnRepo()
        reopened.rows = repo.rows
        reopened.enqueue_distillation = AsyncMock()
        await write(reopened, 'commit_turn', 'owner-a', sid,
                    {**data,'client_msg_id':str(uuid4()),'tool_observations':[]})
        earlier = reopened.enqueue_distillation.await_args_list[0]
        assert earlier.args[3:5] == (tid, observed)
    asyncio.run(run())


def test_postgres_turn_write_and_attribution_include_durable_evidence():
    import json
    from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo

    async def run():
        repo = object.__new__(MemoryRepo)
        conn = SimpleNamespace(execute=AsyncMock(), fetch=AsyncMock(return_value=[]))
        sid, tid = str(uuid4()), str(uuid4())
        observed = [{'name':'catalog.search','args':{},'result':{'items':[]}}]
        await repo.insert_turn(conn, sid, 1, None, 'hotline', date(2030,4,8),
                               'Xin chào', 'Chào mình', tid, observed, 'khac')
        args = conn.execute.await_args.args
        assert 'tool_observations,verified_outcome' in args[0]
        assert json.loads(args[-2]) == observed and args[-1] == 'khac'
        await repo.attribute_anonymous_turns(conn, sid, 'owner-a')
        assert 'tool_observations,verified_outcome' in conn.fetch.await_args.args[0]
    asyncio.run(run())


@pytest.mark.parametrize('name,args,result,reply', [
    ('schedule.callback', {'callback_at':'2030-04-09T10:00'},
     {'callback_id':'CB123','callback_at':'2030-04-09T10:00'}, 'Em đã đặt lịch gọi lại cho mình.'),
    ('handoff.transfer', {}, {'ticket_id':'HT123','status':'queued'}, 'Em đã chuyển yêu cầu đến nhân viên phụ trách.'),
    ('order.update', {'order_id':'ORDER-A','action':'return'},
     {'order_id':'ORDER-A','action':'return','status':'pickup_scheduled'},
     'Em đã ghi nhận yêu cầu trả hàng cho đơn ORDER-A.'),
    ('order.update', {'order_id':'ORDER-A','action':'update_address'},
     {'order_id':'ORDER-A','action':'update_address','status':'updated'},
     'Em đã ghi nhận yêu cầu thay đổi nơi giao cho đơn ORDER-A.'),
])
def test_completed_side_effect_is_acknowledged_by_llm_after_initial_generation_failure(name, args, result, reply):
    async def run():
        state = turn_state('Tôi đồng ý yêu cầu này.')
        state['tool_calls'] = [{'name':name,'args':args,'result':result}]
        state['agent_draft'] = ''
        node, _ = nodes()
        node.llm.ainvoke.return_value = AIMessage(content=reply)
        answer = (await node.verify_agent(state))['agent_text']
        assert answer == reply and node.llm.ainvoke.await_count == 1
    asyncio.run(run())


@pytest.mark.parametrize('assessment', [
    {'allowed':'true','basis':'customer_request','customer_quote':'Đồng ý.','reason':'x'},
    {'allowed':True,'basis':'customer_request','customer_quote':'Tôi muốn mua.','reason':'x'},
    {'allowed':True,'basis':'policy_handoff','customer_quote':'Đồng ý.','reason':'x'},
    {'allowed':True,'basis':'none','customer_quote':'Đồng ý.','reason':'x'},
])
def test_semantic_authorizer_rejects_malformed_or_unattributed_approval(assessment):
    from app.agent.harness.authorization import authorize_write

    async def run():
        state = turn_state('Đồng ý.')
        model = SimpleNamespace(with_structured_output=Mock(return_value=SimpleNamespace(
            ainvoke=AsyncMock(return_value=assessment))))
        assert await authorize_write(model, state, 'order.create', {}, 6) is False
    asyncio.run(run())


def test_pii_masking_is_idempotent_across_context_verification_and_memory():
    from app.mcp_servers.mcp_shared.pii import mask_pii

    once = mask_pii('Địa chỉ: 24 đường Hoa. Email: someone@example.invalid; SĐT 0900000011.')
    assert mask_pii(once) == once
    assert mask_pii(mask_pii(once)) == once


@pytest.mark.parametrize('address_text,expected', [
    ('Địa chỉ: 24 đường Hoa, Hà Nội.', '24 đường Hoa, Hà Nội'),
    ('Tôi chưa cung cấp địa chỉ giao hàng.', None),
])
def test_masked_delivery_address_never_reaches_business_tools_as_a_literal(address_text, expected):
    from app.agent.implementations.business_agent import BusinessTools
    from app.mcp_servers.mcp_shared.pii import mask_pii

    async def run():
        state = turn_state(address_text)
        state['safe_text'] = mask_pii(address_text)
        state['session_tool_calls'] = old_lamp_reads(state)
        node, gateway = nodes()
        gateway.invoke.return_value = old_lamp_reads(state)[1]['result']
        result = await BusinessTools(gateway, state, 8, node.clock).invoke('pricing.get_quote', {
            'sku':'SKU-LAMP-A','address':'[ĐỊA CHỈ ĐÃ ẨN]'})
        if expected is None:
            assert 'error' in result and not gateway.invoke.called
        else:
            assert gateway.invoke.await_args.args[1]['address'] == expected
            assert expected not in str(prompt_context(state, 6))
    asyncio.run(run())


def test_explicit_tool_selection_is_not_reinterpreted_by_a_language_rule_engine():
    from app.agent.harness.policy import catalog_variant

    state = turn_state('Trước đây tôi dùng màu trắng; tôi đang hỏi chiếc màu đen.')
    state['tool_calls'] = [{'name':'catalog.search','args':{},'result':{'items':[{
        'sku':'SKU-LAMP','variants':[
            {'variant_sku':'SKU-LAMP-BLACK','size':1,'color':'đen'},
            {'variant_sku':'SKU-LAMP-WHITE','size':1,'color':'trắng'}]}]}}]
    assert catalog_variant(state, {'sku':'SKU-LAMP-BLACK'}) == 'SKU-LAMP-BLACK'
    assert catalog_variant(state, {'sku':'SKU-LAMP','color':'đen'}) == 'SKU-LAMP-BLACK'


@pytest.mark.parametrize('approved', [False, True])
def test_real_graph_executes_only_model_proposed_and_authorized_purchase(approved):
    from app.agent.harness.runtime import AgentHarnessRuntime
    from test_deep_memory import FakeToolModel, FakeMemory

    class Model(FakeToolModel):
        def with_structured_output(self, schema, **kwargs):
            from app.agent.guardrails.semantic_grounding import GroundingReview
            if schema is GroundingReview:
                return super().with_structured_output(schema, **kwargs)
            return SimpleNamespace(ainvoke=AsyncMock(return_value={
                'allowed':approved,'basis':'customer_request' if approved else 'none',
                'customer_quote':'Tôi đồng ý mua một đèn Aurora giá 199000đ.',
                'reason':'current customer request'}))

    async def run():
        state = turn_state('Tôi đồng ý mua một đèn Aurora giá 199000đ.')
        replies = [AIMessage(content='', tool_calls=[{
                'name':'catalog_search','args':{'sku':'SKU-LAMP-A'},'id':'catalog-1'}]),
            AIMessage(content='', tool_calls=[
                {'name':'inventory_check','args':{'sku':'SKU-LAMP-A'},'id':'stock-1'},
                {'name':'pricing_get_quote','args':{'sku':'SKU-LAMP-A'},'id':'quote-1'}]),
            AIMessage(content='', tool_calls=[{'name':'order_create','args':{
                'sku':'SKU-LAMP-A','price_vnd':199000,'qty':1,'payment':'COD'},'id':'order-1'}]),
            AIMessage(content=('Em đã tạo đơn OD555001 cho mình.' if approved
                               else 'Em chưa thể tạo đơn cho mình.'))]
        model = Model(replies=replies)
        results = {c['name']:c['result'] for c in old_lamp_reads(state)}
        results.update({'crm.get_customer':{'found':True,'customer_id':'owner-a',
            'phone':'0900000011','orders':[],'sessions':[]},
            'order.create':{'status':'created','order_id':'OD555001'}})
        gateway = SimpleNamespace(invoke=AsyncMock(side_effect=lambda name, args: results[name]))
        memory = FakeMemory()
        runtime = AgentHarnessRuntime(model, gateway, memory)
        try:
            response = await runtime.run(state['request'])
            assert response.memory_update.turn_saved
            assert ('OD555001' in response.agent_text) is approved
            calls = [c.args[0] for c in gateway.invoke.await_args_list]
            assert calls.count('order.create') == int(approved)
            assert calls.count('catalog.search') == calls.count('pricing.get_quote') == 1
            assert memory.turns[str(state['request'].session_id)][0]['agent'] == response.agent_text
            seen = len(model.seen)
            assert (await runtime.run(state['request'])).agent_text == response.agent_text
            assert len(model.seen) == seen and len(gateway.invoke.await_args_list) == len(calls)
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('changed_price', [False, True])
def test_basket_write_requires_exact_owned_physical_unit_prices(changed_price):
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = turn_state('Tôi đồng ý mua hai đèn theo báo giá đã trao đổi.')
        state['session_tool_calls'] = old_lamp_reads(state) + [{
            'name':'pricing.quote_order','args':{'on':'2030-04-08','customer_phone':'0900000011',
                'lines':[{'sku':'SKU-LAMP-A','qty':2}]},
            'result':{'units':[{'sku':'SKU-LAMP-A','final_price_vnd':199000},
                               {'sku':'SKU-LAMP-A','final_price_vnd':100000}], 'total_vnd':299000}}]
        node, gateway = nodes()
        gateway.invoke.return_value = {'status':'created','order_id':'OD555001'}
        business = BusinessTools(gateway, state, 8, node.clock,
                                 authorize_write=AsyncMock(return_value=True))
        result = await business.invoke('order.create', {'payment':'bank','lines':[
            {'sku':'SKU-LAMP-A','qty':1,'price_vnd':199000},
            {'sku':'SKU-LAMP-A','qty':1,'price_vnd':100000+int(changed_price)}]})
        if changed_price:
            assert result['error'] == 'purchase_evidence_required'
            assert 'pricing.quote_order' in result['next_tools']
            assert not gateway.invoke.called
        else:
            assert result['status'] == 'created' and gateway.invoke.await_count == 1
    asyncio.run(run())


def test_brackets_do_not_bypass_address_masking():
    from app.mcp_servers.mcp_shared.pii import mask_pii

    assert 'Đống Đa, Hà Nội' not in mask_pii('[Địa chỉ: Đống Đa, Hà Nội]')
