from eval_harness.test_support import VoiceLifecycleStub
import pytest
from eval_harness.reference_adapter import facts_used, _source_session_id


@pytest.mark.parametrize("source,expected", [
    ("langmem:prior:turn-1", "prior"), ("prior:turn-1", "prior"),
    ("langmem:prior", None), ("langmem::turn-1", None), ("garbage", None), (None, None)])
def test_source_parser(source, expected):
    assert _source_session_id(source) == expected


def test_prior_room_area_used_as_catalog_filter_with_scope_and_source():
    scoped = {'room': {'bedroom': {'room_area_m2': fact(25)}}}
    calls = [{'name': 'catalog.search', 'args': {'min_room_area_m2': 25}, 'result': {'items': []}}]
    assert facts_used('Em đang tìm mẫu phù hợp.', calls, {}, scoped, 'now',
                      customer_text='Tìm máy cho phòng ngủ hôm trước.') == ['room_area_m2']
    assert facts_used('Dạ.', calls, {}, scoped, 'now', customer_text='Phòng ngủ 25m2.') == []
    assert facts_used('Dạ.', calls, {}, scoped, 'now', customer_text='Phòng khách hôm trước.') == []
    scoped['room']['living_room'] = {'room_area_m2': fact(25)}
    assert facts_used('Dạ.', calls, {}, scoped, 'now') == []


def test_budget_filter_is_prior_use_only_without_current_repetition():
    calls = [{'name': 'catalog.search', 'args': {'max_price_vnd': 5500000}, 'result': {'items': []}}]
    assert facts_used('Dạ.', calls, {'budget_vnd': fact(5500000)}, current_session_id='now') == ['budget_vnd']
    assert facts_used('Dạ.', calls, {'budget_vnd': fact(5500000)}, current_session_id='now',
                      customer_text='Ngân sách tối đa 5,5 triệu.') == []


def variant_catalog():
    return {'name': 'catalog.search', 'args': {}, 'result': {'items': [
        {'sku': 'SKU-HIKE', 'name': 'Giày HikePro', 'variants': [
            {'variant_sku': 'SKU-HIKE-41-XAM', 'size': 41, 'color': 'xam'},
            {'variant_sku': 'SKU-HIKE-42-XAM', 'size': 42, 'color': 'xam'}]}]}}


@pytest.mark.parametrize('result', [{'in_stock': True}, {'error': 'failed'}])
def test_exact_catalog_variant_demonstrates_size_color_use(result):
    scoped = {'product': {'SKU-HIKE': {'size': fact(41), 'color': fact('xám')}}}
    calls = [{'name': 'inventory.check', 'args': {'sku': 'SKU-HIKE-41-XAM'}, 'result': result}]
    expected = [] if 'error' in result else ['color', 'size']
    assert facts_used('Dạ.', calls, {}, scoped, 'now', catalog_calls=[variant_catalog()]) == expected
    assert facts_used('Dạ.', calls, {}, scoped, 'now') == []
    calls[0]['args']['sku'] = 'SKU-HIKE-42-XAM'
    assert 'size' not in facts_used('Dạ.', calls, {}, scoped, 'now', catalog_calls=[variant_catalog()])
    scoped['product'] = {'SKU-OTHER': {'size': fact(41), 'color': fact('xám')}}
    assert facts_used('Dạ.', calls, {}, scoped, 'now', catalog_calls=[variant_catalog()]) == []


def test_handoff_uses_explicit_product_field_not_arbitrary_nested_text():
    scoped = {'product': {'SKU-HIKE': {'product_advised': fact('SKU-HIKE')}}}
    calls = [{'name': 'handoff.transfer', 'args': {'brief': {'product_advised': 'SKU-HIKE'}},
              'result': {'ticket_id': 'H1'}}]
    assert facts_used('Em đã chuyển yêu cầu.', calls, {}, scoped, 'now') == ['product_advised']
    calls[0]['args']['brief'] = {'conversation_summary': 'SKU-HIKE'}
    assert facts_used('Em đã chuyển yêu cầu.', calls, {}, scoped, 'now') == []


def test_spoken_variant_attributes_bind_to_the_catalog_parent_fact_scope():
    scoped = {'product': {'SKU-HIKE': {'size': fact(41), 'color': fact('xam')}}}
    assert facts_used('Đôi HikePro màu xám size 41 còn hàng.', [], {}, scoped, 'now',
                      catalog_calls=[variant_catalog()]) == ['color', 'size']
    assert facts_used('Đôi HikePro màu xám size 41 còn hàng.', [], {}, scoped, 'now',
                      customer_text='HikePro size 41 màu xám nhé.', catalog_calls=[variant_catalog()]) == []
    assert facts_used('Đôi HikePro màu xám size 42 còn hàng.', [], {}, scoped, 'now',
                      catalog_calls=[variant_catalog()]) == ['color']


def fact(value, source="langmem:prior:turn-1"):
    return {"value": value, "source": source}


def test_same_session_unknown_source_and_customer_repetition_are_not_recall():
    for source in ["langmem:now:turn-1", "garbage", None]:
        assert facts_used("Mẫu SKU-LOCAL có sẵn.", [], {"product_advised": fact("SKU-LOCAL", source)}, current_session_id="now") == []
    assert facts_used("Ngân sách 2 triệu.", [], {"budget_vnd": fact(2000000)},
                      current_session_id="now", customer_text="Ngân sách tôi 2 triệu") == []


def test_money_and_boolean_meaning():
    assert facts_used("Giá đã báo 2731k.", [], {"price_quoted_vnd": fact(2731000)}, current_session_id="now") == ["price_quoted_vnd"]
    assert facts_used("Vì bé nhà mình, mẫu này có khóa trẻ em.", [], {"has_children": fact(True)}, current_session_id="now") == ["has_children"]
    assert facts_used("Nhà không có trẻ nhỏ.", [], {"has_children": fact(True)}, current_session_id="now") == []
    assert facts_used("Dạ", [{"name": "catalog.search", "args": {"include_discontinued": True}}], {"has_children": fact(True)}, current_session_id="now") == []


def test_product_scope_and_argument_semantics():
    scoped = {"product": {"SKU-A": {"price_quoted_vnd": fact(730000)},
                          "SKU-B": {"competitor_price_vnd": fact(730000)}}}
    calls = [{"name": "order.create", "args": {"sku": "SKU-A", "price_vnd": 730000}, "result":{"ok":True}}]
    assert facts_used("Dạ", calls, {}, scoped, "now") == ["price_quoted_vnd"]
    assert facts_used("Giá 730000đ.", [], {}, scoped, "now") == []
    assert facts_used("SKU-A giá 730000đ.", [], {}, scoped, "now") == ["price_quoted_vnd"]


def test_harness_uses_call_start_snapshot_not_current_turn_memory():
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from eval_harness.benchmark_runner import run_scenario_call

    class Runtime(VoiceLifecycleStub):
        count = 0
        async def run(self, request):
            self.count += 1
            return SimpleNamespace(agent_text="SKU-LOCAL", call_brief=None)
        def state_for(self, request):
            source = "langmem:prior:turn-1" if self.count == 1 else f"langmem:{request.session_id}:turn-1"
            return {"profile": {"product_advised": fact("SKU-LOCAL", source)},
                    "tool_calls": [], "memory_writes": []}

    rows = asyncio.run(run_scenario_call(Runtime(), "LOCAL", "call_2",
        {"customer_turns": ["Chào em", "Tiếp tục nhé"]}, date(2026, 11, 2), "0900000000"))
    assert [r["facts_used"] for r in rows] == [["product_advised"], ["product_advised"]]


@pytest.mark.parametrize('text', ['Phòng ngủ 25m2 phù hợp.', 'Phòng NGỦ rộng 25 m² nhé.', 'Bedroom 25m2 phù hợp.'])
def test_room_alias_requires_previous_session_scope_and_value(text):
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used(text,[],{},scoped,'now') == ['room_area_m2']
    for source in ('langmem:now:1', 'invalid', None):
        assert facts_used(text,[],{}, {'room':{'bedroom':{'room_area_m2':fact(25,source)}}}, 'now') == []


@pytest.mark.parametrize('text', [
    'Phòng khách 25m2 phù hợp.', 'Phòng ngủ 30m2 phù hợp.', '25m2 phù hợp.',
    'Phòng ngủ 30m2 và phòng khách 25m2.', 'Phòng ngủ không phải 25m2.',
    'Phòng ngủ 25m2 hay 30m2?', 'Phòng ngủ 25m2x phù hợp.',
])
def test_room_scope_cannot_borrow_value_or_negated_question(text):
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used(text,[],{},scoped,'now') == []


def test_customer_repetition_is_checked_in_the_same_room():
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used('Phòng ngủ 25m2.',[],{},scoped,'now',customer_text='Phòng ngủ 25m2.') == []
    assert facts_used('Phòng ngủ 25m2.',[],{},scoped,'now',customer_text='Phòng khách 25m2.') == ['room_area_m2']


@pytest.mark.parametrize('result', [{'error':'failed'}, {'ok':False}, {'success':False}])
def test_failed_tool_is_not_evidence_of_use(result):
    calls=[{'name':'order.create','args':{'sku':'SKU-A','price_vnd':730000},'result':result}]
    assert facts_used('Dạ',calls,{}, {'product':{'SKU-A':{'price_quoted_vnd':fact(730000)}}}, 'now') == []


def test_product_identity_boundary_and_unknown_session_are_conservative():
    scoped={'product':{'SKU-A':{'price_quoted_vnd':fact(730000)}}}
    assert facts_used('SKU-AB giá 730000đ.',[],{},scoped,'now') == []
    assert facts_used('SKU-A giá 730000đ.',[],{},scoped) == []


@pytest.mark.parametrize('text,expected', [
    ('Lần trước chị cần bàn với ông xã trước khi mua.', ['blocker']),
    ('Chị cần hỏi ý kiến chồng trước khi chốt.', ['blocker']),
    ('Chị đã bàn với chồng và anh đồng ý rồi.', []),
    ('Chị cần hỏi vợ trước khi mua.', []),
    ('Chị có cần bàn với chồng không?', []),
])
def test_controlled_blocker_paraphrase_keeps_dependency_polarity(text,expected):
    assert facts_used(text,[],{'blocker':fact('cần hỏi chồng')},current_session_id='now') == expected


def test_area_before_single_room_and_correction_keeps_scope():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}}}
    assert facts_used('Diện tích 31m2 của phòng ngủ phù hợp.',[],{},scoped,'now') == ['room_area_m2']
    assert facts_used('Phòng ngủ không phải 25m2 mà là 31m2.',[],{},scoped,'now') == ['room_area_m2']
    assert facts_used('Phòng ngủ không phải 25m2 mà là 31m2.',[],{}, {'room':{'bedroom':{'room_area_m2':fact(25)}}},'now') == []


def test_identical_area_in_other_room_is_not_the_prior_fact():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}, 'living_room':{'room_area_m2':fact(25)}}}
    assert facts_used('Phòng ngủ 25m2 và phòng khách 31m2.',[],{},scoped,'now') == []


def test_negation_in_product_category_does_not_negate_spoken_price():
    assert facts_used('Máy lọc không khí có giá 730000đ.',[],{'price_quoted_vnd':fact(730000)},current_session_id='now') == ['price_quoted_vnd']


def test_unknown_other_room_does_not_supply_bedroom_value():
    scoped={'room':{'bedroom':{'room_area_m2':fact(25)}}}
    assert facts_used('Phòng ngủ 30m2 và phòng trẻ em 25m2.',[],{},scoped,'now') == []


def test_unscoped_customer_repetition_does_not_create_scoped_memory_credit():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}}}
    assert facts_used('Phòng ngủ 31m2.',[],{},scoped,'now',customer_text='Diện tích 31m2 nhé.') == []


@pytest.mark.parametrize('source',['langmem: :t1',' prior:t1','langmem:prior: '])
def test_whitespace_source_is_not_valid_provenance(source):
    assert facts_used('Phòng 31m2.',[],{'room_area_m2':fact(31,source)},current_session_id='now') == []


def test_confirming_known_previous_fact_is_still_observable_use():
    scoped={'room':{'bedroom':{'room_area_m2':fact(31)}}}
    assert facts_used('Phòng ngủ 31m2 đúng không?',[],{},scoped,'now') == ['room_area_m2']
    assert facts_used('Phòng ngủ 31m2 đúng không?',[],{},scoped,'now',customer_text='Phòng ngủ 31m2.') == []


def catalog_names():
    return [{'name': 'catalog.search', 'args': {}, 'result': {'items': [
        {'sku': 'SKU-A', 'name': 'Máy lọc Aster Air'},
        {'sku': 'SKU-B', 'name': 'Máy lọc Beryl Air'}]}}]


def test_product_name_counts_as_prior_product_use_without_requiring_spoken_sku():
    scoped = {'product': {'SKU-A': {'product_advised': fact('SKU-A')}}}
    assert facts_used('Lần trước mình xem Aster Air.', [], {}, scoped, 'now',
                      catalog_calls=catalog_names()) == ['product_advised']
    assert facts_used('Lần trước mình xem Aster Air.', [], {}, scoped, 'now',
                      customer_text='Tôi hỏi Aster Air.', catalog_calls=catalog_names()) == []


@pytest.mark.parametrize('text', ['Lần trước mình xem Beryl Air.', 'Lần trước mình xem Air.',
                                 'Nếu mình chọn Aster Air thì báo em.', 'Không phải Aster Air.'])
def test_product_alias_does_not_credit_other_ambiguous_or_negated_products(text):
    scoped = {'product': {'SKU-A': {'product_advised': fact('SKU-A')}}}
    assert facts_used(text, [], {}, scoped, 'now', catalog_calls=catalog_names()) == []


@pytest.mark.parametrize('status', ['inactive', 'superseded', 'expired', 'deleted'])
def test_nonactive_fact_is_not_observable_recall(status):
    prior = {'budget_vnd': {**fact(2000000), 'status': status}}
    assert facts_used('Ngân sách 2 triệu.', [], prior, current_session_id='now') == []


def test_catalog_name_can_bind_spoken_price_to_prior_product_scope():
    scoped = {'product': {'SKU-A': {'price_quoted_vnd': fact(730000)}}}
    assert facts_used('Aster Air giá 730.000đ.', catalog_names(), {}, scoped, 'now') == ['price_quoted_vnd']


@pytest.mark.parametrize('text', ['Beryl Air giá 730.000đ.', 'Air giá 730.000đ.',
    'Aster Air giá 800.000đ và Beryl Air giá 730.000đ.', 'Aster Air giá 800.000đ.',
    'SKU-A giá 800.000đ và Beryl Air giá 730.000đ.'])
def test_catalog_names_do_not_borrow_other_product_values_or_ambiguous_aliases(text):
    scoped = {'product': {'SKU-A': {'price_quoted_vnd': fact(730000)}}}
    assert facts_used(text, catalog_names(), {}, scoped, 'now') == []


def test_named_customer_repetition_and_same_session_still_are_not_memory_credit():
    scoped = {'product': {'SKU-A': {'price_quoted_vnd': fact(730000)}}}
    text = 'Aster Air giá 730.000đ.'
    assert facts_used(text, catalog_names(), {}, scoped, 'now', customer_text=text) == []
    scoped['product']['SKU-A']['price_quoted_vnd']['source'] = 'langmem:now:t1'
    assert facts_used(text, catalog_names(), {}, scoped, 'now') == []


def test_prior_catalog_in_same_call_can_bind_name_when_current_turn_only_quotes():
    scoped = {'product': {'SKU-A': {'price_quoted_vnd': fact(730000)}}}
    assert facts_used('Aster Air giá 730.000đ.', [], {}, scoped, 'now',
                      catalog_calls=catalog_names()) == ['price_quoted_vnd']


@pytest.mark.parametrize('failure', [{'error': 'unavailable'}, {'ok': False}, {'success': False}])
def test_failed_catalog_is_not_product_name_evidence(failure):
    calls = catalog_names()
    calls[0]['result'].update(failure)
    scoped = {'product': {'SKU-A': {'price_quoted_vnd': fact(730000)}}}
    assert facts_used('Aster Air giá 730.000đ.', calls, {}, scoped, 'now') == []


@pytest.mark.parametrize('text,expected', [
    ('Lần trước chị băn khoăn giá Aster Air hơi cao.', ['objection']),
    ('Giá Aster Air quá đắt.', ['objection']),
    ('Giá Aster Air không cao.', []),
    ('Chị không còn băn khoăn giá Aster Air.', []),
    ('Lần trước chị băn khoăn giá Beryl Air hơi cao.', []),
])
def test_price_objection_paraphrase_stays_bound_to_product_and_polarity(text, expected):
    scoped = {'product': {'SKU-A': {'objection': fact('dat_qua')}}}
    assert facts_used(text, catalog_names(), {}, scoped, 'now') == expected


def test_runner_preserves_catalog_aliases_between_turns_without_recounting_new_facts():
    import asyncio
    from datetime import date
    from types import SimpleNamespace
    from eval_harness.benchmark_runner import run_scenario_call

    class Runtime(VoiceLifecycleStub):
        count = 0
        async def run(self, request):
            self.count += 1
            return SimpleNamespace(agent_text='Dạ.' if self.count == 1 else 'Aster Air giá 730.000đ.', call_brief=None)
        def state_for(self, request):
            return {'request': request, 'profile': {}, 'tool_calls': [],
                'session_tool_calls': catalog_names(), 'scoped_facts': {'product': {'SKU-A': {
                    'price_quoted_vnd': fact(730000),
                    'objection': fact('dat_qua', f'langmem:{request.session_id}:t1')}}}}

    rows = asyncio.run(run_scenario_call(Runtime(), 'GENERIC', 'call_2',
        {'customer_turns': ['Chào em', 'Tiếp tục nhé']}, date(2026, 11, 2), '0900000000'))
    assert [r['facts_used'] for r in rows] == [[], ['price_quoted_vnd']]
    assert rows[0]['facts_used_evidence'] == []
    assert rows[1]['facts_used_evidence'] == [{'field': 'price_quoted_vnd',
        'scope_type': 'product', 'via': ['speech']}]


def test_usage_evidence_records_matching_method_without_fact_values_or_context_presence():
    evidence = []
    prior = {'budget_vnd': fact(2000000)}
    assert facts_used('Dạ.', [], prior, current_session_id='now', usage_evidence=evidence) == []
    assert evidence == []
    assert facts_used('Ngân sách 2 triệu.', [], prior, current_session_id='now',
                      usage_evidence=evidence) == ['budget_vnd']
    assert evidence == [{'field': 'budget_vnd', 'scope_type': 'global', 'via': ['speech']}]
    evidence = []
    calls = [{'name': 'order.create', 'args': {'sku': 'SKU-A', 'price_vnd': 730000}, 'result': {'ok': True}}]
    scoped = {'product': {'SKU-A': {'price_quoted_vnd': fact(730000)}}}
    assert facts_used('Dạ.', calls, {}, scoped, 'now', usage_evidence=evidence) == ['price_quoted_vnd']
    assert evidence == [{'field': 'price_quoted_vnd', 'scope_type': 'product', 'via': ['tool_args']}]
