import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.mcp_servers.mcp_shared.pii import mask_pii, resolve_redacted_address


@pytest.mark.parametrize('suffix', [
    'lấy 2 cái và thanh toán momo nhé',
    'nhưng chưa tạo đơn nếu chưa giao kịp thứ sáu',
    'chỉ mua màu xanh, không lấy màu đỏ',
])
def test_address_masking_keeps_customer_purchase_terms(suffix):
    text = f'Chốt đơn. Địa chỉ: 12 đường Mẫu, Phường 3, Hà Nội, {suffix}.'
    masked = mask_pii(text)
    assert suffix in masked
    assert '12 đường Mẫu' not in masked and 'Phường 3' not in masked
    assert resolve_redacted_address(text) == '12 đường Mẫu, Phường 3, Hà Nội'
    assert mask_pii(masked) == masked


@pytest.mark.parametrize('address', [
    '12 đường Mẫu, Phường 3, Hà Nội',
    'căn hộ A12, tòa Mẫu, Hà Nội',
    'ngõ 15, phố Mẫu, Hà Nội',
])
def test_unlabelled_address_does_not_swallow_quantity_and_conditions(address):
    text = f'Giao đến {address}; lấy 2 chiếc, chỉ tạo đơn nếu còn đủ hàng.'
    masked = mask_pii(text)
    assert 'lấy 2 chiếc, chỉ tạo đơn nếu còn đủ hàng' in masked
    assert address not in masked
    assert resolve_redacted_address(text) == address


def test_multiple_addresses_stay_distinct_and_do_not_hide_customer_correction():
    text = 'Địa chỉ: 12 đường Cũ, không giao đó. Địa chỉ: 24 đường Mới, giao chỗ này nhé.'
    masked = mask_pii(text)
    assert 'không giao đó' in masked and 'giao chỗ này nhé' in masked
    assert '12 đường Cũ' not in masked and '24 đường Mới' not in masked
    assert resolve_redacted_address(text) is None


def test_returning_brief_uses_latest_session_even_when_older_one_matches_query():
    from app.agent.harness.context import load_context
    from app.schemas.agent import TextTurnRequest

    request = TextTurnRequest(session_id=uuid4(), client_msg_id=uuid4(),
        channel='hotline', channel_identity='0900000011', on='2031-03-12',
        text='Tôi hỏi tiếp đèn bàn.', input_mode='clean')
    older = {'session_id': str(uuid4()), 'on': '2030-01-01', 'channel': 'hotline',
             'summary': 'Trao đổi đèn bàn cho góc học tập.', 'outcome': 'khac'}
    latest = {'session_id': str(uuid4()), 'on': '2031-03-11', 'channel': 'hotline',
              'summary': 'Trao đổi áo khoác.', 'outcome': 'khac'}

    async def read_context(*args):
        return {'history': [], 'profile': {}, 'episodes': [latest, older]}

    memory = SimpleNamespace(include_prior=True, max_episodes=1, read_context=read_context)
    state = {'request': request, 'safe_text': request.text, 'customer_id': 'owner',
             'customer_phone': '0900000011', 'identity_status': 'known',
             'received_at_monotonic': 0, 'tool_calls': []}
    result = asyncio.run(load_context(state, memory, None,
        lambda: datetime(2031, 3, 12, tzinfo=timezone.utc)))
    assert result['episodes'][0]['session_id'] == older['session_id']
    assert result['call_brief']['last_session']['session_id'] == latest['session_id']
    assert not any('180' in warning for warning in result['call_brief']['stale_warnings'])


def test_known_room_area_does_not_forbid_asking_about_another_room():
    from app.agent.harness.context import load_context
    from test_text_harness_contract import turn_state

    state = turn_state('Phòng ngủ cần máy khác.')
    state['received_at_monotonic'] = 0

    async def read_context(*args):
        return {'history': [], 'profile': {}, 'episodes': [{
            'session_id': str(uuid4()), 'on': '2030-04-07', 'channel': 'hotline',
            'summary': 'Khách hỏi máy cho phòng khách.', 'outcome': 'khac'}],
            'scoped_facts': {'room': {'phong-khach': {
                'room_area_m2': {'value': 25, 'source_kind': 'customer'}}}, 'product': {}}}

    memory = SimpleNamespace(include_prior=True, max_episodes=5, read_context=read_context)
    result = asyncio.run(load_context(state, memory, None,
        lambda: datetime(2030, 4, 8, tzinfo=timezone.utc)))
    assert 'room_area_m2' not in result['call_brief']['must_not_ask']
    assert result['call_brief']['profile_facts']['rooms']['phong-khach']['room_area_m2']['value'] == 25


@pytest.mark.parametrize('basket', [False, True])
def test_quote_evidence_retains_exact_context_without_persisting_private_values(basket):
    import json
    from app.agent.harness.policy import order_evidence_error
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from test_text_harness_contract import turn_state

    state = turn_state('Đồng ý mua một chiếc.')
    address = '24 đường Hoa, Hà Nội'
    quoted_args = {'on': '2030-04-08', 'customer_phone': state['customer_phone'], 'address': address}
    order_args = {**quoted_args, 'payment': 'COD'}
    if basket:
        quoted_args['lines'] = [{'sku': 'SAMPLE-A', 'qty': 1}]
        order_args['lines'] = [{'sku': 'SAMPLE-A', 'qty': 1, 'price_vnd': 100000}]
        quoted_result = {'units': [{'sku': 'SAMPLE-A', 'final_price_vnd': 100000}], 'total_vnd': 100000}
    else:
        quoted_args.update(sku='SAMPLE-A', qty=1)
        order_args.update(sku='SAMPLE-A', qty=1, price_vnd=100000)
        quoted_result = {'sku': 'SAMPLE-A', 'final_price_vnd': 100000, 'applied_promos': []}
    calls = [
        {'name': 'catalog.search', 'args': {'sku': 'SAMPLE-A'}, 'result': {'items': [{
            'sku': 'SAMPLE-A', 'name': 'Máy Mẫu', 'variants': [],
            'attributes': {'connectivity': 'Zigbee', 'tds_output_ppm': 10}}]}},
        {'name': 'inventory.check', 'args': {'sku': 'SAMPLE-A', 'on': '2030-04-08'},
         'result': {'sku': 'SAMPLE-A', 'in_stock': True, 'qty': 4}},
        {'name': 'pricing.quote_order' if basket else 'pricing.get_quote',
         'args': quoted_args, 'result': quoted_result},
    ]
    state['session_tool_calls'] = calls
    assert order_evidence_error(state, order_args) is None
    saved = memory_observations(calls)
    encoded = json.dumps(saved, ensure_ascii=False)
    assert state['customer_phone'] not in encoded and address not in encoded
    assert saved[0]['result']['items'][0]['attributes']['connectivity'] == 'Zigbee'
    assert saved[0]['result']['items'][0]['attributes']['tds_output_ppm'] == 10
    assert memory_observations(saved) == saved
    state['session_tool_calls'] = saved
    assert order_evidence_error(state, order_args) is None
    assert order_evidence_error(state, {**order_args, 'address': '35 đường Mới, Hà Nội'}) == 'current_quote_required'
    state['customer_phone'] = '0900000022'
    assert order_evidence_error(state, {**order_args, 'customer_phone': '0900000022'}) == 'current_quote_required'


def test_quote_persistence_keeps_failed_refresh_barrier_and_promotion_conditions():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from test_text_harness_contract import turn_state

    state = turn_state('Ưu đãi này còn áp dụng không?')
    args = {'sku': 'SAMPLE-A', 'on': '2030-04-08', 'qty': 1}
    quote = {'name': 'pricing.get_quote', 'args': args, 'result': {
        'sku': 'SAMPLE-A', 'final_price_vnd': 100000, 'applied_promos': [],
        'ineligible_promos': [{'promo_code': 'SALE-A', 'reason': 'min_qty'}],
        'not_applied_exclusive': ['SALE-B'], 'estimated_delivery': '2030-04-10'}}
    saved = memory_observations([quote])
    assert saved[0]['result']['ineligible_promos'] == [{'promo_code': 'SALE-A', 'reason': 'min_qty'}]
    assert saved[0]['result']['estimated_delivery'] == '2030-04-10'
    saved += memory_observations([{'name': 'pricing.get_quote', 'args': args,
                                   'result': {'error': 'unavailable'}}])
    state['session_tool_calls'] = saved
    assert not any(call['name'] == 'pricing.get_quote' for call in build_commerce_evidence(state))


def test_repeated_blocked_reads_stop_and_can_recover_after_catalog_evidence():
    from app.agent.implementations.business_agent import BusinessTools
    from test_text_harness_contract import turn_state

    async def run():
        class Gateway:
            async def invoke(self, name, args):
                assert name == 'pricing.get_quote' and args['sku'] == 'SAMPLE-A'
                return {'sku': 'SAMPLE-A', 'final_price_vnd': 100000}

        state = turn_state('Giá mẫu A bao nhiêu?')
        tools = BusinessTools(Gateway(), state, 3, lambda: None)
        first = await tools.invoke('pricing.get_quote', {'sku': 'SAMPLE-A'})
        assert first['error'] == 'catalog_required'
        repeated = await tools.invoke('pricing.get_quote', {'sku': 'SAMPLE-A'})
        assert repeated['error'] == 'repeated_tool_call'
        state['tool_calls'].append({'name': 'catalog.search', 'args': {'sku': 'SAMPLE-A'},
                                   'result': {'items': [{'sku': 'SAMPLE-A', 'variants': []}]}})
        assert (await tools.invoke('pricing.get_quote', {'sku': 'SAMPLE-A'}))['final_price_vnd'] == 100000
    asyncio.run(run())


def test_invalid_tool_proposals_exhaust_model_tool_access():
    from app.agent.implementations.business_agent import BusinessOnlyMiddleware, BusinessTools
    from test_text_harness_contract import turn_state

    async def run():
        state = turn_state('Giá mẫu A bao nhiêu?')
        tools = BusinessTools(None, state, 3, lambda: None)
        for i in range(10):
            result = await tools.invoke('pricing.get_quote', {'sku': f'MISSING-{i}'})
        assert result['error'] == 'tool_limit'
        tools_for_request = tools.langchain_tools()

        class Request:
            tools = tools_for_request
            def override(self, **changes):
                return SimpleNamespace(**changes)

        async def handler(request):
            return request.tools

        assert await BusinessOnlyMiddleware(tools).awrap_model_call(Request(), handler) == []
    asyncio.run(run())


def test_purchase_precondition_reports_only_the_missing_quote():
    from app.agent.implementations.business_agent import BusinessTools
    from test_text_harness_contract import turn_state, old_lamp_reads

    async def run():
        state = turn_state('Tôi đồng ý mua chiếc đèn.')
        state['session_tool_calls'] = [call for call in old_lamp_reads(state)
                                       if call['name'] != 'pricing.get_quote']
        result = await BusinessTools(None, state, 8, lambda: None).invoke('order.create', {
            'sku': 'SKU-LAMP-A', 'qty': 1, 'price_vnd': 199000, 'payment': 'COD'})
        assert result['reason'] == 'current_quote_required'
        assert result['next_tools'] == ['pricing.get_quote']
    asyncio.run(run())


@pytest.mark.parametrize('customer_id', [None, 'C1'])
def test_old_quantities_and_later_corrections_survive_pending_memory_and_restart(customer_id):
    import json
    from app.agent.harness.context import load_context, prompt_context, prompt_messages
    from app.mcp_servers.mcp_memory.services.memory import read
    from test_operational_memory import Repo, Projection, add_turn
    from test_text_harness_contract import turn_state

    class CompleteRepo(Repo):
        async def session_context_turns(self, conn, session):
            return self.sessions[session]['turns']

    async def run():
        repo, sid = CompleteRepo(), str(uuid4())
        first = add_turn(repo, sid, customer_id,
            'Tôi cần 2 máy, bắt buộc Zigbee, tổng ngân sách cả đơn 5 triệu.')
        for i in range(15):
            add_turn(repo, sid, customer_id, f'Tôi hỏi thêm chi tiết thứ {i}.')
        add_turn(repo, sid, customer_id, 'Đổi thành 3 máy, vẫn giữ Zigbee và ngân sách cả đơn.')
        loaded = await read(repo, customer_id, sid, projector=Projection())

        async def read_context(*args):
            return loaded

        state = turn_state('Tư vấn tiếp giúp tôi.')
        state['request'] = state['request'].model_copy(update={'session_id': UUID(sid)})
        state.update(customer_id=customer_id, identity_status='known' if customer_id else 'unknown',
                     received_at_monotonic=0, session_tool_calls=[])
        state.update(await load_context(state, SimpleNamespace(read_context=read_context), None,
            lambda: datetime(2026, 11, 5, tzinfo=timezone.utc)))
        context = prompt_context(state, 6)
        messages = json.dumps([message.content for message in prompt_messages(context)], ensure_ascii=False)
        assert 'Tôi cần 2 máy, bắt buộc Zigbee, tổng ngân sách cả đơn 5 triệu.' in messages
        assert 'Đổi thành 3 máy, vẫn giữ Zigbee và ngân sách cả đơn.' in messages
        assert first in messages
        assert messages.count('Tôi cần 2 máy, bắt buộc Zigbee, tổng ngân sách cả đơn 5 triệu.') == 1
        assert messages.count('Đổi thành 3 máy, vẫn giữ Zigbee và ngân sách cả đơn.') == 1
        assert 'consultation' not in context
    asyncio.run(run())


def test_prompt_context_does_not_repeat_recent_transcripts_and_profile_in_brief():
    import json
    from app.agent.harness.context import prompt_context, prompt_messages
    from test_text_harness_contract import turn_state

    state = turn_state('Tôi hỏi tiếp mẫu đó.')
    tid = str(uuid4())
    turn = {'source_turn_id': tid, 'customer': 'YÊU CẦU RIÊNG CỦA KHÁCH', 'agent': 'NỘI DUNG TƯ VẤN TRƯỚC'}
    state.update(history=[turn], current_episode={'session_id': str(state['request'].session_id),
        'committed_turns': [turn], 'summary': 'Trao đổi sản phẩm.'},
        call_brief={'profile_facts': {'room_area_m2': 25}, 'customer_phone': '0900000011'})
    context = prompt_context(state, 6)
    encoded = json.dumps([message.content for message in prompt_messages(context)], ensure_ascii=False)
    assert encoded.count('YÊU CẦU RIÊNG CỦA KHÁCH') == 1
    assert encoded.count('NỘI DUNG TƯ VẤN TRƯỚC') == 1
    assert 'profile_facts' not in context['call_brief']


def test_catalog_model_schema_distinguishes_list_price_from_customer_budget():
    from app.agent.implementations.business_agent import BusinessTools
    from langchain_core.utils.function_calling import convert_to_openai_tool

    search = next(tool for tool in BusinessTools(None, {}, 8, lambda: None).langchain_tools()
                  if tool.name == 'catalog_search')
    schema = search.args_schema.model_json_schema()
    assert 'max_list_price_vnd' in schema['properties']
    assert 'max_price_vnd' not in schema['properties']
    assert 'max_list_price_vnd' in convert_to_openai_tool(search)['function']['parameters']['properties']
    assert search.args_schema.model_validate({'max_list_price_vnd': 5000000}).model_dump(
        exclude_none=True)['max_list_price_vnd'] == 5000000


def test_model_list_price_argument_reaches_catalog_without_becoming_final_price_filter():
    from app.agent.implementations.business_agent import BusinessTools
    from test_text_harness_contract import turn_state

    async def run():
        class Gateway:
            async def invoke(self, name, args):
                assert name == 'catalog.search'
                assert args['max_price_vnd'] == 5000000
                return {'items': [], 'total': 0}

        state = turn_state('Tìm mẫu giá niêm yết dưới 5 triệu.')
        search = next(tool for tool in BusinessTools(Gateway(), state, 8, lambda: None).langchain_tools()
                      if tool.name == 'catalog_search')
        result = await search.ainvoke({'max_list_price_vnd': 5000000})
        assert result == {'items': [], 'total': 0}
    asyncio.run(run())


def test_empty_list_price_search_cannot_rule_out_discounted_affordable_products():
    from app.agent.guardrails.checks import check_answer
    from app.mcp_servers.mcp_shared.commerce_rules import _catalog, quote

    product = {'sku': 'SAMPLE-A', 'name': 'Máy Mẫu A', 'brand': 'Mẫu', 'category': 'appliance',
               'list_price_vnd': 6000000, 'attributes': {}, 'variants': []}
    promotion = {'promo_code': 'SALE-A', 'applies_to': ['SAMPLE-A'],
                 'start': '2031-03-01', 'end': '2031-03-31', 'type': 'fixed',
                 'discount_vnd': 1500000, 'stackable': False}
    searched = _catalog([product], {'max_price_vnd': 5000000})
    priced = quote([product], [promotion], {'sku': 'SAMPLE-A', 'on': '2031-03-12'})
    assert searched['items'] == [] and priced['final_price_vnd'] == 4500000
    calls = [{'name': 'catalog.search', 'args': {'max_price_vnd': 5000000}, 'result': searched}]
    assert check_answer('Chưa có mẫu trong ngân sách 5 triệu.', calls,
                        'Ngân sách của tôi tối đa 5 triệu.')[1] == 'final_budget_unverified'
    assert check_answer('Chưa có mẫu giá niêm yết dưới ngân sách 5 triệu.', calls,
                        'Ngân sách của tôi tối đa 5 triệu.')[1] is None


@pytest.mark.parametrize('reason,answer,expected', [
    ('unanswered_request', 'Mẫu A có kết nối Zigbee.', None),
    ('unnecessary_clarification', 'Mình muốn hỏi tính năng gì?', None),
    ('customer_constraint_violated', 'Em tư vấn một chiếc màu đỏ.', 'customer_constraint_violated'),
])
def test_grounding_review_only_blocks_explicit_customer_constraint_violations(reason, answer, expected):
    from app.agent.guardrails.semantic_grounding import review_answer
    from test_semantic_grounding import ReviewModel, context

    data = context()
    data['customer_text'] = 'Tôi cần 2 chiếc màu xanh, mẫu B có Wi-Fi không?'
    model = ReviewModel([{'supported': False, 'reason': reason, 'unsupported_claim': answer}])
    assert asyncio.run(review_answer(model, answer, data)) == expected


def test_changed_committed_customer_sources_invalidate_write_review():
    from app.agent.harness.authorization import build_write_context
    from test_text_harness_contract import turn_state

    state = turn_state('Đồng ý mua mẫu đó.')
    state['customer_statements'] = [{'source_turn_id': str(uuid4()), 'customer': 'Tôi cần 2 máy.'}]
    args = {'sku': 'SAMPLE-A', 'qty': 2, 'price_vnd': 100000, 'payment': 'COD',
            'customer_phone': state['customer_phone'], 'on': '2030-04-08'}
    before = build_write_context(state, 'order.create', args)
    state['customer_statements'].append({'source_turn_id': str(uuid4()), 'customer': 'Chỉ tạo đơn nếu giao trước thứ sáu.'})
    assert build_write_context(state, 'order.create', args) != before


@pytest.mark.parametrize('stale_latest', [False, True])
def test_memory_exposes_latest_session_separately_from_one_relevant_episode(stale_latest):
    from app.mcp_servers.mcp_memory.services.memory import read
    from test_operational_memory import Repo, Projection, add_turn

    repo = Repo()
    older, latest, current = str(uuid4()), str(uuid4()), str(uuid4())
    add_turn(repo, older, 'C1', 'Tôi hỏi đèn bàn.')
    add_turn(repo, latest, 'C1', 'Tôi hỏi áo khoác.')
    repo.sessions[older]['turns'][0]['on_date'] = '2030-01-01'
    repo.sessions[latest]['turns'][0]['on_date'] = '2031-03-11'

    class Episodes(Projection):
        async def list_episode_versions(self, customer):
            return [
                {'schema_version': 1, 'session_id': older, 'on': '2030-01-01',
                 'summary': 'Tư vấn đèn bàn', 'channel': 'hotline', 'outcome': 'khac'},
                {'schema_version': 1, 'session_id': latest, 'on': '2029-01-01' if stale_latest else '2031-03-11',
                 'summary': 'Tư vấn áo khoác', 'channel': 'hotline', 'outcome': 'khac'},
            ]

    result = asyncio.run(read(repo, 'C1', current, max_episodes=1,
                              query='đèn bàn', projector=Episodes()))
    assert result['episodes'][0]['session_id'] == older
    assert result['latest_session']['session_id'] == latest
    assert result['latest_session']['on'] == '2031-03-11'


def test_auxiliary_summary_budget_does_not_truncate_customer_requirements():
    from app.agent.harness.context import prompt_context
    from test_text_harness_contract import turn_state

    state = turn_state('Tư vấn tiếp giúp tôi.')
    source = {'source_turn_id': str(uuid4()),
              'customer': 'Tôi cần 3 máy Zigbee, ngân sách tổng đơn 5 triệu.', 'agent': 'Dạ.'}
    state['episodes'] = [{'session_id': str(uuid4()), 'summary': 'Tóm tắt. ' * 2000,
                          'committed_turns': [source]} for _ in range(5)]
    context = prompt_context(state, 6)
    assert sum(len(episode['summary']) for episode in context['previous_episodes']) <= 4000
    assert any(episode.get('summary_truncated') for episode in context['previous_episodes'])
    assert all(episode['committed_turns'][0]['customer'] == source['customer']
               for episode in context['previous_episodes'])
    assert all(len(episode['summary']) == 18000 for episode in state['episodes'])


@pytest.mark.parametrize('address', [
    '12 đường Mẫu, Anh Sơn, Nghệ An',
    '12 đường Mẫu, Minh Khai, Hà Nội',
    '12 đường Mẫu, Chi Lăng, Lạng Sơn',
])
def test_address_component_names_are_not_mistaken_for_customer_clauses(address):
    text = f'Địa chỉ: {address}, tôi chỉ lấy 2 cái.'
    assert resolve_redacted_address(text) == address
    assert 'tôi chỉ lấy 2 cái' in mask_pii(text)
    assert address.split(', ')[1] not in mask_pii(text)


@pytest.mark.parametrize('suffix', [
    'lấy 2 cái thanh toán momo',
    'lấy hai máy và thanh toán COD',
])
def test_spoken_address_preserves_unpunctuated_quantity_and_payment(suffix):
    text = f'Địa chỉ 12 đường Mẫu Hà Nội {suffix}'
    assert suffix in mask_pii(text)
    assert resolve_redacted_address(text) == '12 đường Mẫu Hà Nội'


def test_large_public_catalog_evidence_and_late_receipts_are_not_silently_lost():
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations

    details = {'name': 'catalog.get_details', 'args': {'sku': 'SAMPLE-A'}, 'result': {'items': [{
        'sku': 'SAMPLE-A', 'name': 'Máy Mẫu', 'attributes': {'connectivity': 'Zigbee'},
        'technical_evidence': [{'content': 'Thông số kỹ thuật công khai. ' * 1500}]}]}}
    assert memory_observations([details])[0]['result']['items'][0]['attributes']['connectivity'] == 'Zigbee'
    calls = [{'name': 'crm.get_customer', 'args': {}, 'result': {'found': True}}]
    calls.extend({'name': 'inventory.check', 'args': {'sku': f'SAMPLE-{i}', 'on': '2031-03-12'},
                  'result': {'sku': f'SAMPLE-{i}', 'in_stock': True, 'qty': 2}} for i in range(19))
    calls.append({'name': 'order.create', 'args': {'sku': 'SAMPLE-18', 'qty': 1, 'price_vnd': 100000},
                  'result': {'order_id': 'ORDER-LAST', 'status': 'created', 'total_vnd': 100000}})
    saved = memory_observations(calls)
    assert len(saved) == 20
    assert saved[-1]['result']['order_id'] == 'ORDER-LAST'


def test_model_tool_recovery_hints_use_the_exposed_tool_names():
    from app.agent.implementations.business_agent import BusinessTools
    from test_text_harness_contract import turn_state

    async def run():
        tools = BusinessTools(None, turn_state('Giá mẫu đó?'), 8, lambda: None)
        quote = next(tool for tool in tools.langchain_tools() if tool.name == 'pricing_get_quote')
        result = await quote.ainvoke({'sku': 'UNKNOWN'})
        assert result['next_tool'] == 'catalog_search'
    asyncio.run(run())


def test_failed_memory_cannot_expose_cached_customer_requirements():
    import json
    from app.agent.harness.context import prompt_context
    from test_text_harness_contract import turn_state

    state = turn_state('Tôi hỏi tiếp.')
    state.update(tool_failed=True, customer_statements=[{
        'source_turn_id': str(uuid4()), 'customer': 'YÊU CẦU RIÊNG KHÔNG ĐƯỢC TÁI DÙNG'}])
    assert 'YÊU CẦU RIÊNG' not in json.dumps(prompt_context(state, 6), ensure_ascii=False)


def test_anonymous_source_query_retains_older_turns_and_isolates_the_session():
    import sqlite3
    from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ':memory:' AS runtime")
    conn.execute('CREATE TABLE runtime.turns (session_id TEXT, turn_no INTEGER, customer_text TEXT, client_msg_id TEXT, tool_observations TEXT)')
    sid = str(uuid4())
    conn.executemany('INSERT INTO runtime.turns VALUES (?, ?, ?, ?, ?)', [
        (sid, i, f'Yêu cầu {i}', str(uuid4()), '[]') for i in range(17)])
    conn.execute('INSERT INTO runtime.turns VALUES (?, ?, ?, ?, ?)',
                 (str(uuid4()), 0, 'Phiên khác', str(uuid4()), '[]'))

    class Connection:
        async def fetch(self, query, *args):
            return [dict(row) for row in conn.execute(query,
                {str(index): str(arg) for index, arg in enumerate(args, 1)})]

    try:
        rows = asyncio.run(object.__new__(MemoryRepo).session_context_turns(Connection(), sid))
        assert len(rows) == 17
        assert rows[0]['customer_text'] == 'Yêu cầu 0'
        assert rows[-1]['customer_text'] == 'Yêu cầu 16'
        assert all(row['customer_text'] != 'Phiên khác' for row in rows)
    finally:
        conn.close()


def test_price_argument_mismatch_uses_existing_quote_instead_of_repeating_reads():
    from app.agent.implementations.business_agent import BusinessTools
    from test_text_harness_contract import turn_state, old_lamp_reads

    async def run():
        state = turn_state('Tôi đồng ý mua một chiếc đèn.')
        state['session_tool_calls'] = old_lamp_reads(state)
        result = await BusinessTools(None, state, 8, lambda: None).invoke('order.create', {
            'sku': 'SKU-LAMP-A', 'qty': 1, 'price_vnd': 100000, 'payment': 'COD'})
        assert result['reason'] == 'price_mismatch'
        assert result['next_tools'] == []
    asyncio.run(run())


def test_model_round_limit_stops_schema_retries_that_never_reach_business_tools():
    from app.agent.implementations.business_agent import BusinessOnlyMiddleware, BusinessTools

    async def run():
        state = {'tool_count': 0, 'tool_attempts': 0}
        business = BusinessTools(None, state, 3, lambda: None)
        middleware = BusinessOnlyMiddleware(business)

        class Request:
            tools = business.langchain_tools()
            def override(self, **changes):
                return SimpleNamespace(**changes)

        async def handler(request):
            return request.tools

        for _ in range(6):
            assert await middleware.awrap_model_call(Request(), handler)
        assert await middleware.awrap_model_call(Request(), handler) == []
        assert state == {'tool_count': 0, 'tool_attempts': 0}
    asyncio.run(run())
