"""Session continuation is scoped and never promotes a voice draft to evidence."""
from datetime import date
from types import SimpleNamespace
import asyncio
from uuid import uuid4
import pytest
from test_november_pricing import reference

from app.agent.harness.session_state import SessionState


def request(on=date(2026, 11, 11)):
    return SimpleNamespace(on=on)


def test_session_view_keeps_context_but_not_uncommitted_voice_or_turn_flags():
    session = SessionState('C1', date(2026, 11, 11), True)
    source = {'profile': {'budget_vnd': {'value': 5000000}},
              'episodes': [{'session_id': 'prior', 'summary': 'Đã tư vấn'}],
              'call_brief': {'selected_sku': 'SKU-A'}, 'history': [],
              'agent_text': 'Giá mới khách chưa nghe', 'tool_failed': False,
              'consultation': {'next_action': 'confirm_terms', 'missing_fields': ['offer']}}
    session.update(source)
    view = session.resume('C1', request(), True)
    assert view['profile']['budget_vnd']['value'] == 5000000
    assert view['call_brief']['selected_sku'] == 'SKU-A'
    assert 'agent_text' not in view and 'tool_failed' not in view and 'consultation' not in view
    assert session.decision['next_action'] == 'confirm_terms'
    view['profile'].clear()
    assert session.resume('C1', request(), True)['profile']


def test_new_memory_view_replaces_deleted_facts_and_failure_clears_context():
    session = SessionState('C1', date(2026, 11, 11), True)
    session.update({'profile': {'blocker': {'value': 'cần hỏi chồng'}}, 'call_brief': {'open_blockers': ['cần hỏi chồng']}})
    session.update({'profile': {}, 'call_brief': {'open_blockers': []}})
    assert session.resume('C1', request(), True)['profile'] == {}
    session.update({'tool_failed': True, 'memory_blocked': True})
    assert session.resume('C1', request(), True) == {}
    assert session.decision == {}


def test_owner_date_or_memory_mode_change_cannot_reuse_context():
    for customer, turn, prior in [('C2', request(), True),
            ('C1', request(date(2026, 11, 12)), True), ('C1', request(), False)]:
        session = SessionState('C1', date(2026, 11, 11), True)
        session.update({'profile': {'budget_vnd': {'value': 5000000}}})
        assert session.resume(customer, turn, prior) == {}


@pytest.mark.parametrize('delivery_mode', ['text', 'voice'])
@pytest.mark.parametrize('filler_turns', [0, 14])
def test_new_runtime_recovers_delivered_basket_from_committed_session(reference, delivery_mode, filler_turns):
    from langchain_core.messages import AIMessage
    from app.agent.harness.runtime import AgentHarnessRuntime
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
    from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
    from app.schemas.agent import TextTurnRequest, VoicePlaybackRequest
    from test_basket_runtime import MemoryRepo, Memory
    from test_november_pricing import OrderRepo
    from test_deep_memory import FakeToolModel
    customer = {'customer_id': 'C1', 'phone': '0900000000', 'name': 'Khách', 'orders': [], 'sessions': []}
    class CommerceRepo(OrderRepo):
        async def rows(self, session, table):
            return [customer] if table == 'customers' else await super().rows(session, table)
        async def identity_matches(self, *args):
            return [{'customer_id': 'C1', 'phone': customer['phone']}]
        async def runtime_orders(self, *args):
            return self.orders
    commerce = CommerceRepo(reference)
    commerce.phone = customer['phone']
    memory_repo = MemoryRepo()
    price = reference.pricing_quote_order([{'sku': 'SKU-AP-PRO', 'qty': 2}])['total_vnd']
    first_model = FakeToolModel(replies=[AIMessage(content='', tool_calls=[
        {'id': 'catalog', 'name': 'catalog_search', 'args': {'sku': 'SKU-AP-PRO'}},
        {'id': 'quote', 'name': 'pricing_quote_order', 'args': {'lines': [{'sku': 'SKU-AP-PRO', 'qty': 2}]}}]),
        AIMessage(content=f'2 máy AirPure Pro có tổng giá {price:,}đ.'.replace(',', '.'))])
    def runtime(model):
        return AgentHarnessRuntime(model, MCPGateway(catalog_server(commerce), order_server(commerce), None),
                                   Memory(memory_repo), agent_kind='react', max_tool_calls=10)
    async def run():
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(), on=date(2026, 10, 15),
            channel='hotline', channel_identity=customer['phone'], input_mode='clean',
            delivery_mode=delivery_mode, text='Báo giá 2 máy AirPure Pro.')
        async def respond(active, turn):
            response = await active.run(turn)
            if delivery_mode == 'voice':
                await active.record_playback(VoicePlaybackRequest(**turn.model_dump(include={
                    'session_id', 'client_msg_id', 'channel', 'channel_identity', 'on'}),
                    played_chars=len(response.agent_text), interrupted=False))
            return response
        previous = runtime(first_model)
        offered = await respond(previous, request)
        assert f'{price:,}'.replace(',', '.') in offered.agent_text, (
            offered.agent_text, previous.state_for(request).get('consultation_scope'),
            [(c['name'], c.get('args')) for c in previous.state_for(request).get('tool_calls', [])])
        await previous.close()
        for _ in range(filler_turns):
            await Memory(memory_repo).commit_turn(str(request.session_id), 'C1', 'Em nói tiếp nhé.',
                'Dạ.', request.on.isoformat(), 'hotline', str(uuid4()), tool_observations=[])
        restored = runtime(FakeToolModel(replies=[AIMessage(content='Dạ, em kiểm tra đơn giúp mình.')]))
        confirmation = request.model_copy(update={'client_msg_id': uuid4(),
            'text': 'Đồng ý mua cả hai máy, chuyển khoản nhé.'})
        response = await respond(restored, confirmation)
        assert len(commerce.orders) == 1, response.agent_text
        assert commerce.orders[0]['total_vnd'] == price
        assert len(commerce.orders[0]['lines']) == 2
        assert all(row['memory_status'] == 'pending' for row in memory_repo.sessions[str(request.session_id)]['turns'])
        await restored.close()
    asyncio.run(run())
