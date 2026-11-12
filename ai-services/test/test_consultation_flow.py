"""Offline consultation decisions must not invent customer consent."""
from types import SimpleNamespace
from datetime import date
from copy import deepcopy
import pytest
from app.schemas.consultation import ConsultationSnapshot, ConsultationDecision


def state(text='Tư vấn giúp tôi', items=None):
    products=items if items is not None else [
        {'sku':'SKU-ASTER','name':'Aster','variants':[], 'list_price_vnd':900000,
         'attributes':{'room_area_m2':35,'child_safe_lock':True}},
        {'sku':'SKU-BRIO','name':'Brio','variants':[], 'list_price_vnd':800000,
         'attributes':{'room_area_m2':30,'child_safe_lock':False}}]
    return {'request':SimpleNamespace(session_id='s',client_msg_id='t',on=date(2026,11,5)),
            'customer_id':'C','identity_status':'known','safe_text':text,'history':[], 'profile':{},
            'episodes':[], 'scoped_facts':{},'tool_calls':[{'name':'catalog.search','args':{},
            'result':{'items':products}}], 'session_tool_calls':[]}


def quoted(s,sku='SKU-ASTER',price=900000,qty=1,promos=None):
    s['tool_calls'] += [{'name':'pricing.get_quote','args':{'sku':sku,'on':'2026-11-05','qty':qty},
        'result':{'sku':sku,'final_price_vnd':price,'applied_promos':promos or []}},
        {'name':'inventory.check','args':{'sku':sku,'on':'2026-11-05'},
         'result':{'sku':sku,'in_stock':True,'qty':10}}]
    return s


def test_snapshot_and_runtime_permission_are_separate():
    snap=ConsultationSnapshot(candidates=['SKU-ASTER'])
    assert snap.selected_sku is None and snap.accepted_offer is None
    assert 'purchase_intent' not in snap.model_dump()
    with pytest.raises(ValueError): ConsultationSnapshot(purchase_intent=True)
    assert ConsultationDecision(snapshot=snap).purchase_intent is False


def decision(s):
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    return derive_consultation(s)


def test_named_choice_and_deictic_focus():
    assert decision(state('Tôi chọn Aster để xem giá.')).snapshot.selected_sku=='SKU-ASTER'
    assert not decision(state('Tôi chọn Aster để xem giá.')).purchase_intent
    assert decision(state('Cho tôi xem thêm Aster.')).snapshot.selected_sku is None
    s=state('Lấy mẫu này, lên đơn giúp tôi.')
    s['history']=[{'customer':'Tư vấn giúp tôi','agent':'Em đề xuất Aster phù hợp diện tích phòng, giá 900.000đ.'}]
    d=decision(quoted(s));assert d.snapshot.selected_sku=='SKU-ASTER' and d.purchase_intent
    s['history'][0]['agent']='Em tìm thấy Aster và Brio.'
    assert decision(s).snapshot.selected_sku is None


def test_budget_ceiling_and_offer_scoped_consent():
    s=state('Ngân sách tầm 800k, tôi chọn Aster để xem giá.')
    d=decision(quoted(s));assert d.snapshot.budget.limit_vnd==800000
    assert d.snapshot.accepted_offer is None
    s['history']=[{'customer':'Ngân sách tối đa 800k.','agent':'Aster giá 900.000đ, vượt 100.000đ.'}]
    s['safe_text']='Đồng ý mua Aster với giá 900.000đ, lên đơn nhé.'
    d=decision(s)
    assert d.snapshot.budget.limit_vnd==800000
    assert d.snapshot.accepted_offer.price_vnd==900000
    assert d.purchase_intent


def test_delegation_requires_unique_eligible_variant():
    s=quoted(state('Chọn giúp tôi một mẫu dưới 1 triệu rồi lên đơn.'))
    d=decision(s)
    assert d.snapshot.delegation.status=='active'
    assert d.snapshot.selected_sku is None  # two plausible products, not quote-count guessing
    s['tool_calls'][0]['result']['items']=s['tool_calls'][0]['result']['items'][:1]
    d=decision(s);assert d.snapshot.selected_sku=='SKU-ASTER'


def test_gate_requires_current_evidence_and_permission():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Lấy Aster giá 900.000đ, lên đơn.'))
    args={'sku':'SKU-ASTER','price_vnd':900000,'qty':1}
    assert purchase_block_reason(s,args) is None
    s['safe_text']='Tôi muốn xem giá Aster.'
    assert purchase_block_reason(s,args)=='purchase_permission_required'
    s['safe_text']='Lấy Aster giá 900.000đ, lên đơn.'
    s['session_tool_calls']=s.pop('tool_calls');s['tool_calls']=[]
    assert purchase_block_reason(s,args) is None  # same session observations
    s['session_tool_calls']=[c for c in s['session_tool_calls'] if c['name']!='inventory.check']
    assert purchase_block_reason(s,args)=='current_stock_required'


def test_current_negation_revokes_choice_and_permission():
    s=quoted(state('Chưa mua Aster nhé.'))
    s['history']=[{'customer':'Tôi chọn Aster.','agent':'Aster giá 900.000đ.'}]
    d=decision(s);assert d.snapshot.selected_sku is None and not d.purchase_intent


def test_gold_permission_labels_are_independent_of_scenario_ids():
    import json
    from pathlib import Path
    cases=json.loads((Path(__file__).parents[1]/'eval_harness/fixtures/consultation_flow_labels.json').read_text())['cases']
    for case in cases:
        s=state(case['text']);s.update(scenario_id='anything',ground_truth_facts={'sku':'WRONG'},success_if={'sku':'WRONG'})
        d=decision(s)
        assert bool(d.snapshot.selected_sku)==case['selected'], case['text']
        assert d.purchase_intent==case['buy'], case['text']


def test_category_negation_and_negative_purchase_are_distinct():
    s=quoted(state('Mua máy lọc không khí Aster giá 900.000đ, lên đơn.'))
    assert decision(s).purchase_intent
    assert not decision(state('Không mua Aster.')).purchase_intent


def test_new_selection_cannot_keep_old_offer_and_previous_delegation_is_not_current_permission():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Tôi chọn Brio để xem giá.'))
    s['history']=[{'customer':'Mua Aster giá 900.000đ.','agent':'Aster đã chọn.'}]
    assert decision(s).snapshot.accepted_offer is None
    snap={'selected_sku':'SKU-ASTER','delegation':{'status':'active','constraints':{'limit_vnd':1000000}},
          'source_refs':{'selected_sku':{'customer_id':'C','session_id':'old','source_turn_id':'old-t','source_kind':'customer','evidence_quote':'Chọn giúp Aster rồi đặt.'},
                         'delegation':{'customer_id':'C','session_id':'old','source_turn_id':'old-t','source_kind':'customer','evidence_quote':'Chọn giúp Aster rồi đặt.'}}}
    s=quoted(state('Lên đơn mẫu hôm trước.'));s['episodes']=[{'on_date':'2026-11-04','topics':[{'scope_type':'global','consultation':snap}]}]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':900000})=='offer_confirmation_required'


def test_business_gateway_cannot_create_from_catalog_or_quote_alone():
    import asyncio
    from unittest.mock import AsyncMock
    from app.agent.implementations.business_agent import BusinessTools
    s=quoted(state('Xem giá Aster.'));s['request'].channel='hotline';s['request'].channel_identity=None
    gateway=AsyncMock();gateway.invoke_trusted.return_value={'status':'created','order_id':'OD-FAKE'}
    out=asyncio.run(BusinessTools(gateway,s,8,lambda:None).invoke('order.create',{'sku':'SKU-ASTER','price_vnd':900000}))
    assert out['error']=='purchase_permission_required'
    assert gateway.invoke_trusted.await_count==0


def test_bounded_read_preparation_uses_quote_not_list_price():
    import asyncio
    from app.agent.implementations.business_agent import BusinessTools
    from unittest.mock import AsyncMock
    s=state('Ngân sách tối đa 850k, tư vấn giúp tôi.');s['request'].channel='hotline';s['request'].channel_identity=None
    s['tool_calls'][0]['args'] = {'category': 'air'}
    for item in s['tool_calls'][0]['result']['items']:
        item['category'] = 'air'
    async def invoke(name,args,*a,**kw):
        if name=='pricing.get_quote':return {'sku':args['sku'],'final_price_vnd':800000,'applied_promos':[]}
        raise AssertionError('only bounded price reads needed')
    gateway=AsyncMock();gateway.invoke_trusted.side_effect=invoke
    business=BusinessTools(gateway,s,8,lambda:None)
    assert asyncio.run(business.prepare_consultation())
    assert gateway.invoke_trusted.await_count<=2
    assert decision(s).snapshot.selected_sku is None


def test_worse_benefits_block_but_lower_price_keeps_permission():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Lên đơn mẫu hôm trước.'),price=850000)
    ref={'customer_id':'C','session_id':'old','source_turn_id':'old-t','source_kind':'customer','evidence_quote':'Mua Aster giá 900.000đ.'}
    snap={'selected_sku':'SKU-ASTER','accepted_offer':{'sku':'SKU-ASTER','qty':1,'price_vnd':900000,'on':'2026-11-04','promo_terms':[]},
          'source_refs':{'selected_sku':ref,'accepted_offer':ref}}
    s['episodes']=[{'on_date':'2026-11-04','topics':[{'scope_type':'global','consultation':snap}]}]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':850000}) is None
    snap['accepted_offer']['promo_terms']=[{'type':'gift','gift_sku':'SKU-FILTER','promo_code':'GIFT'}]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':850000})=='offer_confirmation_required'


def test_runtime_context_exposes_decision_without_inferring_purchase():
    from app.agent.harness.context import prompt_context
    s=state('Tôi chọn Aster để xem giá.')
    s['request'].input_mode='clean';s['request'].on=date(2026,11,5)
    context=prompt_context(s,6)
    assert context['consultation']['snapshot']['selected_sku']=='SKU-ASTER'
    assert context['consultation']['purchase_intent'] is False


def test_quote_recovery_never_switches_away_from_selected_product():
    from app.agent.harness.session_nodes import safe_catalog_reply
    s=quoted(state('Tôi chọn Brio để xem giá, tư vấn giúp tôi.'))
    # Only Aster has a quote. It must not be substituted for Brio.
    answer=safe_catalog_reply(s)
    assert answer is None or '900.000' not in answer


def test_revoked_snapshot_does_not_revive_old_recommendation():
    ref={'customer_id':'C','session_id':'old','source_turn_id':'old-t','source_kind':'customer','evidence_quote':'Không lấy Aster nữa.'}
    snap={'recommended_sku':'SKU-ASTER','selected_sku':None,'source_refs':{'selected_sku':ref}}
    s=quoted(state('Lên đơn giúp tôi.'));s['episodes']=[{'on_date':'2026-11-04','topics':[{'scope_type':'global','consultation':snap}]}]
    assert decision(s).snapshot.selected_sku is None


def test_affirmation_only_authorizes_purchase_after_scoped_offer_question():
    s=quoted(state('Đồng ý.'))
    s['history']=[{'customer':'Xem giá Aster.','agent':'Aster giá 900.000đ. Mình đồng ý báo giá này để em lên đơn không ạ?'}]
    from test_commerce_evidence import bind_history_observations
    s['session_tool_calls']=s['tool_calls'];s['tool_calls']=[]
    bind_history_observations(s)
    d=decision(s);assert d.purchase_intent and d.snapshot.accepted_offer.price_vnd==900000
    s['history'][0]['agent']='Aster giá 900.000đ. Mình muốn xem thêm không ạ?'
    assert not decision(s).purchase_intent


def test_qty_and_basis_are_not_invented():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Ngân sách 1 triệu, mua 2 chiếc Aster giá 600.000đ.'),price=600000,qty=2)
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':600000,'qty':2})=='budget_basis_required'
    s['safe_text']='Tổng ngân sách 1 triệu, mua 2 chiếc Aster giá 600.000đ.'
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':600000,'qty':2})=='budget_consent_required'


def test_benefit_improvement_is_not_a_loss():
    from app.mcp_servers.mcp_shared.consultation import worse_terms
    assert not worse_terms([{'type':'fixed','discount_vnd':10000}],[{'type':'fixed','discount_vnd':20000}])
    assert worse_terms([{'type':'delivery','freeship':True}],[{'type':'delivery','freeship':False}])


def test_variant_and_customer_quantity_are_bound_before_purchase():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=state('Mua Aster size 40 màu đen giá 900.000đ, lên đơn.')
    s['tool_calls'][0]['result']['items']=[{'sku':'SKU-ASTER','name':'Aster','variants':[
        {'variant_sku':'SKU-ASTER-40','size':40,'color':'đen'},
        {'variant_sku':'SKU-ASTER-41','size':41,'color':'trắng'}]}]
    quoted(s,'SKU-ASTER-40',900000)
    assert purchase_block_reason(s,{'sku':'SKU-ASTER-40','qty':1,'price_vnd':900000}) is None
    assert purchase_block_reason(s,{'sku':'SKU-ASTER-41','qty':1,'price_vnd':900000})=='selection_mismatch'


def test_actual_agent_prepares_quote_from_catalog_only_model_draft():
    import asyncio
    from unittest.mock import patch
    from langchain_core.messages import AIMessage
    from app.agent.harness.agent_nodes import AgentNodes
    s=state('Tư vấn máy cho phòng 25m2, ngân sách 1 triệu.')
    s['tool_calls']=[];s['customer_phone']='0900000000'
    s['request'].input_mode='clean';s['request'].channel='hotline';s['request'].channel_identity='0900000000'
    async def invoke(name,args,*a,**kw):
        if name=='catalog.search':return {'items':[{'sku':'SKU-ASTER','name':'Aster','variants':[],'attributes':{'room_area_m2':35},'list_price_vnd':900000}]}
        if name=='pricing.get_quote':return {'sku':args['sku'],'final_price_vnd':850000,'applied_promos':[]}
        raise AssertionError('no order without permission')
    gateway=SimpleNamespace(invoke_trusted=invoke)
    def build(kind,llm,business,prompt):
        class Agent:
            async def ainvoke(self,*a,**kw):
                await business.invoke('catalog.search',{'min_room_area_m2':25,'max_price_vnd':1000000})
                return {'messages':[AIMessage(content='Em tìm thấy Aster.')]}
        return Agent()
    with patch('app.agent.harness.agent_nodes.build_agent',side_effect=build),patch('app.agent.harness.agent_nodes.text_prompt',return_value='offline'):
        result=asyncio.run(AgentNodes(None,gateway,None,8,6).run_agent(s))
    assert '850.000' in result['agent_draft']
    assert [c['name'] for c in s['tool_calls']]==['catalog.search','pricing.get_quote']
    assert decision(s).snapshot.selected_sku is None


def test_partial_new_session_snapshot_preserves_known_selection_with_provenance():
    old={'customer_id':'C','session_id':'old','source_turn_id':'old-t','source_kind':'customer','evidence_quote':'Tôi chọn Aster.'}
    now={'customer_id':'C','session_id':'s','source_turn_id':'now-t','source_kind':'customer','evidence_quote':'Ngân sách 1 triệu.'}
    s=state('Mẫu hôm trước còn hàng không?')
    s['episodes']=[{'on_date':'2026-11-05','session_id':'old','topics':[{'scope_type':'global','consultation':{'selected_sku':'SKU-ASTER','source_refs':{'selected_sku':old}}}]}]
    s['current_episode']={'on_date':'2026-11-05','session_id':'s','topics':[{'scope_type':'global','consultation':{'budget':{'limit_vnd':1000000},'source_refs':{'budget':now}}}]}
    assert decision(s).snapshot.selected_sku=='SKU-ASTER'


def test_explicit_customer_price_overrides_previous_offer_focus():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Mua Aster giá 900.000đ, lên đơn.'),price=950000)
    s['history']=[{'customer':'Xem giá Aster.','agent':'Aster giá 950.000đ. Mình đồng ý để em lên đơn không?'}]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':950000})=='offer_confirmation_required'


def test_purchase_cannot_ignore_explicit_mandatory_attribute():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Bắt buộc phải có khóa trẻ em. Mua Brio giá 800.000đ, lên đơn.'),'SKU-BRIO',800000)
    assert purchase_block_reason(s,{'sku':'SKU-BRIO','price_vnd':800000})=='product_requirements_not_met'


def test_history_offer_keeps_historical_benefits_not_current_quote_terms():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=quoted(state('Lấy Aster, lên đơn.'),price=900000)
    gift={'type':'gift','promo_code':'GIFT','gift_sku':'SKU-FILTER'}
    s['session_tool_calls']=[{'name':'pricing.get_quote','args':{'sku':'SKU-ASTER','on':'2026-11-05'},
        'result':{'sku':'SKU-ASTER','final_price_vnd':900000,'applied_promos':[gift]}}]
    s['history']=[{'customer':'Xem Aster.','agent':'Aster giá 900.000đ, có quà tặng kèm.'}]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','price_vnd':900000})=='offer_confirmation_required'


def test_k0_short_brand_choice_matches_catalog_without_selecting_a_bundle():
    from app.mcp_servers.mcp_shared.consultation import _mentions
    items = {
        'SKU-JK-WND': {'name': 'Áo khoác gió Windbreak', 'brand': 'Windbreak', 'variants': []},
        'SKU-PUMP': {'name': 'Máy hút sữa Spectra S1', 'brand': 'Spectra', 'attributes': {}},
        'SKU-COMBO': {'name': 'Combo Spectra S1 và máy hâm', 'brand': 'Spectra',
                      'attributes': {'bundle_of': ['SKU-PUMP', 'SKU-WARMER']}},
    }
    assert _mentions('Anh mua áo Windbreak size M màu navy', items) == {'SKU-JK-WND'}
    assert _mentions('Chị lấy Spectra, trả Momo', items) == {'SKU-PUMP'}
    assert _mentions('Chị lấy Combo Spectra S1 và máy hâm', items) == {'SKU-COMBO'}


def test_k0_order_wording_is_purchase_but_not_a_negated_or_hypothetical_order():
    from app.mcp_servers.mcp_shared.consultation import _buy
    assert _buy('ok, em lên order COD cho chị nha, thanks em')
    assert _buy('Em tạo đơn giúp tôi nhé')
    assert not _buy('Đừng tạo đơn cho tôi')
    assert not _buy('Chưa lên order nhé')
    assert not _buy('Nếu tạo đơn thì sao?')


def test_k0_polite_acceptance_requires_an_actual_offer_and_confirmation_question():
    from app.mcp_servers.mcp_shared.consultation import _approval
    from app.schemas.consultation import AcceptedOffer
    offer = AcceptedOffer(sku='SKU-TEST', qty=1, price_vnd=1890000, on='2026-10-20')
    question = 'Anh xác nhận chốt đơn này để em lên đơn COD cho mình nhé?'
    assert _approval('được rồi, cảm ơn em', question, 'SKU-TEST', offer)
    assert not _approval('cảm ơn em', question, 'SKU-TEST', offer)
    assert not _approval('được rồi, cảm ơn em', 'Dạ chào anh.', 'SKU-TEST', offer)
    assert not _approval('được rồi, cảm ơn em', question, 'SKU-OTHER', offer)
    assert not _approval('được rồi nhưng chưa đặt nhé', question, 'SKU-TEST', offer)


def test_k0_price_and_stock_sentence_remains_a_presented_offer_for_polite_acceptance():
    from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations
    from app.mcp_servers.mcp_shared.consultation import derive_consultation, purchase_arguments, purchase_block_reason
    s = state('được rồi, cảm ơn em')
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    s['history'] = [{'customer': 'Tôi lấy Aster, thanh toán COD.',
                     'agent': 'Aster hiện có sẵn hàng với giá 900.000đ. Anh xác nhận để em lên đơn nhé?'}]
    bind_history_observations(s)
    d = derive_consultation(s)
    assert d.purchase_intent and d.snapshot.accepted_offer is not None
    args = purchase_arguments(s)
    assert args and purchase_block_reason(s, args) is None
    s['session_tool_calls'][-1]['result']['in_stock'] = False
    assert derive_consultation(s).snapshot.accepted_offer is None


def test_k0_lookup_of_a_past_purchase_does_not_grant_new_purchase_permission():
    from app.mcp_servers.mcp_shared.consultation import _buy
    assert not _buy('Tôi hỏi tình trạng đơn đã mua Aster hôm trước, tra giúp tôi.')
    assert _buy('Tra đơn cũ giúp tôi, rồi lên đơn mua thêm một Aster.')


def test_k0_parent_model_name_does_not_become_an_accessory_short_name():
    from app.mcp_servers.mcp_shared.consultation import _mentions
    from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
    item = {'sku': 'SKU-FILTER', 'name': 'Màng lọc thay thế AirPure Pro',
            'category': 'gia-dung/phu-kien', 'attributes': {}, 'variants': []}
    calls = [{'name': 'catalog.search', 'result': {'items': [item]}}]
    assert _mentions('Anh vẫn hỏi máy AirPure Pro', {'SKU-FILTER': item}) == set()
    assert resolve_claim_skus('Anh vẫn hỏi máy AirPure Pro', calls) == set()
    assert _mentions('Anh hỏi màng lọc AirPure Pro', {'SKU-FILTER': item}) == {'SKU-FILTER'}
    assert resolve_claim_skus('Anh hỏi màng lọc AirPure Pro', calls) == {'SKU-FILTER'}
