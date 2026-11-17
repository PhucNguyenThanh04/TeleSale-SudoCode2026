"""Exact-utterance regressions from 20261117T070242Z, with offline inference/storage."""
import asyncio
from datetime import date
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from app.agent.harness.callback_request import callback_request
from app.mcp_servers.mcp_shared.consultation_followup import followup_task
from test_commerce_evidence import state
from test_m1_round2_runtime import runtime_for, turns, tool_message
from test_november_pricing import reference


@pytest.mark.parametrize('text,expected', [
    ('Hiện anh đang bận họp nên chưa trao đổi kỹ được, em đặt lịch hẹn gọi lại cho anh vào 10 giờ sáng ngày mai 22/10/2026 nhé.', '2026-10-22T10:00'),
    ('Anh đang bận, chưa muốn đặt lịch gọi lại ngày mai lúc 10 giờ.', None),
    ('Anh đang bận, em đừng đặt lịch gọi lại ngày mai lúc 10 giờ.', None),
    ('Em đặt lịch gọi lại ngày mai lúc 10 giờ, nhưng đừng gọi lại nhé.', None),
    ('Nếu đặt lịch gọi lại ngày mai lúc 10 giờ thì sao?', None),
    ('Đừng, gọi lại ngày mai lúc 10 giờ.', None),
])
def test_callback_negation_belongs_to_the_requested_action(text, expected):
    assert callback_request(text, date(2026, 10, 21)) == expected


@pytest.mark.parametrize('text', [
    'Anh hỏi lại yêu cầu đổi áo hôm trước, quy trình bưu tá qua thu hồi áo cũ bên em thường mất mấy ngày và điều kiện giữ nguyên tem mác hộp thế nào em?',
    'Anh vẫn giữ nguyên size và màu đã xác nhận đổi hôm trước nhé, khi gửi lại anh cần lưu ý giữ nguyên tem mác ra sao em?',
])
def test_packaging_question_routes_to_policy_with_owned_order_date(text):
    current = state(text)
    current['owned_order_ids'] = ['OD-EXCHANGE']
    task = followup_task(current)
    assert task.kind == 'policy'
    assert 'tem mác' in task.policy_query
    assert task.order_id == 'OD-EXCHANGE'


def test_natural_missing_tds_wording_is_normalized_without_guessing_a_value(reference):
    runtime, repo = runtime_for(reference, [
        tool_message(('catalog.search', {'query': 'máy lọc nước UF Sunhouse'})),
        AIMessage(content='Dạ chị, hiện chưa có dữ liệu xác minh chính xác chỉ số TDS đầu ra là bao nhiêu ppm ạ.')])

    async def run():
        try:
            replies, _ = await turns(runtime, [
                'Alo em, chị đang xem máy lọc nước UF Sunhouse, lọc xong thì chỉ số TDS đầu ra chính xác còn bao nhiêu ppm hả em?',
            ], '2026-10-22')
            answer = replies[0].agent_text
            assert 'chưa có thông tin' in answer.lower(), answer
            assert 'TDS' in answer
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())


def test_tds_context_does_not_erase_new_ro_price_answer(reference):
    runtime, repo = runtime_for(reference, [
        tool_message(('catalog.search', {'query': 'máy lọc nước UF Sunhouse'})),
        AIMessage(content='Hiện chưa có dữ liệu xác minh chỉ số TDS đầu ra.'),
        tool_message(('catalog.search', {'query': 'máy lọc nước RO Kangaroo 10 lõi'})),
        AIMessage(content='Máy lọc nước RO Kangaroo 10 lõi có giá 6.890.000đ.')])

    async def run():
        try:
            replies, states = await turns(runtime, [
                'Alo em, chị đang xem máy lọc nước UF Sunhouse, lọc xong thì chỉ số TDS đầu ra chính xác còn bao nhiêu ppm hả em?',
                'Nếu tài liệu chưa có thông tin chỉ số TDS và nhà chị dùng nước giếng khoan thì nên chuyển sang mẫu máy lọc nước RO Kangaroo 10 lõi đúng không em, mẫu đó giá bao nhiêu để chị cân nhắc gọi lại sau?',
            ], '2026-10-22')
            assert '6.890.000' in replies[-1].agent_text, replies[-1].agent_text
            assert any(c['name'] == 'pricing.get_quote' and c['args']['sku'] == 'SKU-WF-RO10'
                       for c in states[-1]['tool_calls'])
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize('text,on,sku,price,stock', [
    ('Hi em, chị đang xem mẫu áo phao lông vũ Warmly, bản size L màu đen giá bao nhiêu và hiện còn hàng không em?',
     '2026-10-22', 'SKU-JK-DWN-L-DEN', '1.490.000', 'còn hàng'),
    ('Hello em, anh đang xem quạt tháp Xiaomi Tower Fan, mẫu này giá bao nhiêu và hiện còn hàng trong kho không em?',
     '2026-10-22', 'SKU-FAN-TWR', '1.790.000', 'hết hàng'),
    ('Chào em, chị đang xem mẫu áo khoác gió Windbreak, bản size L màu be giá bao nhiêu và hiện còn hàng không em?',
     '2026-10-21', 'SKU-JK-WND-L-BE', '690.000', 'còn hàng'),
    ('Chào em, anh đang xem mẫu nồi chiên không dầu Xiaomi 4.5L, em kiểm tra giá bán và tồn kho giúp anh nhé.',
     '2026-10-20', 'SKU-AF-XM', '1.590.000', 'còn hàng'),
])
def test_literal_product_price_and_stock_do_not_require_model_tool_loops(reference, text, on, sku, price, stock):
    runtime, repo = runtime_for(reference, [])

    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model loop')):
                replies, states = await turns(runtime, [text], on)
            assert price in replies[0].agent_text and stock in replies[0].agent_text, replies[0].agent_text
            assert any(c['name'] == 'inventory.check' and c['args']['sku'] == sku
                       for c in states[0]['tool_calls'])
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())


def test_prepared_warranty_price_and_stock_are_combined_without_model(reference):
    runtime, repo = runtime_for(reference, [])

    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model loop')):
                replies, states = await turns(runtime, [
                    'Chào em, anh đang xem máy tiệt trùng sấy khô Moaz Bebe, mẫu này giá bao nhiêu, hiện còn hàng không và thời hạn bảo hành chính hãng bao lâu em?',
                ], '2026-10-21')
            answer = replies[0].agent_text
            assert '1.890.000' in answer and '12 tháng' in answer and 'còn hàng' in answer, answer
            assert answer.count('1.890.000') == 1
            assert {c['name'] for c in states[0]['tool_calls']} >= {'policy.search', 'pricing.get_quote', 'inventory.check'}
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())


def test_sourced_packaging_policy_is_returned_without_model_or_guessed_pickup_time():
    from app.agent.harness.agent_nodes import AgentNodes
    from test_consultation_followup import FollowupGateway, policy_result
    gateway = FollowupGateway()
    gateway.policy = policy_result()
    gateway.policy['evidence'][0]['content'] = 'Điều kiện đổi trả\nSản phẩm còn nguyên tem, nhãn, hộp, chưa qua sử dụng; có hóa đơn hoặc mã đơn hàng.'
    current = state('Quy trình bưu tá thu hồi thường mất mấy ngày và điều kiện giữ nguyên tem mác hộp thế nào em?')

    async def run():
        with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model loop')):
            node = AgentNodes(None, gateway, None, 6, 6)
            current.update(await node.run_agent(current))
            current.update(await node.verify_agent(current))
        assert 'nguyên tem' in current['agent_text'], current['agent_text']
        assert 'chưa có thông tin' in current['agent_text']
        assert [name for name, _ in gateway.calls] == ['policy.search']

    asyncio.run(run())


def test_prepared_single_product_price_does_not_wait_for_model(reference):
    runtime, repo = runtime_for(reference, [])

    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model loop')):
                replies, _ = await turns(runtime, [
                    'Anh đang xem máy lọc không khí Xiaomi Smart 4 Pro, giá bao nhiêu em?',
                ], '2026-10-20')
            assert '5.490.000' in replies[0].agent_text, replies[0].agent_text
            assert not repo.orders
        finally:
            await runtime.close()

    asyncio.run(run())


def test_one_price_does_not_complete_a_request_for_two_named_products():
    from app.agent.harness.agent_nodes import _task_answer_complete
    from test_commerce_evidence import catalog, quote
    current = state('Cho tôi giá từng món Aster và Brio.')
    current['tool_calls'] = [catalog(), catalog('SKU-BRIO', 'Brio'), quote(), quote('SKU-BRIO', 800000)]
    assert not _task_answer_complete('Aster giá 900.000đ.', current)


def test_hypothetical_switch_changes_only_information_focus():
    from app.mcp_servers.mcp_shared.consultation import derive_consultation
    from test_consultation_flow import state as consultation_state, quoted
    current = quoted(consultation_state('Nếu chuyển sang Brio thì giá bao nhiêu để tôi cân nhắc?'))
    current['history'] = [{'customer': 'Tôi đang xem Aster.', 'agent': 'Aster có giá 900.000đ.'}]
    decision = derive_consultation(current)
    assert decision.focus_sku == 'SKU-BRIO'
    assert decision.snapshot.selected_sku is None
    assert decision.snapshot.accepted_offer is None
    assert not decision.purchase_intent


def test_policy_answer_cannot_hide_an_unanswered_stock_question():
    from app.agent.harness.agent_nodes import _task_answer_complete
    from test_consultation_followup import policy_result
    from test_commerce_evidence import catalog
    current = state('Aster bảo hành bao lâu và hiện còn hàng không?')
    current['tool_calls'] = [catalog(), {'name': 'policy.search',
        'args': {'query': followup_task(current).policy_query, 'on': '2026-11-05'}, 'result': policy_result()}]
    assert not _task_answer_complete('Theo thông tin chính sách đã kiểm tra: ' +
        policy_result()['evidence'][0]['content'], current)


@pytest.mark.parametrize('text,expected', [
    ('Tôi đang xem một mẫu áo khoác, hiện giá bao nhiêu?', []),
    ('Tôi đang xem Xiaomi Smart 4 Pro và Philips AC1715, cho giá từng món.',
     ['Xiaomi Smart 4 Pro', 'AC1715']),
])
def test_literal_product_reads_do_not_invent_or_collapse_product_names(text, expected):
    from app.agent.harness.catalog_query import explicit_product_queries
    assert explicit_product_queries(text) == expected


def test_prepared_order_policy_keeps_ownership_binding_across_graph_nodes(reference):
    from test_consultation_followup import policy_result
    seed = {'order_id': 'OD-REFUND', 'sku': 'SKU-AF-XM', 'price_vnd': 1590000, 'qty': 1,
            'customer_phone': '0900000000', 'status': 'delivered', 'created_on': '2026-10-20'}
    runtime, _ = runtime_for(reference, [], old_orders=[seed])
    original = runtime.tools.invoke_trusted

    async def invoke(name, args, *context, **kwargs):
        if name == 'policy.search':
            result = policy_result()
            result['evidence'][0]['content'] = ('Hoàn tiền\nThời gian 3–5 ngày làm việc kể từ khi kho xác nhận nhận hàng đạt điều kiện. '
                'Đơn COD hoàn qua chuyển khoản. Thông tin tài khoản chỉ nhập vào biểu mẫu hoàn tiền của hệ thống, '
                'không ghi vào ghi chú hội thoại hay bộ nhớ khách hàng.')
            return result
        return await original(name, args, *context, **kwargs)

    runtime.tools.invoke_trusted = invoke

    async def run():
        try:
            with patch('app.agent.harness.agent_nodes.build_agent', side_effect=AssertionError('unnecessary model loop')):
                replies, states = await turns(runtime, [
                    'Đơn đó anh thanh toán COD thì hoàn tiền trong mấy ngày làm việc, và thông tin tài khoản nhận hoàn tiền anh điền vào biểu mẫu nào của hệ thống chứ không đọc qua cuộc gọi đúng không em?',
                ], '2026-10-29')
            answer = replies[0].agent_text
            assert 'biểu mẫu hoàn tiền' in answer and '3–5 ngày' in answer, answer
            assert 'không ghi vào ghi chú' in answer
            assert 'OD-REFUND' in states[0]['policy_order_bindings'].values()
        finally:
            await runtime.close()

    asyncio.run(run())


def test_policy_reply_omits_document_instructions_and_keeps_the_entire_rule():
    from app.agent.harness.session_nodes import safe_followup_reply
    from test_consultation_followup import policy_result
    current = state('Điều kiện giữ nguyên tem mác khi đổi trả ra sao?')
    task = followup_task(current)
    result = policy_result()
    result['evidence'][0]['content'] = ('# Chính sách đổi trả\n\n'
        'Mỗi mục có mã `[DT-xx]` — là `chunk_id` dùng để gán nhãn Recall@k.\n\n'
        'Điều kiện đổi trả\nSản phẩm còn nguyên tem, nhãn, hộp, chưa qua sử dụng. '
        'Bình sữa đã bóc seal không được đổi trả vì lý do vệ sinh.')
    current['tool_calls'] = [{'name': 'policy.search',
        'args': {'query': task.policy_query, 'on': '2026-11-05'}, 'result': result}]
    answer = safe_followup_reply(current, task)
    assert 'chunk_id' not in answer and 'Recall@k' not in answer, answer
    assert 'nguyên tem' in answer and 'không được đổi trả' in answer, answer
