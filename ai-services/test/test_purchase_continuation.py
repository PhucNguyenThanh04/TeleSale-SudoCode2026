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






def test_actual_agent_completes_verified_order_before_invoking_model():
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
        assert agent.count==0
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




















def test_previous_product_variant_does_not_select_new_product_variant():
    from app.agent.harness.policy import resolve_product_selection
    s=state('Mua Brio, lên đơn.')
    variants=lambda prefix:[{'variant_sku':prefix+'-40','size':40},{'variant_sku':prefix+'-41','size':41}]
    s['session_tool_calls']=[catalog(variants=variants('SKU-ASTER')),
        catalog('SKU-BRIO','Brio',variants('SKU-BRIO'))]
    s['history']=[{'customer':'Tôi hỏi Aster size 40.','agent':'Aster giá 900.000đ.'}]
    assert resolve_product_selection(s,{'sku':'SKU-BRIO'}).status=='selection_required'






import pytest
