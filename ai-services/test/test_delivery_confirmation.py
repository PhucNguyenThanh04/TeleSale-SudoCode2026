"""A delivery conflict waits for customer consent instead of a generic handoff."""
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.harness.session_nodes import safe_consultation_reply
from app.agent.implementations.business_agent import BusinessTools
from app.mcp_servers.mcp_shared.consultation import purchase_block_reason


def delivery_state(text='Mua Aster giá 900.000đ, giao trong tuần này nhé.'):
    s = state(text)
    s['request'] = s['request'].model_copy(update={'on': date(2026, 10, 18)})
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    for call in s['session_tool_calls'][1:]:
        call['args']['on'] = '2026-10-18'
    s['session_tool_calls'][1]['result']['estimated_delivery'] = '2026-10-22'
    s['history'] = [{'customer': 'Tôi chọn Aster để xem giá.', 'agent': 'Aster giá 900.000đ.'}]
    bind_history_observations(s)
    return s


def clock():
    return datetime(2026, 10, 18, tzinfo=timezone.utc)


def confirmation_state(text='Đồng ý.'):
    s = delivery_state()
    reply = safe_consultation_reply(s)
    s['history'].append({'customer': s['safe_text'], 'agent': reply})
    s['safe_text'] = text
    s['request'] = s['request'].model_copy(update={'text': text})
    return s


def test_blocked_delivery_does_not_create_generic_handoff():
    s = delivery_state()
    writes = []

    async def invoke(name, args, *context, **kwargs):
        writes.append(name)
        return {'status': 'queued', 'ticket_id': 'HT-OFFLINE'}

    tools = SimpleNamespace(invoke_trusted=invoke)

    def build(kind, llm, business, prompt):
        class Agent:
            async def ainvoke(self, *args, **kwargs):
                result = await business.invoke('order.create', {'sku': 'SKU-ASTER', 'price_vnd': 900000})
                assert result['error'] == 'delivery_confirmation_required'
                await business.invoke('handoff.transfer', {'brief': {'escalation_reason': 'khac'}})
                return {'messages': [AIMessage(content='Em chuyển nhân viên xử lý nhé.')]}
        return Agent()

    with patch('app.agent.harness.agent_nodes.build_agent', side_effect=build), \
         patch('app.agent.harness.agent_nodes.text_prompt', return_value='offline'):
        nodes = AgentNodes(None, tools, None, 6, 6, clock=clock)
        s.update(asyncio.run(nodes.run_agent(s)))
        s.update(asyncio.run(nodes.verify_agent(s)))
    assert writes == []
    assert not s.get('needs_handoff')
    assert '2026-10-22' not in s['agent_text']
    assert 'chưa' in s['agent_text'] and 'kiểm tra' in s['agent_text']
    assert '?' in s['agent_text']


@pytest.mark.parametrize('text', ['Đồng ý.', 'Đồng ý giao vào ngày 2026-10-22, lên đơn giúp tôi.'])
def test_accepting_estimated_date_does_not_verify_delivery_deadline(text):
    s = confirmation_state(text)
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) is not None


def test_customer_can_explicitly_remove_delivery_deadline_before_ordering():
    text = 'Không cần giao trong tuần này nữa, lên đơn giúp tôi.'
    s = confirmation_state(text)
    writes = []

    async def invoke(name, args, *context, **kwargs):
        assert name == 'order.create'
        writes.append(args)
        return {'status': 'created', 'order_id': 'OD-OFFLINE', 'estimated_delivery': '2026-10-22'}

    business = BusinessTools(SimpleNamespace(invoke_trusted=invoke), s, 6, clock)
    async def run():
        await business.complete_purchase_if_ready()
        await business.complete_purchase_if_ready()
    asyncio.run(run())
    assert len(writes) == 1
    assert writes[0]['sku'] == 'SKU-ASTER' and writes[0]['price_vnd'] == 900000


@pytest.mark.parametrize('text,estimated', [
    ('Không đồng ý, chị vẫn cần giao trong tuần này.', '2026-10-22'),
    ('Đồng ý giao vào ngày 2026-10-21, lên đơn giúp tôi.', '2026-10-22'),
    ('Đồng ý giao vào ngày 2026-10-22, lên đơn giúp tôi.', '2026-10-23'),
    ('Đồng ý giao vào ngày 2026-10-22 trước 10 giờ, lên đơn giúp tôi.', '2026-10-22'),
    ('Đồng ý giao vào ngày 2026-10-22 hoặc 2026-10-23, lên đơn giúp tôi.', '2026-10-22'),
])
def test_refusal_or_mismatched_date_cannot_authorize_delivery(text, estimated):
    s = delivery_state(text)
    s['session_tool_calls'][1]['result']['estimated_delivery'] = estimated
    assert purchase_block_reason(s, {'sku': 'SKU-ASTER', 'qty': 1, 'price_vnd': 900000}) is not None


def test_explicit_human_request_is_still_honored_with_delivery_conflict():
    s = delivery_state('Mua Aster giá 900.000đ, giao trong tuần này, cho chị gặp nhân viên nhé.')
    async def invoke(name, args, *context, **kwargs):
        assert name == 'handoff.transfer'
        return {'status': 'queued', 'ticket_id': 'HT-REQUESTED'}
    tools = SimpleNamespace(invoke_trusted=invoke)
    with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('no model needed')):
        result = asyncio.run(AgentNodes(None, tools, None, 6, 6, clock=clock).run_agent(s))
    assert result['needs_handoff'] is True
    assert result['handoff_ticket_id'] == 'HT-REQUESTED'
