import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from test_deep_memory import FakeToolModel
from test_text_harness_contract import turn_state, old_lamp_reads, nodes


def test_deadline_dependent_purchase_requires_model_authorization_without_automatic_handoff():
    async def run():
        state=turn_state('Tôi chỉ mua nếu giao đúng thời hạn tôi yêu cầu.')
        state['session_tool_calls']=old_lamp_reads(state)
        reply='Em chưa xác nhận được thời hạn giao mình yêu cầu. Mình muốn em kiểm tra thêm không?'
        model=FakeToolModel(replies=[AIMessage(content='',tool_calls=[{
            'name':'order_create','args':{'sku':'SKU-LAMP-A','price_vnd':199000},'id':'purchase'}]),
            AIMessage(content=reply)])
        node,gateway=nodes();node.llm=model
        reviewer=AsyncMock(return_value=False)
        with patch('app.agent.harness.authorization.authorize_write',reviewer):
            state.update(await node.run_agent(state))
            state.update(await node.verify_agent(state))
        reviewer.assert_awaited_once()
        gateway.invoke.assert_not_awaited()
        assert state['agent_text']==reply and len(model.seen)==2
        assert not state.get('needs_handoff')
    asyncio.run(run())


def test_explicit_human_request_reaches_model_before_handoff():
    async def run():
        state=turn_state('Tôi cần giao theo thời hạn riêng, cho tôi gặp nhân viên nhé.')
        brief={'escalation_reason':'khach_yeu_cau_gap_nguoi',
            'conversation_summary':'Khách muốn trao đổi với nhân viên về thời hạn giao hàng.',
            'open_questions':['Có thể đáp ứng thời hạn giao không?'],
            'next_action':'Nhân viên xác minh thời hạn giao với vận hành.'}
        reply='Em đã chuyển yêu cầu đến nhân viên phụ trách.'
        model=FakeToolModel(replies=[AIMessage(content='',tool_calls=[{
            'name':'handoff_transfer','args':{'brief':brief},'id':'handoff'}]),AIMessage(content=reply)])
        node,gateway=nodes();node.llm=model
        gateway.invoke.return_value={'status':'queued','ticket_id':'HT-LOCAL'}
        with patch('app.agent.harness.authorization.authorize_write',AsyncMock(return_value=True)):
            state.update(await node.run_agent(state))
            state.update(await node.verify_agent(state))
        assert state['agent_text']==reply and len(model.seen)==2
        assert state['needs_handoff'] and state['handoff_ticket_id']=='HT-LOCAL'
        assert gateway.invoke.await_args.args[0]=='handoff.transfer'
    asyncio.run(run())
