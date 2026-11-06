"""Presented offers need committed agent speech and its own tool evidence."""
from copy import deepcopy
from uuid import uuid4
import pytest
from test_commerce_evidence import catalog,quote


def evidence():
    sid,tid=str(uuid4()),str(uuid4())
    turns=[{'customer_id':'C','session_id':sid,'turn_id':tid,'on':'2026-11-05',
            'customer_text':'Giá Aster bao nhiêu?', 'agent_text':'Aster giá 900.000đ.'}]
    calls=[{**c,'source_turn_id':tid,'customer_id':'C','session_id':sid} for c in [catalog(),quote()]]
    return sid,turns,calls


def derive(sid,turns,calls):
    from app.mcp_servers.mcp_shared.presented_offers import derive_presented_offers
    return derive_presented_offers(customer_id='C',session_id=sid,committed_turns=turns,tool_calls=calls)


def test_only_spoken_terms_admitted_and_sources_roundtrip():
    sid,turns,calls=evidence()
    calls[-1]['result']['applied_promos']=[{'type':'gift','promo_code':'GIFT-ASTER','gift_sku':'SKU-GIFT'}]
    offer,=derive(sid,turns,calls)
    assert offer.price_vnd==900000 and offer.promo_terms==[]
    assert offer.sources['price'].agent.source_turn_id==turns[0]['turn_id']
    assert offer.sources['price'].observation.source_turn_id==turns[0]['turn_id']
    assert offer==type(offer).model_validate_json(offer.model_dump_json())
    turns[0]['agent_text']='Em kiểm tra giúp mình.'
    assert derive(sid,turns,calls)==[]
    turns[0]['agent_text']='Aster giá 900.000đ.'
    assert derive(sid,turns,[{**c,'customer_id':'OTHER'} for c in calls])==[]


@pytest.mark.parametrize('changed',[False,True])
def test_gift_followup_merges_only_compatible_quote(changed):
    sid,turns,calls=evidence()
    tid=str(uuid4())
    turns.append({**turns[0],'turn_id':tid,'customer_text':'Có quà không?',
        'agent_text':'Aster được tặng quà kèm theo chương trình GIFT-ASTER.'})
    calls[-1]['result']['applied_promos']=[{'type':'gift','promo_code':'GIFT-ASTER','gift_sku':'SKU-GIFT'}]
    q=deepcopy(calls[-1]);q['source_turn_id']=tid
    if changed:q['result']['final_price_vnd']=950000
    calls.append(q)
    offers=derive(sid,turns,calls)
    if changed:
        assert not any(o.price_vnd==900000 and o.promo_terms for o in offers)
    else:
        offer,=offers
        assert offer.price_vnd==900000 and offer.promo_terms[0]['gift_sku']=='SKU-GIFT'
        assert offer.sources['price'].agent.source_turn_id!=offer.sources['term:0'].agent.source_turn_id


def test_memory_observations_preserve_offer_fields_without_inventing_unknowns():
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    q=quote();q['result']['freeship']=True;q['result']['expired_promos']=['OTHER-OLD']
    result=memory_observations([q])[0]['result']
    assert result['freeship'] is True and result['expired_promos']==['OTHER-OLD']
    del q['result']['freeship']
    assert 'freeship' not in memory_observations([q])[0]['result']


def test_total_price_is_not_mistaken_for_unit_price():
    sid,turns,calls=evidence()
    calls[-1]['args']['qty']=2
    turns[0]['agent_text']='Aster tổng cả 2 chiếc giá 900.000đ.'
    assert derive(sid,turns,calls)==[]
    turns[0]['agent_text']='Aster tổng cả 2 chiếc giá 1.800.000đ.'
    offer,=derive(sid,turns,calls)
    assert offer.basis=='total' and offer.price_vnd==1800000 and offer.qty==2


def test_named_choice_recovers_one_of_multiple_presented_offers():
    from datetime import date
    from types import SimpleNamespace
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    sid,turns,calls=evidence()
    tid=turns[0]['turn_id']
    calls.extend({**c,'source_turn_id':tid,'customer_id':'C','session_id':sid}
                 for c in [catalog('SKU-BRIO','Brio'),quote('SKU-BRIO',800000)])
    turns[0]['agent_text']='Aster giá 900.000đ; Brio giá 800.000đ.'
    history=[{**t,'source_turn_id':t['turn_id'],'customer':t['customer_text'],'agent':t['agent_text']} for t in turns]
    state={'request':SimpleNamespace(session_id=sid,client_msg_id='next',on=date(2026,11,5)),
           'customer_id':'C','identity_status':'known','safe_text':'Lấy Aster, lên đơn.',
           'history':history,'session_tool_calls':calls,'tool_calls':[]}
    decision=derive_consultation(state)
    assert decision.snapshot.accepted_offer.price_vnd==900000
    state['safe_text']='Lấy mẫu đó, lên đơn.'
    assert derive_consultation(state).snapshot.accepted_offer is None


def test_cross_session_named_choice_uses_bounded_committed_offer_candidates():
    from datetime import date
    from types import SimpleNamespace
    from app.mcp_servers.mcp_shared.consultation import committed_consultation,derive_consultation
    sid,turns,calls=evidence();tid=turns[0]['turn_id']
    calls.extend({**c,'source_turn_id':tid,'customer_id':'C','session_id':sid}
                 for c in [catalog('SKU-BRIO','Brio'),quote('SKU-BRIO',800000)])
    turns[0]['agent_text']='Aster giá 900.000đ; Brio giá 800.000đ.'
    snapshot=committed_consultation('C',sid,turns,calls)
    ep={'customer_id':'C','session_id':sid,'on':'2026-11-05','topics':[
        {'scope_type':'global','consultation':snapshot.model_dump(mode='json')}],
        'offer_candidates':[o.model_dump(mode='json') for o in derive(sid,turns,calls)]}
    s={'request':SimpleNamespace(session_id='new',client_msg_id='now',on=date(2026,11,5)),
       'customer_id':'C','identity_status':'known','safe_text':'Lấy Aster, lên đơn.',
       'history':[],'session_tool_calls':[],'tool_calls':[catalog(),catalog('SKU-BRIO','Brio')],'episodes':[ep]}
    assert derive_consultation(s).snapshot.accepted_offer.price_vnd==900000
    s['safe_text']='Lấy mẫu đó, lên đơn.'
    assert derive_consultation(s).snapshot.accepted_offer is None


def test_two_variant_offers_do_not_pick_last_and_revocation_keeps_permission_revoked():
    from datetime import date
    from types import SimpleNamespace
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    sid,turns,calls=evidence();tid=turns[0]['turn_id']
    calls[0]=dict(calls[0],result=catalog(variants=[{'variant_sku':'SKU-ASTER-40','size':40},
        {'variant_sku':'SKU-ASTER-41','size':41}])['result'])
    calls[1:]=[{**quote(sku),'source_turn_id':tid} for sku in ['SKU-ASTER-40','SKU-ASTER-41']]
    turns[0]['agent_text']='SKU-ASTER-40 giá 900.000đ; SKU-ASTER-41 giá 900.000đ.'
    s={'request':SimpleNamespace(session_id=sid,client_msg_id='next',on=date(2026,11,5)),
       'customer_id':'C','identity_status':'known','safe_text':'Lấy Aster, lên đơn.',
       'history':[dict(turns[0],source_turn_id=tid)],'session_tool_calls':calls,'tool_calls':[]}
    assert derive_consultation(s).snapshot.accepted_offer is None
    s['history'].append({'customer':'Không mua Aster nữa.','agent':'Dạ.','source_turn_id':'revoked'})
    s['safe_text']='Lên đơn mẫu đó.'
    d=derive_consultation(s)
    assert d.snapshot.selected_sku is None and d.snapshot.accepted_offer is None


def test_one_spoken_gift_program_does_not_admit_other_unspoken_gifts():
    sid,turns,calls=evidence()
    calls[-1]['result']['applied_promos']=[
        {'type':'gift','promo_code':'GIFT-ASTER','gift_sku':'SKU-GIFT-A'},
        {'type':'gift','promo_code':'GIFT-OTHER','gift_sku':'SKU-GIFT-B'}]
    turns[0]['agent_text']='Aster được tặng quà kèm theo chương trình GIFT-ASTER.'
    offer,=derive(sid,turns,calls)
    assert [p['gift_sku'] for p in offer.promo_terms]==['SKU-GIFT-A']
    turns[0]['agent_text']='Aster được tặng quà.'
    offer,=derive(sid,turns,calls)
    assert offer.promo_terms==[{'type':'gift'}]


def test_equivalent_program_change_can_keep_price_without_claiming_old_code_active():
    sid,turns,calls=evidence()
    calls[-1]['result']['applied_promos']=[{'type':'gift','promo_code':'GIFT-OLD','gift_sku':'SKU-GIFT'}]
    tid=str(uuid4());q=deepcopy(calls[-1]);q['source_turn_id']=tid
    q['result']['applied_promos'][0]['promo_code']='GIFT-NEW'
    calls.append(q)
    turns.append({**turns[0],'turn_id':tid,'customer_text':'Có quà gì?',
        'agent_text':'Aster được tặng quà theo chương trình GIFT-NEW.'})
    offer,=derive(sid,turns,calls)
    assert offer.price_vnd==900000
    assert offer.promo_terms==[{'type':'gift','promo_code':'GIFT-NEW','gift_sku':'SKU-GIFT'}]


def test_gift_program_does_not_hide_separately_spoken_cod_benefit():
    sid,turns,calls=evidence()
    calls[-1]['result']['applied_promos']=[
        {'type':'gift','promo_code':'GIFT-ASTER','gift_sku':'SKU-GIFT'},
        {'type':'freecod','promo_code':'COD-ZERO','discount_vnd':0}]
    turns[0]['agent_text']='Aster có quà theo chương trình GIFT-ASTER, miễn phí thu hộ COD.'
    offer,=derive(sid,turns,calls)
    assert {p['type'] for p in offer.promo_terms}=={'gift','freecod'}


@pytest.mark.parametrize('owner', [None, ''])
def test_anonymous_history_does_not_create_customer_bound_offer(owner):
    from app.mcp_servers.mcp_shared.presented_offers import derive_presented_offers
    sid, turns, calls = evidence()
    for item in [*turns, *calls]:
        item['customer_id'] = owner
    assert derive_presented_offers(customer_id=owner, session_id=sid,
        committed_turns=turns, tool_calls=calls) == []
    # A later verified attribution can derive the same committed evidence.
    for item in [*turns, *calls]:
        item['customer_id'] = 'C'
    offer, = derive(sid, turns, calls)
    assert offer.price_vnd == 900000
    assert offer.sources['price'].observation.customer_id == 'C'


def test_anonymous_priced_history_loads_context_without_validation_error():
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.agent.harness.context import load_context
    from app.mcp_servers.mcp_shared.consultation import derive_consultation, purchase_block_reason
    sid, turns, calls = evidence()
    for item in [*turns, *calls]:
        item['customer_id'] = None
    request = SimpleNamespace(session_id=sid, client_msg_id=str(uuid4()),
                              on=date(2026, 11, 5), text='Có giảm không?')
    state = {'request': request, 'customer_id': None, 'identity_status': 'unknown',
        'safe_text': request.text, 'tool_calls': [], 'session_tool_calls': calls}
    history = [{'customer': t['customer_text'], 'agent': t['agent_text'], 'on': t['on'],
                'source_turn_id': t['turn_id']} for t in turns]
    memory = SimpleNamespace(include_prior=True, max_episodes=5, read_context=AsyncMock(return_value={
        'history': history, 'profile': {}, 'scoped_facts': {'product': {}, 'room': {}},
        'episodes': [], 'current_episode': None, 'turn_count': 1}))
    tools = AsyncMock()
    loaded = asyncio.run(load_context(state, memory, tools, lambda: None))
    assert loaded['history'] and not loaded.get('tool_failed')
    decision = derive_consultation({**state, **loaded})
    assert decision.snapshot.presented_offer is None
    assert purchase_block_reason({**state, **loaded}, {}) == 'identity_required'
    tools.invoke.assert_not_called()
    tools.invoke_trusted.assert_not_called()
