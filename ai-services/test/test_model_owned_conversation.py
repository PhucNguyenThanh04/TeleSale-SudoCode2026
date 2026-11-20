import asyncio
import json
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessageChunk

from test_text_harness_contract import turn_state, old_lamp_reads, nodes


def test_handoff_preserves_model_narrative_without_selecting_a_product_or_next_step():
    from datetime import datetime, timezone
    from app.agent.harness.handoff_brief import build_handoff_brief
    state=turn_state('Tôi cần trao đổi về cách kết nối bộ điều khiển sân khấu.')
    state.update(identity_status='known',customer_id='C-LOCAL',customer_phone='0900000011')
    state['session_tool_calls']=old_lamp_reads(state)
    proposal={'escalation_reason':'ngoai_pham_vi_tai_lieu',
        'conversation_summary':'Khách cần xác minh khả năng kết nối với bộ điều khiển sân khấu.',
        'next_action':'Nhân viên kiểm tra giao thức kết nối với kỹ thuật.',
        'open_questions':['Thiết bị hỗ trợ giao thức kết nối nào?'],
        'customer_phone':'0900000022'}
    brief=build_handoff_brief(state,proposal,lambda:datetime.now(timezone.utc))
    assert brief.conversation_summary==proposal['conversation_summary']
    assert brief.next_action==proposal['next_action']
    assert brief.open_questions==proposal['open_questions']
    assert brief.product_advised is None and brief.price_quoted_vnd is None
    assert brief.customer_phone=='0900000011'
    assert build_handoff_brief(state,{'escalation_reason':'khac'},lambda:datetime.now(timezone.utc)) is None


def test_memory_admission_preserves_model_classification_and_requires_source_quote():
    from app.agent.guardrails.checks import fact_evidence
    quote='Tôi cần thử với bộ điều khiển sân khấu trước khi quyết định.'
    result=fact_evidence('blocker',quote,'set',quote,[],quote)
    assert result.source=='customer' and result.normalized_value==quote
    objection='Giá này đắt quá so với dự kiến.'
    result=fact_evidence('objection','khac','set',objection,[],objection)
    assert result.source=='customer' and result.normalized_value=='khac'
    assert fact_evidence('blocker',quote,'set',quote,[]).source is None
    assert fact_evidence('blocker',quote,'set','Tôi cần thêm thông tin.',[],quote).source is None




@pytest.mark.parametrize('key,value,text,quote',[
    ('has_children','true','Tôi có con nhỏ.','Tôi có con nhỏ.'),
    ('payment','credit','Tôi trả bằng thẻ.','Tôi trả bằng thẻ.'),
    ('room_area_m2',-1,'Diện tích âm một mét vuông.','Diện tích âm một mét vuông.'),
    ('budget_vnd',500000,'Tôi dự kiến 700 nghìn.','Tôi dự kiến 700 nghìn.'),
    ('price_quoted_vnd',700000,'Giá bán là 700 nghìn.','Giá bán là 700 nghìn.'),
    ('blocker','Gọi 0901234567','Gọi 0901234567','Gọi 0901234567'),
])
def test_memory_admission_keeps_type_domain_source_and_pii_boundaries(key,value,text,quote):
    from app.agent.guardrails.checks import fact_evidence
    assert fact_evidence(key,value,'set',text,[],quote).source is None


def test_tool_query_is_not_rewritten_by_phrase_or_category_rules():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state=turn_state('Tôi đang tìm đèn dành cho người chụp ảnh.')
        node,gateway=nodes()
        business=BusinessTools(gateway,state,8,node.clock)
        query='Đèn Solstice cho người chụp ảnh'
        await business.invoke('catalog.search',{'query':query,'category':'đèn','max_price_vnd':400000})
        args=gateway.invoke.await_args.args[1]
        assert args['query']==query and args['category']=='đèn'
        assert args['max_price_vnd']==400000
    asyncio.run(run())


def test_variant_validation_does_not_infer_a_selection_from_customer_language():
    from app.agent.harness.policy import resolve_product_selection
    state=turn_state('Mẫu màu đỏ trước đây không phải mẫu màu xanh tôi đang hỏi.')
    state['tool_calls']=[{'name':'catalog.search','args':{},'result':{'items':[{
        'sku':'SKU-DESK','variants':[{'variant_sku':'SKU-DESK-RED','color':'đỏ'},
                                    {'variant_sku':'SKU-DESK-BLUE','color':'xanh'}]}]}}]
    state['scoped_facts']={'product':{'SKU-DESK':{'color':{'value':'đỏ','source_kind':'customer'}}},'room':{}}
    assert resolve_product_selection(state,{'sku':'SKU-DESK-BLUE'}).sku=='SKU-DESK-BLUE'
    assert resolve_product_selection(state,{'sku':'SKU-DESK'}).status=='selection_required'


def test_evidence_selection_uses_explicit_arguments_not_utterance_patterns():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    state=turn_state('Nếu mua hai chiếc thì tổng giá thay đổi như thế nào?')
    state['session_tool_calls']=old_lamp_reads(state)
    assert any(c['name']=='pricing.get_quote' for c in build_commerce_evidence(state))
    assert not any(c['name']=='pricing.get_quote' for c in build_commerce_evidence(state,
        args={'sku':'SKU-LAMP-A','qty':2}))


def test_context_excludes_legacy_inferred_plans_but_keeps_customer_narrative():
    from app.agent.harness.context import prompt_context
    state=turn_state('Tôi muốn tiếp tục trao đổi.')
    episode={'session_id':str(uuid4()),'topics':[{'scope_type':'global','scope_id':'',
        'customer_goal':'Tìm hiểu ánh sáng bàn làm việc.',
        'consultation':{'selected_sku':'SKU-UNWANTED','next_action':'purchase','accepted_offer':{'price_vnd':999}}}],
        'offer_candidates':[{'sku':'SKU-UNWANTED'}], 'basket_offers':[{'units':[]}]}
    state['current_episode']=episode
    state['episodes']=[episode]
    context=prompt_context(state,6)
    encoded=json.dumps(context,ensure_ascii=False)
    assert 'Tìm hiểu ánh sáng bàn làm việc.' in encoded
    assert 'accepted_offer' not in encoded and 'SKU-UNWANTED' not in encoded
    assert 'offer_candidates' not in encoded and 'basket_offers' not in encoded


@pytest.mark.parametrize('text',['Giá hôm nay bao nhiêu?','Tôi hỏi tiếp việc hôm trước.'])
def test_context_read_does_not_choose_commercial_tools_from_conversation(text):
    from app.agent.harness.context import load_context
    from test_deep_memory import FakeMemory
    async def run():
        state=turn_state(text)
        state['received_at_monotonic']=time.perf_counter()
        memory=FakeMemory()
        memory.read_context=AsyncMock(return_value={'history':[],'profile':{},'episodes':[{
            'session_id':str(uuid4()),'on':'2030-04-07','channel':'hotline','summary':'Khách tìm đèn bàn.',
            'outcome':'khac'}], 'scoped_facts':{'product':{'SKU-LAMP-A':{
                'product_advised':{'value':'SKU-LAMP-A','source_kind':'tool','on':'2030-04-07'},
                'price_quoted_vnd':{'value':199000,'source_kind':'tool','on':'2030-04-07'}}},'room':{}}})
        node,gateway=nodes()
        result=await load_context(state,memory,gateway,node.clock)
        assert result['call_brief'] and result['scoped_facts']['product']['SKU-LAMP-A']
        assert not gateway.invoke.called
        assert result['call_brief']['recommended_sku'] is None
        assert result['call_brief']['selected_sku'] is None
    asyncio.run(run())


def test_stopped_model_reply_waits_for_verification_without_keyword_task_classifiers():
    from app.agent.harness.streaming import GuardedStream
    async def run():
        state=turn_state('Tôi muốn xác nhận lại nội dung đã trao đổi.')
        sink=AsyncMock(return_value=True)
        stream=GuardedStream(sink)
        reply='Mình muốn làm rõ điều gì trước ạ?'
        await stream.feed(AIMessageChunk(content=reply,id='answer',response_metadata={'finish_reason':'stop'}),state)
        assert not stream.published and not sink.called
        state['agent_draft']=reply
        node,_=nodes()
        state.update(await node.verify_agent(state))
        await stream.finish(state['agent_text'],state)
        assert stream.published==reply and sink.await_count==1
    asyncio.run(run())


def test_memory_proposals_do_not_accept_a_deterministic_consultation_plan():
    from app.schemas.langmem import TopicProposal
    assert 'consultation' not in TopicProposal.model_fields


def test_privacy_request_reaches_model_before_any_handoff_action():
    from unittest.mock import patch
    from test_text_harness_contract import AgentReply
    async def run():
        state=turn_state('Tôi yêu cầu xóa hồ sơ cá nhân đã lưu.')
        node,gateway=nodes()
        agent=AgentReply()
        with patch('app.agent.harness.agent_nodes.build_agent',return_value=agent), patch(
                'app.agent.harness.agent_nodes.text_prompt',return_value='business contract'):
            result=await node.run_agent(state)
        assert agent.response.await_count==1
        assert not gateway.invoke.called
        assert result['agent_draft']=='Em đang trao đổi yêu cầu hiện tại với mình ạ.'
    asyncio.run(run())


def test_order_update_preserves_the_models_proposed_action():
    from app.agent.implementations.business_agent import BusinessTools
    async def run():
        state=turn_state('Tôi muốn đổi sản phẩm đã mua.')
        state['owned_order_ids']=['ORDER-1']
        state['crm_orders']=[{'order_id':'ORDER-1','variant_sku':'SKU-DESK-RED'}]
        state['tool_calls']=[{'name':'catalog.search','args':{},'result':{'items':[{
            'sku':'SKU-DESK','variants':[{'variant_sku':'SKU-DESK-RED','color':'đỏ'},
                                        {'variant_sku':'SKU-DESK-BLUE','color':'xanh'}]}]}}]
        node,gateway=nodes()
        business=BusinessTools(gateway,state,8,node.clock,authorize_write=AsyncMock(return_value=True))
        await business.invoke('order.update',{'order_id':'ORDER-1','action':'exchange_product','new_variant_sku':'SKU-DESK-BLUE'})
        assert gateway.invoke.await_args.args[1]['action']=='exchange_product'
    asyncio.run(run())


def test_late_tool_chunk_is_never_treated_as_a_customer_reply():
    from app.agent.harness.streaming import GuardedStream
    async def run():
        state=turn_state('Xin tư vấn.')
        sink=AsyncMock(return_value=True)
        stream=GuardedStream(sink)
        await stream.feed(AIMessageChunk(content='Em có thể hỗ trợ mình.',id='message'),state)
        await stream.feed(AIMessageChunk(content='',id='message',tool_call_chunks=[{
            'name':'catalog_search','args':'{}','id':'read','index':0}],response_metadata={'finish_reason':'stop'}),state)
        assert not sink.called
    asyncio.run(run())


def test_empty_langmem_output_does_not_trigger_a_customer_fact_rulebook():
    from unittest.mock import patch
    from app.agent.memory.langmem_extractor import extract_candidates
    from types import SimpleNamespace
    async def run():
        turn={'turn_id':str(uuid4()),'session_id':str(uuid4()),'customer_id':'owner-a',
              'on':'2030-04-08','channel':'hotline',
              'customer_text':'Phòng của tôi 17 mét vuông, ngân sách tám trăm nghìn đồng.',
              'agent_text':'Em sẽ dựa trên nhu cầu mình vừa cung cấp.'}
        manager=SimpleNamespace(ainvoke=AsyncMock(return_value=[]))
        with patch('app.agent.memory.langmem_extractor.create_memory_manager',return_value=manager):
            facts,episode=await extract_candidates(object(),[{'role':'user','content':json.dumps(turn)}],[])
        assert facts==[] and episode is None
        assert manager.ainvoke.await_count==1
    asyncio.run(run())


def test_worker_outcome_requires_observed_action_not_a_callback_keyword():
    from app.mcp_servers.mcp_memory.distiller_worker import process_one
    from app.schemas.langmem import CustomerCallEpisodeCandidate
    from test_langmem_worker import QueueTests
    from types import SimpleNamespace
    async def run():
        repo=QueueTests().repo()
        sid,tid=str(uuid4()),str(uuid4())
        job={'job_id':1,'customer_id':'owner-a','session_id':sid,'source_turn_id':tid,
             'attempts':1,'accepted_proposals':None,'tool_observations':[],'verified_outcome':'khac'}
        turn={'customer_text':'Ngày mai gọi lại giúp tôi nhé.','agent_text':'Mình cần xác nhận thời điểm gọi.',
              'on_date':'2030-04-08','channel':'hotline','client_msg_id':tid}
        repo.claim_distillation.return_value=job
        repo.distillation_turn.return_value=turn
        repo.recent_session_turns=AsyncMock(return_value=[turn])
        repo.is_erasure_blocked.return_value=False
        repo.save_distillation_proposals=AsyncMock()
        episode=CustomerCallEpisodeCandidate(customer_id='owner-a',session_id=sid,on='2030-04-08',
            channel='hotline',source_turn_ids=[tid],outcome='hen_goi_lai')
        extractor=AsyncMock(return_value=([],episode))
        projector=SimpleNamespace(list_fact_versions=AsyncMock(return_value=[]),
            list_episode_versions=AsyncMock(return_value=[]),put_facts=AsyncMock(return_value=[]),
            put_episode=AsyncMock())
        assert await process_one(repo,extractor,projector)
        stored=repo.save_distillation_proposals.await_args.args[2]
        assert stored['outcome']=='khac'
        assert stored['facts']==[]
        assert not any('consultation' in update for update in (stored.get('delta') or {}).get('topic_updates',[]))
    asyncio.run(run())


def test_claim_binding_does_not_guess_skus_from_brand_fragments():
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    calls=[{'name':'catalog.search','args':{},'result':{'items':[
        {'sku':'ITEM-A','name':'Đèn bàn Aurora','variants':[]},
        {'sku':'ITEM-B','name':'Đèn Aurora Pro','variants':[]}]}}]
    assert resolve_claim_skus('Aurora',calls)==set()
    assert resolve_claim_skus('Đèn Aurora Pro',calls)=={'ITEM-B'}
    assert resolve_claim_skus('ITEM-A',calls)=={'ITEM-A'}
