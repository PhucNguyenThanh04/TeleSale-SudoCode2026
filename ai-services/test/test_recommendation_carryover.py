import asyncio
from copy import deepcopy
from datetime import date
import json
from uuid import uuid4

from test_commerce_evidence import quote, state
from test_consultation_shortlist import products, clock
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.memory_observations import memory_observations
from app.mcp_servers.mcp_memory.services.memory import _committed_episode_view


def committed_recommendations():
    sid = str(uuid4())
    first, second = str(uuid4()), str(uuid4())
    turns = [
        {'customer_id': 'C', 'session_id': sid, 'turn_id': first, 'on': '2026-11-05',
         'customer_text': 'Tư vấn máy lọc cho phòng 25m2.', 'agent_text': 'Beryl Air giá 4.800.000đ.'},
        {'customer_id': 'C', 'session_id': sid, 'turn_id': second, 'on': '2026-11-05',
         'customer_text': 'Nhà có bé nhỏ, ngân sách khoảng 5 triệu.',
         'agent_text': 'Em đề xuất Aster Air giá 5.200.000đ, có khóa trẻ em. Mẫu này vượt mức chi, mình đồng ý điều chỉnh không ạ?'}]
    search = {'name': 'catalog.search', 'args': {'query': 'máy lọc', 'category': 'air', 'min_room_area_m2': 25},
              'result': {'items': products()[:2]}}
    filtered = deepcopy(search)
    filtered['args']['max_price_vnd'] = 5000000
    filtered['result']['items'] = products()[1:2]
    batches = [[search, quote('SKU-BERYL', 4800000)],
               [quote('SKU-ASTER', 5200000), filtered, quote('SKU-BERYL', 4800000)]]
    rows, calls = [], []
    for turn, observed in zip(turns, batches):
        safe = json.loads(json.dumps(memory_observations(memory_observations(observed))))
        rows.append({'client_msg_id': turn['turn_id'], 'on_date': turn['on'],
            'customer_text': turn['customer_text'], 'agent_text': turn['agent_text'], 'tool_observations': safe})
        calls.extend({**c, 'customer_id': 'C', 'session_id': sid, 'source_turn_id': turn['turn_id']} for c in safe)
    return sid, turns, calls, rows
