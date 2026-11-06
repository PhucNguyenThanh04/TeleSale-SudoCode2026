"""Actual read preparation and write boundary, not pre-resolved decision mocks."""
import asyncio
from types import SimpleNamespace
from test_commerce_evidence import state,catalog,quote,stock,bind_history_observations
from app.agent.implementations.business_agent import BusinessTools


def gateway(calls):
    async def invoke(name,args,*a,**kw):
        calls.append((name,dict(args)))
        if name=='catalog.search':return catalog()['result']
        if name=='pricing.get_quote':return quote()['result']
        if name=='inventory.check':return stock()['result']
        if name=='order.create':return {'status':'created','order_id':'OD-OFFLINE'}
        raise AssertionError(name)
    return SimpleNamespace(invoke_trusted=invoke)


def test_returning_choice_hydrates_before_selection_gate():
    async def run():
        s=state('Tôi lấy cái đó, lên đơn giúp tôi.')
        s['history']=[{'customer':'Tôi hỏi máy Aster.','agent':'Aster giá 900.000đ.'}]
        # Price and stock refresh alone do not supply product-name metadata.
        s['session_tool_calls']=[quote(),stock()]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        result=await tools.invoke('order.create',{'sku':'SKU-ASTER','qty':1,'price_vnd':900000})
        assert result.get('status')=='created',result
        assert [n for n,_ in calls]==['catalog.search','order.create']
    asyncio.run(run())


def test_model_sku_does_not_grant_selection():
    async def run():
        s=state('Mua giúp tôi một máy nhé.');calls=[]
        tools=BusinessTools(gateway(calls),s,6,lambda:None)
        result=await tools.invoke('order.create',{'sku':'SKU-ASTER','price_vnd':900000})
        assert 'error' in result
        assert all(n!='order.create' for n,_ in calls)
    asyncio.run(run())


def test_complete_purchase_without_second_model_invocation_and_once_only():
    async def run():
        s=state();s['session_tool_calls']=[catalog(),quote(),stock()]
        s['history']=[{'customer':'Tôi chọn Aster để xem giá.','agent':'Aster giá 900.000đ.'}]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        result=await tools.complete_purchase_if_ready()
        assert result['status']=='created'
        await tools.complete_purchase_if_ready()
        assert [n for n,_ in calls]==['order.create']
    asyncio.run(run())


def test_completion_blocks_without_permission_and_does_not_retry_failed_write():
    async def run():
        for text in ['Cho tôi xem giá Aster.', 'Không mua Aster nữa.', 'Nếu mua Aster thì sao?']:
            s=state(text);s['session_tool_calls']=[catalog(),quote(),stock()]
            if s['history'] and s['session_tool_calls']:bind_history_observations(s)
            calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
            assert await tools.complete_purchase_if_ready() is None
            assert not calls
        s=state();s['session_tool_calls']=[catalog(),quote(),stock()]
        s['history']=[{'customer':'Hỏi Aster.','agent':'Aster giá 900.000đ.'}]
        s['tool_calls']=[{'name':'order.create','args':{'sku':'SKU-ASTER'},'result':{'error':'tool_error'}}]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        assert await tools.complete_purchase_if_ready() is None
        assert not calls
    asyncio.run(run())


def test_actual_agent_completes_order_when_model_only_quotes():
    from unittest.mock import patch
    from langchain_core.messages import AIMessage
    from app.agent.harness.agent_nodes import AgentNodes
    async def run():
        s=state();s['session_tool_calls']=[catalog(),quote(),stock()]
        s['history']=[{'customer':'Hỏi Aster.','agent':'Aster giá 900.000đ.'}]
        bind_history_observations(s)
        calls=[]
        class Agent:
            count=0
            async def ainvoke(self,*a,**kw):
                self.count+=1
                return {'messages':[AIMessage(content='Aster giá 900.000đ.')]}
        agent=Agent()
        with patch('app.agent.harness.agent_nodes.build_agent',return_value=agent),patch('app.agent.harness.agent_nodes.text_prompt',return_value='offline'):
            node=AgentNodes(None,gateway(calls),None,6,6)
            s.update(await node.run_agent(s));s.update(await node.verify_agent(s))
        assert agent.count==1
        assert [n for n,_ in calls]==['order.create']
        assert 'OD-OFFLINE' in s['agent_text']
    asyncio.run(run())


def test_failed_refresh_is_not_served_from_older_current_cache():
    async def run():
        s=state();s['tool_calls']=[catalog(),quote(),
            {'name':'pricing.get_quote','args':quote()['args'],'result':{'error':'unavailable'}}]
        for c in s['tool_calls'][1:]:
            c['args']['customer_phone'] = s['customer_phone']
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        await tools.invoke('pricing.get_quote',{'sku':'SKU-ASTER','qty':1})
        assert [n for n,_ in calls]==['pricing.get_quote']
    asyncio.run(run())


def test_new_offer_consent_and_price_decrease_progress_but_adverse_change_waits():
    async def run():
        for price,text,expected in [(950000,'Lấy Aster, lên đơn.',False),
                (950000,'Lấy Aster giá 950.000đ, lên đơn.',True),
                (850000,'Lấy Aster, lên đơn.',True)]:
            s=state(text);s['session_tool_calls']=[catalog(),quote(price=900000)]
            s['tool_calls']=[quote(price=price),stock()]
            s['history']=[{'customer':'Tôi chọn Aster.','agent':'Aster giá 900.000đ.'}]
            if s['history'] and s['session_tool_calls']:bind_history_observations(s)
            calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
            result=await tools.complete_purchase_if_ready()
            assert bool(result and result.get('status')=='created')==expected
    asyncio.run(run())


def test_quantity_and_explicit_payment_survive_continuation():
    async def run():
        s=state('Lấy 2 chiếc Aster, đơn giá 900.000đ, thanh toán chuyển khoản, lên đơn.')
        s['session_tool_calls']=[catalog(),quote(qty=2),stock()]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        result=await tools.complete_purchase_if_ready()
        assert result and result['status']=='created',result
        assert calls[-1][1]['qty']==2 and calls[-1][1]['payment']=='bank'
    asyncio.run(run())


def test_ambiguous_deictic_choice_and_exhausted_budget_do_not_write():
    async def run():
        s=state('Lấy cái đó nhé.');s['session_tool_calls']=[catalog(),catalog('SKU-BRIO','Brio'),quote(),stock()]
        s['history']=[{'customer':'Tư vấn máy.','agent':'Aster hoặc Brio đều có thể cân nhắc.'}]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        assert await tools.complete_purchase_if_ready() is None and not calls
        s=state('Mua Aster giá 900.000đ.');calls=[]
        tools=BusinessTools(gateway(calls),s,0,lambda:None)
        await tools.prepare_consultation()
        assert await tools.complete_purchase_if_ready() is None and not calls
    asyncio.run(run())


def test_same_price_variant_change_does_not_reuse_other_variant_consent():
    async def run():
        s=state('Lấy Aster size 41, lên đơn nhé.')
        s['session_tool_calls']=[catalog(variants=[{'variant_sku':'SKU-ASTER-40','size':40},
            {'variant_sku':'SKU-ASTER-41','size':41}]),quote('SKU-ASTER-40')]
        s['history']=[{'customer':'Tôi hỏi Aster size 40.','agent':'Aster giá 900.000đ.'}]
        s['tool_calls']=[quote('SKU-ASTER-41'),stock('SKU-ASTER-41')]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        assert await tools.complete_purchase_if_ready() is None
        assert not calls
    asyncio.run(run())


def test_prior_customer_quantity_and_unique_name_suffix_are_not_lost():
    async def run():
        s=state('Lấy cái đó, lên đơn nhé.')
        s['session_tool_calls']=[catalog(name='Máy lọc không khí Cedar Plus'),quote(qty=2),stock()]
        s['history']=[{'customer':'Tôi lấy 2 chiếc Cedar Plus, ngân sách mỗi chiếc 1 triệu.',
                       'agent':'Máy lọc không khí Cedar Plus giá 900.000đ mỗi chiếc.'}]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        result=await tools.complete_purchase_if_ready()
        assert result and result['status']=='created',result
        assert calls[-1][1]['qty']==2
    asyncio.run(run())


def test_returning_to_buy_is_not_a_request_to_pause():
    async def run():
        s=state('Tôi gọi lại lấy Aster giá 900.000đ, lên đơn nhé.')
        s['session_tool_calls']=[catalog(),quote(),stock()]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        result=await tools.complete_purchase_if_ready()
        assert result and result.get('status')=='created'
    asyncio.run(run())


def test_category_word_khong_does_not_erase_customer_payment_choice():
    from app.mcp_servers.mcp_shared.consultation import purchase_arguments
    s=state('Mua máy lọc không khí Aster giá 900.000đ, thanh toán chuyển khoản, lên đơn.')
    s['session_tool_calls']=[catalog(),quote(),stock()]
    assert purchase_arguments(s)['payment']=='bank'


def test_changed_address_refreshes_quote_before_write_in_same_turn():
    async def run():
        s=state('Mua Aster giá 900.000đ, lên đơn. Địa chỉ: Region B')
        s['session_tool_calls']=[catalog(),quote(address='Region A'),stock()]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        await tools.prepare_consultation()
        await tools.complete_purchase_if_ready()
        assert [n for n,_ in calls]==['pricing.get_quote','order.create']
        assert calls[0][1]['address']==calls[1][1]['address']=='Region B'
    asyncio.run(run())


def test_refusing_default_payment_does_not_silently_create_cod_order():
    async def run():
        s=state('Mua Aster giá 900.000đ, lên đơn nhưng không COD nhé.')
        s['session_tool_calls']=[catalog(),quote(),stock()]
        if s['history'] and s['session_tool_calls']:bind_history_observations(s)
        calls=[];tools=BusinessTools(gateway(calls),s,6,lambda:None)
        assert await tools.complete_purchase_if_ready() is None
        assert not calls
    asyncio.run(run())


def test_previous_product_variant_does_not_select_new_product_variant():
    from app.agent.harness.policy import resolve_product_selection
    s=state('Mua Brio, lên đơn.')
    variants=lambda prefix:[{'variant_sku':prefix+'-40','size':40},{'variant_sku':prefix+'-41','size':41}]
    s['session_tool_calls']=[catalog(variants=variants('SKU-ASTER')),
        catalog('SKU-BRIO','Brio',variants('SKU-BRIO'))]
    s['history']=[{'customer':'Tôi hỏi Aster size 40.','agent':'Aster giá 900.000đ.'}]
    assert resolve_product_selection(s,{'sku':'SKU-BRIO'}).status=='selection_required'


def test_first_variant_selection_can_accept_parent_offer_but_change_cannot():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=state('Lấy Aster size 40 màu đen, lên đơn.')
    s['history']=[{'customer':'Giá Aster bao nhiêu?','agent':'Aster giá 900.000đ.'}]
    s['session_tool_calls']=[catalog(variants=[{'variant_sku':'SKU-ASTER-40','size':40,'color':'den'},
        {'variant_sku':'SKU-ASTER-41','size':41,'color':'den'}]),quote()]
    bind_history_observations(s)
    s['tool_calls']=[quote('SKU-ASTER-40'),stock('SKU-ASTER-40')]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER-40','qty':1,'price_vnd':900000}) is None


def test_explicit_delivery_condition_and_required_code_cannot_be_ignored():
    from app.mcp_servers.mcp_shared.consultation import purchase_block_reason
    s=state('Mua Aster giá 900.000đ, giao trong tuần này nhé.')
    s['session_tool_calls']=[catalog(),quote(),stock()]
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','qty':1,'price_vnd':900000})=='delivery_confirmation_required'
    s['safe_text']='Mua Aster giá 900.000đ, phải dùng mã EXACT-SALE.'
    assert purchase_block_reason(s,{'sku':'SKU-ASTER','qty':1,'price_vnd':900000})=='offer_confirmation_required'


import pytest


@pytest.mark.parametrize('text',['Ok em lên đơn cho anh, thanh toán COD nhé.',
    'Thôi cũng được, lên đơn.', 'ok len don cho a nhe'])
def test_order_only_accepts_unique_presented_offer_without_prior_selection(text):
    from app.mcp_servers.mcp_shared.consultation import derive_consultation,purchase_block_reason
    async def run():
        s=state(text)
        s['history']=[{'customer':'Cho tôi xem giá Aster.','agent':'Aster giá 900.000đ.'}]
        s['session_tool_calls']=[catalog(),quote(),stock()]
        bind_history_observations(s)
        d=derive_consultation(s)
        assert d.snapshot.presented_offer is not None
        assert d.snapshot.accepted_offer is not None
        assert d.snapshot.source_refs['accepted_offer'].source_turn_id==str(s['request'].client_msg_id)
        assert d.snapshot.source_refs['selected_sku'].source_turn_id==str(s['request'].client_msg_id)
        assert purchase_block_reason(s,{'sku':'SKU-ASTER','qty':1,'price_vnd':900000}) is None
        calls=[];business=BusinessTools(gateway(calls),s,6,lambda:None)
        assert (await business.complete_purchase_if_ready())['status']=='created'
        assert [name for name,_ in calls]==['order.create']
    asyncio.run(run())


@pytest.mark.parametrize('text',['Nếu lên đơn thì sao?', 'Chưa lên đơn nhé.', 'Đừng lên đơn.',
    'Có COD không?', 'Ông xã đồng ý rồi.'])
def test_order_only_cannot_accept_ambiguous_unpresented_or_revoked_offer(text):
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    s=state(text)
    s['history']=[{'customer':'Cho tôi xem Aster.','agent':'Aster giá 900.000đ.'}]
    s['session_tool_calls']=[catalog(),quote(),stock()]
    bind_history_observations(s)
    assert not derive_consultation(s).purchase_intent
    assert derive_consultation(s).snapshot.accepted_offer is None
