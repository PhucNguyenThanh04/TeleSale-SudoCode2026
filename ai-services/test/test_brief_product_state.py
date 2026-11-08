"""The returning brief uses the same admitted product state as the agent."""
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.agent.harness.context import load_context
from app.mcp_servers.mcp_shared.consultation import derive_consultation
from test_deep_memory import turn
from test_scoped_context import Tools


class BriefProductStateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('offline brief test'))
        blocker.start()
        self.addCleanup(blocker.stop)

    async def brief(self, *, selected=None, recommendation='SKU-AP-Y', owner='C1', refs=True,
                    snapshot_factory=None, recommendation_kind='agent'):
        sid, tid = str(uuid4()), str(uuid4())
        snapshot = {'recommended_sku': recommendation, 'source_refs': {}}
        if refs and recommendation:
            snapshot['source_refs']['recommended_sku'] = {
                'customer_id': owner, 'session_id': sid, 'source_turn_id': tid,
                'source_kind': recommendation_kind, 'evidence_quote': 'Em đề xuất AirPure Y vì nhà có trẻ nhỏ.'}
        if selected:
            snapshot['selected_sku'] = selected
            snapshot['source_refs']['selected_sku'] = {
                'customer_id': owner, 'session_id': sid, 'source_turn_id': tid,
                'source_kind': 'customer', 'evidence_quote': 'Tôi chọn mẫu này để xem giá.'}
        if snapshot_factory:
            snapshot = snapshot_factory(sid, tid)
        episode = {'session_id': sid, 'on': '2026-11-08', 'channel': 'hotline',
            'summary': 'Đổi từ X sang Y vì nhà có trẻ nhỏ', 'outcome': 'hen_goi_lai',
            'topics': [{'scope_type': 'global', 'scope_id': '', 'consultation': snapshot},
                       {'scope_type': 'product', 'scope_id': 'SKU-AP-Y', 'items': [
                           {'item_id': 'b-1', 'kind': 'blocker', 'status': 'open', 'text': 'cần hỏi chồng'}]}]}
        class Memory:
            include_prior = True
            max_episodes = 5
            reads = 0
            async def read_context(self, *_):
                self.reads += 1
                return {'history': [], 'profile': {}, 'turn_count': 0, 'current_episode': None,
                    'episodes': [episode], 'scoped_facts': {'room': {}, 'product': {
                        'SKU-AP-X': {'product_advised': {'value': 'SKU-AP-X', 'source_kind': 'tool'},
                                     'price_quoted_vnd': {'value': 4_000_000, 'source_kind': 'tool',
                                                          'on': '2026-11-08'}}}}}
        request = turn('Tôi gọi lại').model_copy(update={'on': datetime(2026, 11, 8).date()})
        state = {'request': request, 'safe_text': request.text, 'identity_status': 'known',
                 'customer_id': 'C1', 'customer_phone': '0984726714', 'honorific': 'chị',
                 'received_at_monotonic': time.perf_counter(), 'tool_calls': []}
        memory, tools = Memory(), Tools()
        with patch('app.mcp_servers.mcp_shared.consultation.derive_consultation',
                   wraps=derive_consultation) as derive:
            result = await load_context(state, memory, tools, lambda: datetime.now(timezone.utc))
        return result['call_brief'], memory.reads, tools.calls, derive.call_count

    async def test_x_to_y_keeps_history_and_latest_recommendation_without_claiming_selection(self):
        brief, reads, calls, derives = await self.brief()
        assert {p['sku'] for p in brief['products_advised']} == {'SKU-AP-X', 'SKU-AP-Y'}
        assert brief['recommended_sku'] == 'SKU-AP-Y'
        assert brief['selected_sku'] is None
        assert 'SKU-AP-Y' in brief['suggested_opening']
        assert 'cần hỏi chồng' in brief['suggested_opening']
        products = {p['sku']: p for p in brief['products_advised']}
        assert products['SKU-AP-X']['price_quoted_vnd'] == 4_000_000
        assert 'price_quoted_vnd' not in products['SKU-AP-Y']
        assert reads == 1 and derives == 1
        assert [name for name, args in calls] == ['inventory.check', 'pricing.get_quote']
        assert all(args['sku'] == 'SKU-AP-Y' for name, args in calls)

    async def test_only_customer_evidence_grants_selected_product(self):
        brief, *_ = await self.brief(selected='SKU-AP-Y')
        assert brief['selected_sku'] == 'SKU-AP-Y'
        assert brief['recommended_sku'] == 'SKU-AP-Y'

    async def test_missing_or_foreign_provenance_does_not_replace_history(self):
        for kwargs in ({'refs': False}, {'owner': 'OTHER'}, {'recommendation': None},
                       {'recommendation_kind': 'tool'}):
            brief, *_ = await self.brief(**kwargs)
            assert brief['recommended_sku'] is None
            assert brief['selected_sku'] is None
            assert [p['sku'] for p in brief['products_advised']] == ['SKU-AP-X']

    async def test_customer_selection_and_agent_recommendation_remain_distinct(self):
        brief, *_ = await self.brief(selected='SKU-AP-X')
        assert brief['selected_sku'] == 'SKU-AP-X'
        assert brief['recommended_sku'] == 'SKU-AP-Y'

    def test_recommendation_or_selection_is_not_an_order_confirmation(self):
        from app.agent.harness.brief_opening import build_suggested_opening
        opening = build_suggested_opening(last_session={'outcome': 'chot_don'},
            advised_products=[{'sku': 'SKU-AP-X'}], recommended_sku='SKU-AP-Y')
        assert 'đã đặt mẫu SKU-AP-Y' not in opening
        assert 'đơn hàng lần trước' in opening

    async def test_reused_catalog_and_confirmed_voice_text_drive_latest_recommendation(self):
        from app.mcp_servers.mcp_shared.consultation import committed_consultation
        for delivered in (True, False):
            def snapshot(sid, tid):
                first = str(uuid4())
                turns = [{'turn_id': first, 'customer_id': 'C1', 'session_id': sid,
                          'customer_text': 'Tư vấn giúp tôi.', 'agent_text': 'Em đề xuất AirPure X.',
                          'on': '2026-11-08'},
                         {'turn_id': tid, 'customer_id': 'C1', 'session_id': sid,
                          'customer_text': 'Nhà có trẻ nhỏ.',
                          'agent_text': 'Em đề xuất AirPure Y.' if delivered else '',
                          'on': '2026-11-08'}]
                calls = [{'name': 'catalog.search', 'args': {}, 'source_turn_id': first,
                          'result': {'items': [{'sku': 'SKU-AP-X', 'name': 'AirPure X'},
                                               {'sku': 'SKU-AP-Y', 'name': 'AirPure Y'}]}}]
                return committed_consultation('C1', sid, turns, calls).model_dump(mode='json')
            brief, reads, calls, derives = await self.brief(snapshot_factory=snapshot)
            assert brief['recommended_sku'] == ('SKU-AP-Y' if delivered else 'SKU-AP-X')
            assert brief['selected_sku'] is None
            assert reads == derives == 1 and len(calls) == 2
