"""Changing a recommendation survives the real memory evidence boundary."""
import asyncio
from copy import deepcopy
from datetime import date
import json
from uuid import uuid4

from test_commerce_evidence import quote, state
from test_consultation_shortlist import products, clock
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.session_nodes import safe_catalog_reply
from app.mcp_servers.mcp_shared.consultation import committed_consultation, derive_consultation
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
        # MCPMemoryStore and MemoryRepo both sanitize; evidence must survive both.
        safe = json.loads(json.dumps(memory_observations(memory_observations(observed))))
        rows.append({'client_msg_id': turn['turn_id'], 'on_date': turn['on'],
            'customer_text': turn['customer_text'], 'agent_text': turn['agent_text'], 'tool_observations': safe})
        calls.extend({**c, 'customer_id': 'C', 'session_id': sid, 'source_turn_id': turn['turn_id']} for c in safe)
    return sid, turns, calls, rows


def test_filtered_search_does_not_erase_evidence_for_latest_spoken_recommendation():
    sid, turns, calls, _ = committed_recommendations()
    snap = committed_consultation('C', sid, turns, calls)
    assert snap.recommended_sku == 'SKU-ASTER'
    assert snap.presented_offer.sku == 'SKU-ASTER'
    assert snap.presented_offer.price_vnd == 5200000
    assert snap.source_refs['recommended_sku'].source_turn_id == turns[-1]['turn_id']
    assert snap.selected_sku is None and snap.accepted_offer is None


def test_memory_read_and_next_call_keep_recommendation_without_granting_purchase():
    sid, turns, calls, rows = committed_recommendations()
    first = committed_consultation('C', sid, turns[:1], calls[:2])
    previous = {'schema_version': 1, 'customer_id': 'C', 'session_id': sid, 'on_date': '2026-11-05',
                'topics': [{'scope_type': 'global', 'consultation': first.model_dump(mode='json')}]}

    class Repo:
        async def owner(self, conn, session): return 'C'
        async def turn_count(self, conn, session): return 2
        async def recent_session_turns(self, *args, **kwargs): return rows

    episode = asyncio.run(_committed_episode_view(Repo(), None, 'C', sid, previous))
    episode = json.loads(json.dumps(episode))
    s = state('Hôm trước chị hỏi máy lọc đó em, báo lại giá giúp chị.')
    s.update(customer_id='C', episodes=[episode], scoped_facts={'product': {'SKU-BERYL': {
        'product_advised': {'value': 'SKU-BERYL', 'source': f'langmem:{sid}:{turns[0]["turn_id"]}'}}}})
    s['request'] = s['request'].model_copy(update={'on': date(2026, 11, 7)})
    assert derive_consultation(s).focus_sku == 'SKU-ASTER'
    trades = []

    class Gateway:
        async def invoke(self, name, args):
            if name == 'order.create':
                trades.append(args)
                return {'status': 'created', 'order_id': 'OD-OFFLINE'}
            assert args['sku'] == 'SKU-ASTER'
            if name == 'catalog.search': return {'items': products()[:1]}
            if name == 'pricing.get_quote': return {'sku': 'SKU-ASTER', 'final_price_vnd': 5200000, 'applied_promos': []}
            assert name == 'inventory.check'
            return {'sku': 'SKU-ASTER', 'in_stock': True, 'qty': 10}

    async def run():
        tools = BusinessTools(Gateway(), s, 6, clock)
        await tools.prepare_consultation()
        answer = safe_catalog_reply(s)
        assert 'Aster Air' in answer and '5.200.000' in answer and 'vượt mức chi' in answer
        assert await tools.complete_purchase_if_ready() is None
        assert trades == []
        assert derive_consultation(s).snapshot.accepted_offer is None
        request = s['request']
        s['history'] = [{'customer': s['safe_text'], 'agent': answer, 'source_turn_id': str(request.client_msg_id)}]
        s['session_tool_calls'] = [{**c, 'source_turn_id': str(request.client_msg_id),
            'customer_id': 'C', 'session_id': str(request.session_id)} for c in s['tool_calls']]
        text = 'Đồng ý mua Aster Air giá 5.200.000đ, lên đơn giúp chị.'
        s.update(safe_text=text, tool_calls=[], tool_count=0)
        s['request'] = request.model_copy(update={'text': text, 'client_msg_id': uuid4()})
        purchase = BusinessTools(Gateway(), s, 6, clock)
        await purchase.prepare_consultation()
        assert (await purchase.complete_purchase_if_ready())['status'] == 'created'
        await purchase.complete_purchase_if_ready()
        assert len(trades) == 1 and trades[0]['sku'] == 'SKU-ASTER' and trades[0]['price_vnd'] == 5200000
    asyncio.run(run())
