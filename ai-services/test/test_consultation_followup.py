"""Follow-up behavior uses customer sources and public evidence, never benchmark labels."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from test_consultation_shortlist import consultation_state, clock, products
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.guardrails.checks import check_answer, check_grounding


def task(state):
    from app.mcp_servers.mcp_shared.consultation_followup import followup_task
    return followup_task(state)


def quoted(state, price=5200000, promos=None):
    state['tool_calls'].append({'name': 'pricing.get_quote',
        'args': {'sku': 'SKU-ASTER', 'qty': 1, 'on': '2026-11-05'},
        'result': {'sku': 'SKU-ASTER', 'final_price_vnd': price,
                   'applied_promos': promos or [], 'freeship': True}})
    return state


def policy_result(status='applicable', *, retrieval='ok', missing=None):
    return {'retrieval_status': retrieval, 'context': {},
        'evidence_set': {'required_dependencies_complete': not missing,
                         'missing_required_section_ids': missing or []},
        'evidence': [] if retrieval != 'ok' else [{'chunk_id': 'WARRANTY', 'section_id': 'warranty',
            'document_id': 'public', 'content': 'Bảo hành 24 tháng cho lỗi kỹ thuật do nhà sản xuất. Không bảo hành hư hỏng do sử dụng sai hướng dẫn.',
            'evidence_type': 'business_rule', 'source': {},
            'applicability': {'status': status, 'missing_required_section_ids': missing or []}}]}


class FollowupGateway:
    def __init__(self):
        self.calls = []
        self.policy = policy_result()
        self.quote = {'sku': 'SKU-ASTER', 'final_price_vnd': 5200000,
            'applied_promos': [{'type': 'gift', 'promo_code': 'GIFT-PUBLIC', 'gift_sku': 'SKU-GIFT'}],
            'freeship': True}
    async def invoke(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == 'policy.search': return deepcopy(self.policy)
        if name == 'pricing.get_quote': return deepcopy(self.quote)
        if name == 'catalog.search': return {'items': deepcopy(products())}
        raise AssertionError(name)


def test_policy_question_has_priority_over_pause_and_does_not_require_order():
    s = consultation_state('Aster Air bảo hành thế nào? Tôi cân nhắc thêm rồi báo lại.')
    t = task(s)
    assert t.kind == 'policy' and 'bảo hành' in t.policy_query.lower()
    gateway = FollowupGateway()
    business = BusinessTools(gateway, s, 6, clock)
    async def run():
        await business.prepare_followup(t)
        await business.prepare_followup(t)
    asyncio.run(run())
    assert len(gateway.calls) == 1
    name, args = gateway.calls[0]
    assert name == 'policy.search' and args['on'] == '2026-11-05'
    assert 'order_id' not in args and 'order_date' not in args
    from app.agent.harness.session_nodes import safe_followup_reply
    answer = safe_followup_reply(s, t)
    assert '24 tháng' in answer and 'sai hướng dẫn' in answer
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None
    assert not any(c['name'].startswith('order.') for c in s['tool_calls'])


def test_price_objection_needs_benefits_not_just_repeat_price():
    from app.agent.harness.agent_nodes import _task_answer_complete
    from app.agent.harness.session_nodes import safe_followup_reply
    s = quoted(consultation_state('Aster Air bên kia bán 4590k, sao bên em đắt hơn?'),
        promos=[{'type': 'freecod', 'promo_code': 'COD-ZERO', 'discount_vnd': 0}])
    t = task(s)
    assert t.kind == 'price_objection' and t.focus_sku == 'SKU-ASTER'
    assert not _task_answer_complete('Aster Air có giá 5.200.000đ.', s)
    answer = safe_followup_reply(s, t)
    assert '5.200.000' in answer and 'miễn phí' in answer and 'COD' in answer
    assert '4590' not in answer and '4.590.000' not in answer
    assert 'rẻ hơn' not in answer and 'đắt hơn' not in answer
    assert check_grounding(answer, s['tool_calls'] + s['session_tool_calls']) is None
    assert check_answer(answer, s['tool_calls'] + s['session_tool_calls'], s['safe_text'])[1] is None


def test_global_competitor_price_without_product_binding_does_not_create_objection():
    s = consultation_state('Tôi gọi lại về Aster Air.')
    s['profile'] = {'competitor_price_vnd': {'value': 1000000, 'status': 'active',
        'source_kind': 'customer', 'source': f'langmem:{uuid4()}:{uuid4()}'}}
    assert task(s).kind == 'none'


def test_model_policy_evidence_reuse_and_failure_are_bounded():
    s = consultation_state('Aster Air bảo hành thế nào?')
    t = task(s)
    gateway = FollowupGateway(); gateway.policy = policy_result(retrieval='timeout')
    business = BusinessTools(gateway, s, 6, clock)
    async def run():
        await business.prepare_followup(t)
        await business.prepare_followup(t)
    asyncio.run(run())
    assert len(gateway.calls) == 1
    from app.agent.harness.session_nodes import safe_followup_reply
    answer = safe_followup_reply(s, t)
    assert 'chưa' in answer.lower() and '24' not in answer
    assert 'timeout' not in answer and 'quota' not in answer


def test_returning_objection_is_scoped_and_resolved_price_is_not_reopened():
    s = consultation_state('Tôi gọi lại về Aster Air hôm trước.')
    old_session, old_turn = str(uuid4()), str(uuid4())
    s['scoped_facts'] = {'product': {'SKU-ASTER': {'objection': {
        'value': 'đắt quá', 'source_kind': 'customer', 'status': 'active',
        'source': f'langmem:{old_session}:{old_turn}'}}}}
    assert task(s).kind == 'returning_objection'
    other = deepcopy(s)
    other['scoped_facts']['product'] = {'SKU-BERYL': s['scoped_facts']['product']['SKU-ASTER']}
    assert task(other).kind == 'none'
    s['history'].append({'source_turn_id': str(uuid4()), 'customer': 'Thôi được, chấp nhận giá.', 'agent': 'Em ghi nhận.'})
    assert task(s).kind == 'none'


def test_policy_model_read_reused_but_explicit_reads_still_revalidate():
    s = consultation_state('Aster Air bảo hành thế nào?')
    t = task(s); gateway = FollowupGateway(); business = BusinessTools(gateway, s, 6, clock)
    async def run():
        await business.invoke('policy.search', {'query': t.policy_query})
        await business.prepare_followup(t)
        assert len(gateway.calls) == 1
        await business.invoke('policy.search', {'query': t.policy_query})
    asyncio.run(run())
    assert len(gateway.calls) == 2


def test_policy_context_release_must_match_before_reuse():
    from app.knowledge.context import release_context
    s = consultation_state('Aster Air bảo hành thế nào?')
    t = task(s); gateway = FollowupGateway(); business = BusinessTools(gateway, s, 6, clock)
    s['tool_calls'] = [{'name': 'policy.search', 'args': {'query': t.policy_query, 'on': '2026-11-05'},
        'result': {**policy_result(), 'context': {'knowledge_release_id': 'release-old'}}}]
    gateway.policy['context'] = {'knowledge_release_id': 'release-current'}
    with release_context('release-current'):
        asyncio.run(business.prepare_followup(t))
    assert len(gateway.calls) == 1


def test_policy_budget_exhausted_does_not_retry_or_invent_terms():
    from app.agent.harness.session_nodes import safe_followup_reply
    s = consultation_state('Aster Air bảo hành thế nào?'); s['tool_count'] = 6
    t = task(s); gateway = FollowupGateway(); business = BusinessTools(gateway, s, 6, clock)
    asyncio.run(business.prepare_followup(t))
    assert not gateway.calls
    answer = safe_followup_reply(s, t)
    assert 'chưa xác minh' in answer.lower() and '24' not in answer


def test_policy_deferred_without_question_does_not_start_a_lookup():
    s = consultation_state('Tôi chưa cần hỏi bảo hành nữa, để tôi cân nhắc thêm.')
    assert task(s).kind == 'none'


@pytest.mark.parametrize('field,entry,expected', [
    ('expired_promos', 'PROMO-OLD', 'đã hết hạn'),
    ('ineligible_promos', {'promo_code': 'PROMO-OLD'}, 'không đủ điều kiện'),
    ('not_applied_exclusive', 'PROMO-OLD', 'không được cộng dồn'),
    ('applied_promos', None, 'chưa xác minh được tình trạng'),
])
def test_promotion_status_is_explained_from_the_correct_evidence(field, entry, expected):
    from app.agent.harness.session_nodes import safe_followup_reply
    s = quoted(consultation_state('Aster Air đắt quá, mã PROMO-OLD còn không?'))
    if entry is not None: s['tool_calls'][-1]['result'][field] = [entry]
    answer = safe_followup_reply(s, task(s))
    assert expected in answer
    if field != 'expired_promos': assert 'hết hạn' not in answer
    assert check_answer(answer, s['tool_calls'] + s['session_tool_calls'], s['safe_text'])[1] is None


@pytest.mark.parametrize('status,missing', [('conditional', None), ('conflict', None), ('applicable', ['exception'])])
def test_policy_without_entitlement_or_exceptions_does_not_become_an_unqualified_answer(status, missing):
    from app.agent.harness.session_nodes import safe_followup_reply
    s = consultation_state('Aster Air bảo hành thế nào?'); t = task(s)
    s['tool_calls'] = [{'name': 'policy.search', 'args': {'query': t.policy_query, 'on': '2026-11-05'},
                        'result': policy_result(status, missing=missing)}]
    answer = safe_followup_reply(s, t)
    assert '24 tháng' not in answer and 'chưa xác minh' in answer.lower()
    assert check_answer(answer, s['tool_calls'], s['safe_text'])[1] is None


def test_policy_order_date_comes_only_from_owned_order_status():
    s = consultation_state('Bảo hành đơn OD-OWN đã mua hôm trước còn áp dụng không?')
    s['owned_order_ids'] = ['OD-OWN']
    t = task(s)
    class Gateway(FollowupGateway):
        async def invoke(self, name, args):
            if name == 'order.status':
                self.calls.append((name, deepcopy(args)))
                return {'orders': [{'order_id': 'OD-OWN', 'created_on': '2026-10-01'}]}
            return await super().invoke(name, args)
    gateway = Gateway(); business = BusinessTools(gateway, s, 6, clock)
    asyncio.run(business.prepare_followup(t))
    assert [name for name, _ in gateway.calls] == ['order.status', 'policy.search']
    assert gateway.calls[-1][1]['order_date'] == '2026-10-01'
    other = consultation_state('Bảo hành đơn OD-OTHER đã mua hôm trước còn áp dụng không?')
    gateway = Gateway(); business = BusinessTools(gateway, other, 6, clock)
    asyncio.run(business.prepare_followup(task(other)))
    assert not gateway.calls


def test_missing_policy_info_is_targeted_and_a_good_model_answer_is_preserved():
    from app.agent.harness.agent_nodes import _task_answer_complete
    s = consultation_state('Aster Air bảo hành thế nào?'); t = task(s)
    s['tool_calls'] = [{'name': 'policy.search', 'args': {'query': t.policy_query, 'on': '2026-11-05'},
                       'result': policy_result()}]
    assert not _task_answer_complete('Aster Air giá 5.200.000đ.', s)
    assert _task_answer_complete('Bảo hành 24 tháng cho lỗi kỹ thuật do nhà sản xuất. Không bảo hành hư hỏng do sử dụng sai hướng dẫn.', s)


def test_same_query_and_date_for_different_owned_orders_is_not_a_shared_policy_read():
    from dataclasses import replace
    s = consultation_state('Bảo hành đơn OD-FIRST còn áp dụng không?')
    s['owned_order_ids'] = ['OD-FIRST', 'OD-SECOND']
    first = task(s)
    class Gateway(FollowupGateway):
        async def invoke(self, name, args):
            if name == 'order.status':
                self.calls.append((name, deepcopy(args)))
                return {'orders': [{'order_id': args['order_id'], 'created_on': '2026-10-01'}]}
            return await super().invoke(name, args)
    gateway = Gateway(); business = BusinessTools(gateway, s, 6, clock)
    async def run():
        await business.prepare_followup(first)
        await business.prepare_followup(replace(first, order_id='OD-SECOND'))
    asyncio.run(run())
    assert [name for name, _ in gateway.calls].count('policy.search') == 2


def test_reported_order_date_allows_conditional_explanation_without_verified_entitlement():
    from app.agent.harness.agent_nodes import _task_answer_complete
    s = consultation_state('Bảo hành đơn OD-OWN mua hôm trước còn áp dụng không?')
    s['owned_order_ids'] = ['OD-OWN']; t = task(s)
    result = policy_result('conditional')
    result['evidence'][0]['applicability']['required_context'] = ['order_date']
    s['tool_calls'] = [{'name': 'policy.search', 'args': {'query': t.policy_query, 'on': '2026-11-05',
        'customer_reported_order_date': '2026-11-04'}, 'result': result}]
    explanation = 'Theo ngày mình khai, bảo hành 24 tháng cho lỗi kỹ thuật do nhà sản xuất; em chưa xác minh quyền lợi của đơn.'
    assert _task_answer_complete(explanation, s)
    assert not _task_answer_complete('Đơn của mình đủ điều kiện bảo hành 24 tháng.', s)


def test_failed_order_lookup_is_not_repeated_by_automatic_preparation():
    s = consultation_state('Bảo hành đơn OD-OWN còn áp dụng không?')
    s['owned_order_ids'] = ['OD-OWN']
    class Gateway(FollowupGateway):
        async def invoke(self, name, args):
            assert name == 'order.status'
            self.calls.append((name, deepcopy(args)))
            return {'error': 'unavailable'}
    gateway = Gateway(); business = BusinessTools(gateway, s, 6, clock)
    async def run():
        await business.prepare_followup(task(s))
        await business.prepare_followup(task(s))
    asyncio.run(run())
    assert [name for name, _ in gateway.calls] == ['order.status']


def test_followup_quote_shares_two_sku_preparation_budget():
    s = consultation_state('Aster Air đắt quá.')
    gateway = FollowupGateway(); business = BusinessTools(gateway, s, 6, clock)
    # The same per-turn ledger is used by prepare_consultation, including failed quotes.
    business._prepared_quote_skus.update({'SKU-BERYL', 'SKU-CEDAR'})
    asyncio.run(business.prepare_followup(task(s)))
    assert not gateway.calls
    business._prepared_quote_skus.remove('SKU-CEDAR')
    async def run():
        await business.prepare_followup(task(s))
        await business.prepare_followup(task(s))
    asyncio.run(run())
    assert [name for name, _ in gateway.calls] == ['pricing.get_quote']
