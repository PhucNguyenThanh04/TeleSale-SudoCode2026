import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agent.harness.authorization import authorize_write
from app.schemas.agent import TextTurnRequest


SECRET = 'offline-write-context-secret'
NOW = datetime(2032, 5, 10, 10, tzinfo=timezone.utc)


def current(text='Tôi mua thiết bị màu đỏ giá 97000 đồng, thanh toán COD.'):
    request = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(),
        channel='hotline', channel_identity='0900000027', on=date(2032, 5, 10),
        text=text, input_mode='clean')
    return {'request': request, 'safe_text': text, 'identity_status': 'known',
        'customer_id': 'OWNER-STUDIO', 'customer_phone': '0900000027',
        'owned_order_ids': ['ORDER-STUDIO'], 'tool_count': 0, 'tool_calls': [],
        'history': [{'customer': 'Tôi chọn thiết bị đỏ.',
                     'agent': 'Thiết bị đỏ giá 97000 đồng, mình có mua không?'}]}


def proposal(name):
    return {
        'order.create': {'sku': 'DEVICE-RED', 'qty': 1, 'price_vnd': 97000,
                         'payment': 'COD', 'on': '2032-05-10', 'customer_phone': '0900000027'},
        'order.update': {'order_id': 'ORDER-STUDIO', 'action': 'return', 'on': '2032-05-10'},
        'schedule.callback': {'customer_phone': '0900000027', 'callback_at': '2032-05-11T10:30:00+07:00'},
        'handoff.transfer': {'brief': {'customer_phone': '0900000027', 'customer_name': None,
            'escalation_reason': 'khach_yeu_cau_gap_nguoi',
            'conversation_summary': 'Khách yêu cầu trao đổi với nhân viên về thiết bị.',
            'product_advised': None, 'price_quoted_vnd': None, 'open_questions': [],
            'next_action': 'Nhân viên tiếp nhận yêu cầu của khách.', 'generated_at': NOW.isoformat()}},
    }[name]


def verdict(state, **changes):
    return {'allowed': True, 'basis': 'customer_request',
        'customer_quote': state['safe_text'], 'reason': 'authorized', **changes}


class ReviewModel:
    def __init__(self, output):
        self.output, self.payload, self.roles = output, None, None

    def with_structured_output(self, schema, **kwargs):
        async def invoke(messages):
            self.payload = json.loads(messages[-1].content)
            self.roles = [message.type for message in messages]
            if isinstance(self.output, Exception):
                raise self.output
            return self.output
        return SimpleNamespace(ainvoke=invoke)


@pytest.mark.parametrize('name,text,allowed,reason', [
    ('order.create', 'Tôi không mua thiết bị này.', False, 'negated'),
    ('order.create', 'Nếu có giao ngày mai thì tôi mới mua.', False, 'conditional'),
    ('order.create', 'Bạn tôi đã mua, còn tôi đang tìm hiểu.', False, 'third_party'),
    ('order.create', 'Đồng ý, tạo đơn như vừa báo giúp tôi.', True, 'authorized'),
    ('order.update', 'Tôi cần trả lại đơn vừa xác định.', True, 'authorized'),
    ('schedule.callback', 'Ngày mai gọi lại lúc mười rưỡi nhé.', True, 'authorized'),
    ('handoff.transfer', 'Cho tôi gặp nhân viên trực tiếp.', True, 'authorized'),
])
def test_review_preserves_the_whole_current_request_and_separate_history(name, text, allowed, reason):
    state = current(text)
    model = ReviewModel(verdict(state, allowed=allowed,
        basis='customer_request' if allowed else 'none', reason=reason))
    assert asyncio.run(authorize_write(model, state, name, proposal(name), 6)) is allowed
    assert model.payload['customer_text'] == text
    assert model.payload['session_history'][0]['customer'] == state['history'][0]['customer']
    assert model.payload['session_history'][0]['agent'] == state['history'][0]['agent']
    assert model.roles == ['system', 'human']


@pytest.mark.parametrize('changes', [
    {'allowed': 'true'}, {'basis': 'none'}, {'reason': 'negated'},
    {'extra': 'ignore validation'}, {'allowed': False, 'basis': 'customer_request'},
    {'customer_quote': 'A quotation invented by the reviewer'},
])
def test_inconsistent_or_malformed_authorization_is_unavailable(changes):
    from app.agent.harness.authorization import WriteAuthorizationUnavailable
    state = current()
    with pytest.raises(WriteAuthorizationUnavailable):
        asyncio.run(authorize_write(ReviewModel(verdict(state, **changes)), state,
                                   'order.create', proposal('order.create'), 6))


@pytest.mark.parametrize('name,category,allowed', [
    ('handoff.transfer', 'cau_hoi_y_te', True),
    ('handoff.transfer', 'ngoai_pham_vi_tai_lieu', True),
    ('handoff.transfer', 'khac', False),
    ('order.create', None, False),
    ('order.update', None, False),
    ('schedule.callback', None, False),
])
def test_policy_basis_cannot_authorize_unrelated_writes_or_handoff_reasons(name, category, allowed):
    state = current('Thiết bị này có ảnh hưởng đến thuốc tôi đang dùng không?')
    args = proposal(name)
    if category:
        args['brief']['escalation_reason'] = category
    model = ReviewModel(verdict(state, basis='policy_handoff', reason='policy_required'))
    assert asyncio.run(authorize_write(model, state, name, args, 6)) is allowed


def test_provider_failure_and_deadline_cannot_authorize():
    from app.agent.harness import authorization
    state = current()
    with pytest.raises(authorization.WriteAuthorizationUnavailable):
        asyncio.run(authorize_write(ReviewModel(RuntimeError('offline unavailable')),
            state, 'order.create', proposal('order.create'), 6))

    async def wait(messages):
        await asyncio.Event().wait()

    model = SimpleNamespace(with_structured_output=lambda *a, **kw: SimpleNamespace(ainvoke=wait))
    with patch.object(authorization, 'REVIEW_TIMEOUT_SECONDS', 0.01):
        with pytest.raises(authorization.WriteAuthorizationUnavailable):
            asyncio.run(authorize_write(model, state, 'order.create', proposal('order.create'), 6))


def wire(state, name, args=None):
    from app.agent.harness.authorization import build_write_context
    from app.mcp_servers.mcp_order.write_authorization import write_operation_key
    args = deepcopy(proposal(name) if args is None else args)
    context = build_write_context(state, name, args)
    return context, {**args, 'source_channel': state['request'].channel,
        'source_identity': state['request'].channel_identity,
        'operation_key': write_operation_key(context, args)}


@pytest.mark.parametrize('name', ['order.create', 'order.update', 'schedule.callback', 'handoff.transfer'])
def test_signed_grant_roundtrip_binds_exact_payload_and_explicit_context(name):
    from app.mcp_servers.mcp_order.write_authorization import sign_write_authorization, verify_write_authorization
    context, args = wire(current(), name)
    envelope = sign_write_authorization(name, args, context, SECRET)
    assert verify_write_authorization(name, {**args, 'trusted_authorization': envelope}, SECRET) == context
    assert 'Tôi mua' not in envelope and context.customer_text_hash
    with pytest.raises(PermissionError):
        verify_write_authorization(name, args, SECRET)
    with pytest.raises(PermissionError):
        verify_write_authorization(name, {**args, 'trusted_authorization': envelope}, 'different-secret')


@pytest.mark.parametrize('change', [
    {'qty': 2}, {'price_vnd': 96000}, {'payment': 'bank'}, {'sku': 'DEVICE-BLUE'},
    {'address': 'Địa điểm khác'}, {'on': '2032-05-11'},
    {'source_identity': '0900000028'}, {'source_channel': 'zalo_oa'},
    {'operation_key': 'another-request-key'}, {'trusted_authorization': '{}'},
])
def test_altered_wire_payload_cannot_reuse_an_authorization(change):
    from app.mcp_servers.mcp_order.write_authorization import sign_write_authorization, verify_write_authorization
    context, args = wire(current(), 'order.create')
    args['trusted_authorization'] = sign_write_authorization('order.create', args, context, SECRET)
    with pytest.raises(PermissionError):
        verify_write_authorization('order.create', {**args, **change}, SECRET)


@pytest.mark.parametrize('elapsed', [-6, 121])
def test_future_or_expired_grant_is_rejected(elapsed):
    from app.mcp_servers.mcp_order import write_authorization as auth
    context, args = wire(current(), 'order.create')
    with patch.object(auth.time, 'time', return_value=2_000_000_000):
        args['trusted_authorization'] = auth.sign_write_authorization('order.create', args, context, SECRET)
    with patch.object(auth.time, 'time', return_value=2_000_000_000 + elapsed):
        with pytest.raises(PermissionError):
            auth.verify_write_authorization('order.create', args, SECRET)


def test_context_cannot_sign_another_tool_or_business_arguments():
    from app.mcp_servers.mcp_order.write_authorization import sign_write_authorization
    context, args = wire(current(), 'order.create')
    with pytest.raises(PermissionError):
        sign_write_authorization('order.update', proposal('order.update'), context, SECRET)
    with pytest.raises(PermissionError):
        sign_write_authorization('order.create', {**args, 'qty': 3}, context, SECRET)


class OrderRepo:
    def __init__(self):
        self.owner = 'OWNER-STUDIO'
        self.operations, self.writes, self.transactions = {}, [], 0
        self.product = {'sku': 'DEVICE-RED', 'name': 'Thiết bị đỏ', 'category': 'devices',
            'stock': 50, 'list_price_vnd': 97000, 'attributes': {}, 'variants': []}

    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1
        yield object()

    async def identity_matches(self, *args):
        return [{'customer_id': self.owner, 'phone': '0900000027'}] if self.owner else []

    async def rows(self, session, table):
        return {'products': [self.product], 'promotions': [], 'inventory_events': [],
            'customers': [{'customer_id': self.owner, 'phone': '0900000027',
                'orders': [{'order_id': 'ORDER-STUDIO', 'sku': 'DEVICE-RED',
                            'price_vnd': 97000, 'status': 'delivered'}]}]}[table]

    async def lock_customer(self, *args):
        pass

    async def same_day_orders(self, *args):
        return []

    async def used_promos(self, *args):
        return set()

    async def next_order_id(self, *args):
        return 'ORDER-CREATED'

    async def insert_order(self, session, order_id, customer_id, args, *values):
        self.writes.append(('order.create', deepcopy(args)))

    async def order_owned(self, session, order_id, customer_id):
        return order_id == 'ORDER-STUDIO' and customer_id == self.owner

    async def phone_owned(self, session, phone, customer_id):
        return phone == '0900000027' and customer_id == self.owner

    async def runtime_orders(self, *args):
        return []

    async def insert_update(self, session, order_id, action, result):
        self.writes.append(('order.update', deepcopy(result)))

    async def order_updates(self, session, order_id):
        return [deepcopy(result) for name, result in self.writes
                if name == 'order.update' and result.get('order_id') == order_id]

    async def insert_callback(self, session, phone, moment, note):
        self.writes.append(('schedule.callback', {'moment': moment, 'note': note}))
        return len(self.writes)

    async def insert_handoff(self, session, brief):
        self.writes.append(('handoff.transfer', deepcopy(brief)))
        return len(self.writes)

    async def claim_operation(self, session, key, name, digest):
        previous = self.operations.get(key)
        if previous and previous[:2] != (name, digest):
            return {'error': 'operation_key_conflict'}
        if previous:
            return deepcopy(previous[2])
        self.operations[key] = (name, digest, None)

    async def finish_operation(self, session, key, result):
        self.operations[key] = (*self.operations[key][:2], deepcopy(result))


def purchase_evidence(state):
    on = state['request'].on.isoformat()
    state['tool_calls'] = [
        {'name': 'catalog.search', 'args': {'sku': 'DEVICE-RED'},
         'result': {'items': [{'sku': 'DEVICE-RED', 'variants': []}]}},
        {'name': 'inventory.check', 'args': {'sku': 'DEVICE-RED', 'on': on},
         'result': {'sku': 'DEVICE-RED', 'in_stock': True, 'qty': 50}},
        {'name': 'pricing.get_quote', 'args': {'sku': 'DEVICE-RED', 'on': on,
            'qty': 1, 'customer_phone': state['customer_phone']},
         'result': {'sku': 'DEVICE-RED', 'final_price_vnd': 97000}},
    ]


def business(state, repo, reviewer):
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_order.tools.handlers import create_server
    gateway = MCPGateway(None, create_server(repo, context_secret=SECRET), None,
                         context_secret=SECRET)
    return BusinessTools(gateway, state, 8, lambda: NOW, authorize_write=reviewer)


@pytest.mark.parametrize('name', ['order.create', 'order.update', 'schedule.callback', 'handoff.transfer'])
def test_unsigned_domain_write_is_blocked_before_transaction(name):
    from app.mcp_servers.mcp_order.services.order import invoke
    repo = OrderRepo()
    args = {**proposal(name), 'source_channel': 'hotline', 'source_identity': '0900000027'}
    result = asyncio.run(invoke(repo, name, args))
    assert result.get('error') == 'write_authorization_required'
    assert repo.writes == [] and repo.transactions == 0


def test_direct_mcp_write_without_grant_is_blocked_even_with_matching_identity():
    from fastmcp import Client
    from app.mcp_servers.mcp_order.tools.handlers import create_server

    async def run():
        repo = OrderRepo()
        async with Client(create_server(repo)) as client:
            response = await client.call_tool('schedule.callback', {**proposal('schedule.callback'),
                'source_channel': 'hotline', 'source_identity': '0900000027'})
        assert response.data.get('error') == 'write_authorization_required'
        assert repo.writes == [] and repo.transactions == 0
    asyncio.run(run())


@pytest.mark.parametrize('name,text', [
    ('order.create', 'Tôi mua thiết bị đỏ như giá vừa báo, COD.'),
    ('order.update', 'Tôi muốn trả lại đơn đang trao đổi.'),
    ('schedule.callback', 'Gọi lại cho tôi ngày mai lúc mười rưỡi.'),
    ('handoff.transfer', 'Tôi muốn gặp nhân viên tư vấn trực tiếp.'),
])
def test_reviewed_business_write_reaches_real_mcp_service_once_and_replays_after_restart(name, text):
    async def run():
        state, repo = current(text), OrderRepo()
        purchase_evidence(state)
        model = ReviewModel(verdict(state))

        async def review(tool, args):
            return await authorize_write(model, state, tool, args, 6)

        reviewer = AsyncMock(side_effect=review)
        tools = business(state, repo, reviewer)
        first = await tools.invoke(name, proposal(name))
        assert 'error' not in first, first
        assert len(repo.writes) == 1 and repo.writes[0][0] == name
        assert await tools.invoke(name, proposal(name)) == first
        assert len(repo.writes) == 1 and reviewer.await_count == 1
        restarted = business(state, repo, reviewer)
        assert await restarted.invoke(name, proposal(name)) == first
        assert len(repo.writes) == 1 and reviewer.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('name', ['order.create', 'order.update', 'schedule.callback', 'handoff.transfer'])
def test_semantic_denial_never_reaches_gateway_or_domain(name):
    async def run():
        state, repo = current('Tôi chưa yêu cầu thực hiện thao tác.'), OrderRepo()
        purchase_evidence(state)
        reviewer = AsyncMock(return_value=False)
        tools = business(state, repo, reviewer)
        result = await tools.invoke(name, proposal(name))
        assert result.get('error') == 'customer_authorization_required'
        assert (await tools.invoke(name, proposal(name)))['error'] == 'customer_authorization_required'
        assert reviewer.await_count == 1 and not repo.writes and not repo.transactions
    asyncio.run(run())


@pytest.mark.parametrize('text,expected_writes', [
    ('Xác nhận một chiếc thiết bị đỏ, em tạo đơn giúp tôi.', 1),
    ('Tạo thêm một đơn riêng cho một chiếc thiết bị đỏ.', 2),
])
def test_same_session_purchase_confirmation_cannot_create_duplicate(text, expected_writes):
    async def run():
        state, repo = current(), OrderRepo()
        purchase_evidence(state)
        reviewer = AsyncMock(return_value=True)
        first = await business(state, repo, reviewer).invoke('order.create', proposal('order.create'))
        assert first['status'] == 'created'
        previous = state['tool_calls'][-1]
        next_request = state['request'].model_copy(update={'client_msg_id': uuid4(), 'text': text})
        state.update(request=next_request, safe_text=text, session_tool_calls=[previous], tool_count=0)
        repo.product['list_price_vnd'] = 101000
        purchase_evidence(state)
        state['tool_calls'][-1]['result']['final_price_vnd'] = 101000
        args = proposal('order.create') | {'price_vnd': 101000}
        result = await business(state, repo, reviewer).invoke('order.create', args)
        assert len(repo.writes) == reviewer.await_count == expected_writes
        if expected_writes == 1:
            assert result['order_id'] == first['order_id']
            assert not any(call['name'] == 'order.create' for call in state['tool_calls'])
        else:
            assert result['status'] == 'created'
    asyncio.run(run())


def test_reconfirmation_resolves_parent_sku_before_matching_prior_receipt():
    async def run():
        state, repo = current('Tôi xác nhận lấy chiếc size L màu đỏ, em tạo đơn nhé.'), OrderRepo()
        state['session_tool_calls'] = [{'name': 'order.create', 'args': {'sku': 'DEVICE-L-RED', 'qty': 1},
            'result': {'status': 'created', 'order_id': 'ORDER-FIRST'}}]
        state['tool_calls'] = [{'name': 'catalog.search', 'args': {'sku': 'DEVICE'},
            'result': {'items': [{'sku': 'DEVICE', 'variants': [
                {'variant_sku': 'DEVICE-L-RED', 'size': 'L', 'color': 'Đỏ'},
                {'variant_sku': 'DEVICE-M-RED', 'size': 'M', 'color': 'Đỏ'}]}]}}]
        reviewer = AsyncMock(return_value=True)
        result = await business(state, repo, reviewer).invoke('order.create',
            {'sku': 'DEVICE', 'qty': 1, 'size': 'L', 'color': 'đỏ', 'price_vnd': 97000})
        assert result['status'] == 'already_created'
        assert result['order_id'] == 'ORDER-FIRST'
        assert not repo.writes and not repo.transactions
        reviewer.assert_not_awaited()
    asyncio.run(run())


def test_unbound_state_receipt_cannot_bypass_current_authorization():
    async def run():
        state, repo = current('Tôi không muốn đặt lịch gọi.'), OrderRepo()
        state['tool_calls'] = [{'name': 'schedule.callback', 'args': proposal('schedule.callback'),
            'result': {'callback_id': 'CALLBACK-OLD', 'callback_at': '2032-05-11T10:30:00+07:00'}}]
        reviewer = AsyncMock(return_value=False)
        result = await business(state, repo, reviewer).invoke('schedule.callback', proposal('schedule.callback'))
        assert result.get('error') == 'customer_authorization_required'
        assert reviewer.await_count == 1 and not repo.writes
    asyncio.run(run())


def test_transient_write_failure_can_retry_without_reusing_a_failed_result():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state = current('Gọi lại cho tôi ngày mai lúc mười rưỡi.')
        gateway = AsyncMock()
        gateway.invoke_trusted.side_effect = [{'error': 'mcp_unavailable'},
            {'callback_id': 'CALLBACK-NEW', 'callback_at': '2032-05-11T10:30:00+07:00'}]
        tools = BusinessTools(gateway, state, 8, lambda: NOW,
                              authorize_write=AsyncMock(return_value=True))
        assert (await tools.invoke('schedule.callback', proposal('schedule.callback')))['error'] == 'mcp_unavailable'
        assert (await tools.invoke('schedule.callback', proposal('schedule.callback')))['callback_id'] == 'CALLBACK-NEW'
        assert gateway.invoke_trusted.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('field', ['safe_text', 'customer_id', 'customer_phone', 'history',
                                  'request', 'request_text', 'tool_private_args'])
def test_context_changed_while_reviewing_cannot_execute_the_old_grant(field):
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state, gateway = current(), AsyncMock()
        if field == 'tool_private_args':
            purchase_evidence(state)
            state['tool_calls'][-1]['args']['address'] = '18 đường Sao Mai'

        async def review(name, args):
            if field == 'request_text':
                state['request'] = state['request'].model_copy(update={'text': 'Tôi đổi ý.'})
            elif field == 'tool_private_args':
                state['tool_calls'][-1]['args']['address'] = '35 đường Hướng Dương'
            else:
                state[field] = {'safe_text': 'Tôi đổi ý, chưa gọi lại.', 'customer_id': 'OWNER-OTHER',
                    'customer_phone': '0900000028',
                    'history': [], 'request': state['request'].model_copy(update={'client_msg_id': uuid4()})}[field]
            return True

        tools = BusinessTools(gateway, state, 8, lambda: NOW, authorize_write=review)
        result = await tools.invoke('schedule.callback', proposal('schedule.callback'))
        assert result.get('error') == 'write_authorization_context_changed'
        gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())


def test_unavailable_review_has_a_distinct_error_and_no_side_effect():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        gateway = AsyncMock()
        tools = BusinessTools(gateway, current(), 8, lambda: NOW,
            authorize_write=AsyncMock(side_effect=TimeoutError('review unavailable')))
        assert (await tools.invoke('schedule.callback', proposal('schedule.callback')))['error'] == 'write_authorization_unavailable'
        gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('moment,holiday', [
    ('2032-05-11T07:30', None), ('2032-05-11T22:00', None),
    ('2032-05-16T08:30', None), ('2032-05-11T10:30', '2032-05-11'),
    ('2032-05-11T00:30:00+00:00', None),
])
def test_callback_receipt_records_a_calendar_shift(moment, holiday):
    from app.mcp_servers.mcp_order.services import order
    from app.mcp_servers.mcp_shared import business_calendar as calendar
    repo = OrderRepo()
    rules = deepcopy(calendar.load_calendar())
    if holiday:
        rules['dates'][holiday] = {'hours': []}
    with patch.object(calendar, 'load_calendar', return_value=rules):
        result = asyncio.run(order.callback(repo, None,
            {'customer_phone': '0900000027', 'callback_at': moment}, '0900000027'))
    assert 'error' not in result and len(repo.writes) == 1
    assert datetime.fromisoformat(result['moved_from']) == datetime.fromisoformat(moment)


def test_valid_callback_checks_business_timezone_and_preserves_the_instant():
    from app.mcp_servers.mcp_order.services.order import callback
    repo = OrderRepo()
    original = '2032-05-11T02:30:00+00:00'
    result = asyncio.run(callback(repo, None,
        {'customer_phone': '0900000027', 'callback_at': original}, '0900000027'))
    assert 'error' not in result and len(repo.writes) == 1
    assert repo.writes[0][1]['moment'] == datetime.fromisoformat(original)


@pytest.mark.parametrize('name', ['order.create', 'order.update', 'schedule.callback', 'handoff.transfer'])
def test_fresh_signature_replays_the_same_durable_operation(name):
    from app.mcp_servers.mcp_order import write_authorization as auth
    from app.mcp_servers.mcp_order.services.order import invoke

    async def run():
        repo = OrderRepo()
        context, args = wire(current(), name)
        with patch.object(auth.time, 'time', return_value=2_000_000_000):
            first_grant = auth.sign_write_authorization(name, args, context, SECRET)
            first = await invoke(repo, name, {**args, 'trusted_authorization': first_grant}, context_secret=SECRET)
        with patch.object(auth.time, 'time', return_value=2_000_000_001):
            second_grant = auth.sign_write_authorization(name, args, context, SECRET)
            second = await invoke(repo, name, {**args, 'trusted_authorization': second_grant}, context_secret=SECRET)
        assert first_grant != second_grant
        assert 'error' not in first and first == second and len(repo.writes) == 1
    asyncio.run(run())


def test_mcp_rechecks_owner_before_claiming_or_replaying_a_write():
    from app.mcp_servers.mcp_order.write_authorization import sign_write_authorization
    from app.mcp_servers.mcp_order.services.order import invoke
    repo = OrderRepo()
    repo.owner = 'OWNER-OTHER'
    context, args = wire(current(), 'schedule.callback')
    args['trusted_authorization'] = sign_write_authorization('schedule.callback', args, context, SECRET)
    result = asyncio.run(invoke(repo, 'schedule.callback', args, context_secret=SECRET))
    assert result.get('error') == 'identity_changed' and not repo.writes and not repo.operations


def test_unknown_hotline_customer_can_request_a_phone_bound_handoff():
    async def run():
        state, repo = current('Cho tôi nói chuyện với nhân viên.'), OrderRepo()
        state.update(identity_status='unknown', customer_id=None, customer_phone=None)
        repo.owner = None
        result = await business(state, repo, AsyncMock(return_value=True)).invoke(
            'handoff.transfer', proposal('handoff.transfer'))
        assert result.get('status') == 'queued' and len(repo.writes) == 1
        assert repo.writes[0][1]['customer_phone'] == state['request'].channel_identity
    asyncio.run(run())


def test_gateway_rejects_model_supplied_grant_and_keeps_reads_available():
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_order.tools.handlers import create_server

    async def run():
        repo, state = OrderRepo(), current()
        gateway = MCPGateway(None, create_server(repo, context_secret=SECRET), None, context_secret=SECRET)
        context, args = wire(state, 'schedule.callback')
        from app.mcp_servers.mcp_order.write_authorization import sign_write_authorization
        args['trusted_authorization'] = sign_write_authorization('schedule.callback', args, context, SECRET)
        result = await gateway.invoke('schedule.callback', args)
        assert result.get('error') == 'write_authorization_required' and not repo.transactions
        result = await gateway.invoke_trusted('order.status', {'order_id': 'ORDER-STUDIO'},
            state['customer_id'], state['request'].channel, state['request'].channel_identity)
        assert result['orders'][0]['order_id'] == 'ORDER-STUDIO' and not repo.writes
    asyncio.run(run())


def test_reviewer_argument_mutation_cannot_change_the_executed_payload():
    async def run():
        state, repo = current('Gọi lại cho tôi ngày mai lúc mười rưỡi.'), OrderRepo()

        async def review(name, args):
            args['callback_at'] = '2032-05-12T14:00:00+07:00'
            return True

        result = await business(state, repo, review).invoke('schedule.callback', proposal('schedule.callback'))
        assert 'error' not in result
        assert repo.writes[0][1]['moment'] == datetime.fromisoformat(proposal('schedule.callback')['callback_at'])
    asyncio.run(run())


def test_denial_cache_is_bound_to_current_source_and_review_budget_is_bounded():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state, gateway = current(), AsyncMock()
        reviewer = AsyncMock(return_value=False)
        tools = BusinessTools(gateway, state, 2, lambda: NOW, authorize_write=reviewer)
        for text in ['Không gọi lại.', 'Tôi cần tìm hiểu thêm.']:
            state['safe_text'] = text
            assert (await tools.invoke('schedule.callback', proposal('schedule.callback')))['error'] == 'customer_authorization_required'
        state['safe_text'] = 'Lời mới không cấp quyền cho cache cũ.'
        assert (await tools.invoke('schedule.callback', proposal('schedule.callback')))['error'] == 'write_authorization_limit'
        assert reviewer.await_count == 2
        gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'Không giao đến 18 đường Sao Mai. Giao đến 35 đường Hướng Dương.',
    'Không dùng địa chỉ: 18 đường Sao Mai. Dùng địa chỉ: 35 đường Hướng Dương.',
])
def test_address_review_preserves_private_value_equality_without_sending_the_address(text):
    state = current(text)
    from app.agent.guardrails.checks import mask_pii
    state['safe_text'] = mask_pii(text)
    first, second = ReviewModel(verdict(state)), ReviewModel(verdict(state))
    args = proposal('order.create')
    asyncio.run(authorize_write(first, state, 'order.create', {**args, 'address': '18 đường Sao Mai'}, 6))
    asyncio.run(authorize_write(second, state, 'order.create', {**args, 'address': '35 đường Hướng Dương'}, 6))
    assert first.payload != second.payload
    for payload in [first.payload, second.payload]:
        encoded = json.dumps(payload, ensure_ascii=False)
        assert 'Sao Mai' not in encoded and 'Hướng Dương' not in encoded
        assert '[PROPOSED_ADDRESS]' in encoded


def test_exhausted_tool_budget_does_not_spend_a_semantic_review():
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state, gateway, reviewer = current(), AsyncMock(), AsyncMock(return_value=True)
        state['tool_count'] = 2
        tools = BusinessTools(gateway, state, 2, lambda: NOW, authorize_write=reviewer)
        assert (await tools.invoke('schedule.callback', proposal('schedule.callback')))['error'] == 'tool_limit'
        reviewer.assert_not_awaited()
        gateway.invoke_trusted.assert_not_awaited()
    asyncio.run(run())


def test_unbound_purchase_receipt_cannot_bypass_current_stock_and_quote_checks():
    async def run():
        state, repo, reviewer = current(), OrderRepo(), AsyncMock(return_value=True)
        purchase_evidence(state)
        state['tool_calls'] = [state['tool_calls'][0], {'name': 'order.create',
            'args': proposal('order.create'), 'result': {'status': 'created', 'order_id': 'OLD-ORDER'}}]
        result = await business(state, repo, reviewer).invoke('order.create', proposal('order.create'))
        assert result.get('error') == 'purchase_evidence_required' and not repo.writes
        reviewer.assert_not_awaited()
    asyncio.run(run())


def test_transport_failure_after_write_replays_receipt_without_a_second_business_write():
    async def run():
        state, repo = current('Gọi lại cho tôi ngày mai lúc mười rưỡi.'), OrderRepo()
        tools = business(state, repo, AsyncMock(return_value=True))
        invoke = tools.gateway.invoke_trusted
        failures = [True]

        async def lose_response(*args, **kwargs):
            result = await invoke(*args, **kwargs)
            if failures:
                failures.pop()
                return {'error': 'mcp_unavailable'}
            return result

        tools.gateway.invoke_trusted = lose_response
        first = await tools.invoke('schedule.callback', proposal('schedule.callback'))
        assert first.get('error') == 'mcp_unavailable' and len(repo.writes) == 1
        second = await tools.invoke('schedule.callback', proposal('schedule.callback'))
        assert second.get('callback_id') and len(repo.writes) == 1
    asyncio.run(run())


@pytest.mark.parametrize('name,receipt', [
    ('order.create', {'status': 'created', 'order_id': 'ORDER-CREATED'}),
    ('order.update', {'status': 'pickup_scheduled', 'order_id': 'ORDER-STUDIO', 'action': 'return'}),
    ('schedule.callback', {'callback_id': 'CALLBACK-NEW', 'callback_at': '2032-05-11T10:30+07:00'}),
    ('handoff.transfer', {'status': 'queued', 'ticket_id': 'HANDOFF-NEW'}),
])
@pytest.mark.parametrize('invalid', [{}, {'order_id': 'ORDER-STUDIO', 'status': [],
    'ticket_id': 'HANDOFF-INVALID', 'callback_id': None}])
def test_invalid_write_receipt_is_not_cached_as_a_completed_operation(name, receipt, invalid):
    from app.agent.implementations.business_agent import BusinessTools

    async def run():
        state, gateway = current(), AsyncMock()
        purchase_evidence(state)
        gateway.invoke_trusted.side_effect = [invalid, receipt]
        tools = BusinessTools(gateway, state, 8, lambda: NOW,
                              authorize_write=AsyncMock(return_value=True))
        first = await tools.invoke(name, proposal(name))
        assert first.get('error') == 'invalid_tool_result'
        assert await tools.invoke(name, proposal(name)) == receipt
        assert gateway.invoke_trusted.await_count == 2
    asyncio.run(run())


def test_real_structured_model_adapter_parses_authorization_without_network():
    import httpx2 as httpx
    from app.configs import Settings
    from app.infarstructure.llm import build_llm

    async def run():
        state, requests = current(), []
        model = build_llm(Settings(_env_file=None, llm_api_key='offline',
            llm_model='offline-model', llm_base_url='https://offline.invalid/v1'))

        async def send(client, request, **kwargs):
            payload = json.loads(request.content)
            requests.append(payload)
            definition = payload['tools'][0]['function']
            assert definition['name'] == 'WriteAuthorization'
            assert definition['parameters']['additionalProperties'] is False
            assert definition['parameters']['properties']['allowed']['type'] == 'boolean'
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': 'offline-auth', 'type': 'function', 'function': {
                    'name': 'WriteAuthorization', 'arguments': json.dumps(verdict(state))}}]}
            return httpx.Response(200, request=request, json={'id': 'offline-auth',
                'object': 'chat.completion', 'created': 0, 'model': 'offline-model',
                'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls'}]})

        with patch.object(httpx.AsyncClient, 'send', send):
            assert await authorize_write(model, state, 'order.create', proposal('order.create'), 6) is True
        assert len(requests) == 1
    asyncio.run(run())
