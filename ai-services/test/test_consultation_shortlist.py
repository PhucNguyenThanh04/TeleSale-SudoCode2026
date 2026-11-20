import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.agent import TextTurnRequest
from app.agent.implementations.business_agent import BusinessTools


def products():
    return [
        {'sku': 'SKU-ASTER', 'name': 'Aster Air', 'category': 'air', 'variants': [],
         'list_price_vnd': 5200000, 'attributes': {'room_area_m2': 30, 'child_safe_lock': True}},
        {'sku': 'SKU-BERYL', 'name': 'Beryl Air', 'category': 'air', 'variants': [],
         'list_price_vnd': 4800000, 'attributes': {'room_area_m2': 25, 'child_safe_lock': False}},
        {'sku': 'SKU-CEDAR', 'name': 'Cedar Air', 'category': 'air', 'variants': [],
         'list_price_vnd': 3200000, 'attributes': {'room_area_m2': 15}},
    ]


def consultation_state(text='Nhà có bé nhỏ, ngân sách khoảng 5 triệu.', items=None):
    request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), channel='hotline',
        channel_identity='0900000000', on=date(2026, 11, 5), text=text, input_mode='clean')
    source = str(uuid4())
    catalog = {'name': 'catalog.search', 'args': {'category': 'air', 'min_room_area_m2': 25},
        'result': {'items': deepcopy(products() if items is None else items)},
        'customer_id': 'C-SHORTLIST', 'session_id': str(request.session_id), 'source_turn_id': source}
    return {'request': request, 'safe_text': text, 'customer_id': 'C-SHORTLIST',
        'customer_phone': '0900000000', 'identity_status': 'known', 'tool_calls': [],
        'tool_count': 0, 'session_tool_calls': [catalog],
        'history': [{'source_turn_id': source, 'customer': 'Tư vấn máy lọc không khí cho phòng 25m2.',
                     'agent': 'Có Aster Air và Beryl Air để mình cân nhắc.'}]}


class QuoteGateway:
    def __init__(self, items=None):
        self.items = products() if items is None else items
        self.calls = []
        self.fail = False

    async def invoke(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return {'items': deepcopy([p for p in self.items if not args.get('sku') or p['sku'] == args['sku']])}
        assert name == 'pricing.get_quote', name
        if self.fail: return {'error': 'unavailable'}
        price = next(p['list_price_vnd'] for p in self.items if p['sku'] == args['sku'])
        return {'sku': args['sku'], 'final_price_vnd': price, 'applied_promos': [], 'freeship': False}


def clock(): return datetime(2026, 11, 5, tzinfo=timezone.utc)
