from types import SimpleNamespace
from datetime import date
from copy import deepcopy
import pytest


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
























def test_business_gateway_cannot_create_from_catalog_or_quote_alone():
    import asyncio
    from unittest.mock import AsyncMock
    from app.agent.implementations.business_agent import BusinessTools
    s=quoted(state('Xem giá Aster.'));s['request'].channel='hotline';s['request'].channel_identity=None
    gateway=AsyncMock();gateway.invoke_trusted.return_value={'status':'created','order_id':'OD-FAKE'}
    out=asyncio.run(BusinessTools(gateway,s,8,lambda:None).invoke('order.create',{'sku':'SKU-ASTER','price_vnd':900000}))
    assert out['error']=='purchase_permission_required'
    assert gateway.invoke_trusted.await_count==0






def test_runtime_context_exposes_decision_without_inferring_purchase():
    from app.agent.harness.context import prompt_context
    s=state('Tôi chọn Aster để xem giá.')
    s['request'].input_mode='clean';s['request'].on=date(2026,11,5)
    context=prompt_context(s,6)
    assert context['consultation']['snapshot']['selected_sku']=='SKU-ASTER'
    assert context['consultation']['purchase_intent'] is False
