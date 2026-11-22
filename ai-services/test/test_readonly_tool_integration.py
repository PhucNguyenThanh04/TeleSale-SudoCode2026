import asyncio
from datetime import date
from unittest.mock import AsyncMock

from app.agent.implementations.business_agent import BusinessTools
from app.agent.mcp.gateway import MCPGateway
from app.mcp_servers.mcp_catalog.tools.handlers import create_server as catalog_server
from app.mcp_servers.mcp_order.tools.handlers import create_server as order_server
from test_catalog_details import Repo as DetailsRepo
from test_catalog_evidence import rules
from test_order_update_lines import Repo as OrderRepo
from test_write_authorization import current, NOW


class Repo(OrderRepo):
    def __init__(self):
        super().__init__()
        self.details = DetailsRepo()

    async def rows(self, session, table):
        if table in {'products', 'policy_chunks'}:
            return await self.details.rows(session, table)
        return await super().rows(session, table)

    async def same_day_orders(self, *args):
        return []


def state():
    result = current('Cho tôi biết phương án, tôi chưa đồng ý tạo phiếu.')
    result.update(customer_id='OWNER-LINES', customer_phone='0900000061',
                  owned_order_ids=['LINE-ORDER'], tool_calls=[], session_tool_calls=[])
    result['request'] = result['request'].model_copy(update={'channel_identity': '0900000061', 'on': date(2034, 6, 8)})
    return result


def test_agent_can_preview_without_consent_but_cannot_write_from_preview_alone():
    async def run():
        repo = Repo()
        try:
            reviewer = AsyncMock(return_value=False)
            gateway = MCPGateway(None, order_server(repo, context_secret='read-secret'), None, context_secret='read-secret')
            business = BusinessTools(gateway, state(), 8, lambda: NOW, authorize_write=reviewer)
            tool = next(t for t in business.langchain_tools() if t.name == 'order_preview_update')
            args = {'order_id': 'LINE-ORDER', 'action': 'return', 'line_index': 0, 'qty': 1}
            result = await tool.ainvoke(args)
            assert result['status'] == 'preview' and result['refund_vnd'] == 110000
            assert result['on'] == '2034-06-08'
            reviewer.assert_not_awaited()
            denied = await business.invoke('order.update', args)
            assert denied['error'] == 'customer_authorization_required'
            assert not await repo.order_updates(repo.session, 'LINE-ORDER')
        finally:
            repo.close()
    asyncio.run(run())


def test_details_flow_into_quote_policy_memory_and_grounding(monkeypatch):
    from app.mcp_servers.mcp_shared import catalog_evidence
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    from app.agent.guardrails.checks import check_answer
    from app.agent.guardrails.semantic_grounding import _review_context
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    from test_policy_search import search_fixture
    from test_policy_rules import chunk

    async def run():
        monkeypatch.setattr(catalog_evidence, 'load_rules', rules)
        repo = Repo()
        service, _, _ = await search_fixture([chunk(date_basis='on', required_context=['product'])])
        try:
            gateway = MCPGateway(catalog_server(repo, context_secret='read-secret'), None, None,
                                 knowledge=create_server(service, context_secret='read-secret'), context_secret='read-secret')
            current_state = state()
            business = BusinessTools(gateway, current_state, 8, lambda: NOW)
            tool = next(t for t in business.langchain_tools() if t.name == 'catalog_get_details')
            result = await tool.ainvoke({'sku': 'LAB-DEVICE'})
            assert result['items'][0]['specifications']
            quote = await business.invoke('pricing.get_quote', {'sku': 'LAB-DEVICE'})
            assert quote['final_price_vnd'] == 131000
            policy = await business.invoke('policy.search', {'query': 'warranty', 'product_sku': 'LAB-DEVICE'})
            assert policy['context']['product_source'] == 'catalog.get_details'
            assert policy['evidence'][0]['applicability']['status'] == 'applicable'
            saved = memory_observations(current_state['tool_calls'])
            detail = next(c for c in saved if c['name'] == 'catalog.get_details')
            assert detail['result']['items'][0]['specifications'][0]['sources'][0]['source_hash']
            assert check_answer('Studio controller có 4 lõi.', current_state['tool_calls'])[1] is None
            from app.agent.memory.deterministic_tool_facts import verified_tool_candidates
            facts = verified_tool_candidates('Studio controller có 4 lõi.', saved, 'turn-lab', '2034-06-08')
            assert any(f.key == 'product_advised' and f.source_tool == 'catalog.get_details' for f in facts)
            reviewed = _review_context({'tool_observations': current_state['tool_calls']})
            assert any(c['name'] == 'catalog.get_details' for c in reviewed['tool_observations'])
        finally:
            repo.close()
            await service.close()
    asyncio.run(run())


def test_grounding_accepts_preview_amounts_but_not_an_invented_amount():
    from app.agent.guardrails.checks import check_answer
    call = {'name': 'order.preview_update', 'args': {'order_id': 'LINE-ORDER', 'action': 'return', 'on': '2034-06-08'},
            'result': {'order_id': 'LINE-ORDER', 'action': 'return', 'status': 'preview', 'estimate': True,
                'requires_policy_check': True, 'refund_vnd': 110000, 'estimated_total_refund_vnd': 110000,
                'estimated_total_payment_vnd': 0}}
    assert check_answer('Số tiền hoàn dự kiến là 110.000đ.', [call])[1] is None
    assert check_answer('Số tiền hoàn dự kiến là 150.000đ.', [call])[1] is not None


def test_semantic_review_receives_estimate_scope_for_a_completed_action_claim():
    from langchain_core.messages import HumanMessage
    from app.agent.guardrails.semantic_grounding import review_answer
    import json
    from unittest.mock import Mock
    answer = 'Tôi đã tạo phiếu trả hàng và hoàn tiền cho anh.'
    model = Mock()
    reviewer = model.with_structured_output.return_value
    reviewer.ainvoke = AsyncMock(return_value={'supported': False, 'reason': 'unsupported_claim', 'unsupported_claim': answer})
    call = {'name': 'order.preview_update', 'result': {'status': 'preview', 'estimate': True, 'requires_policy_check': True}}
    assert asyncio.run(review_answer(model, answer, {'tool_observations': [call]})) == 'unsupported_answer_claim'
    message = next(m for m in reviewer.ainvoke.await_args.args[0] if isinstance(m, HumanMessage))
    observed = json.loads(message.content)['context']['tool_observations'][0]
    assert observed['name'] == 'order.preview_update' and observed['result']['estimate'] is True


def test_preview_replacement_availability_is_a_scoped_inventory_observation():
    from app.agent.guardrails.checks import check_answer
    call = {'name': 'order.preview_update', 'args': {'order_id': 'LINE-ORDER', 'action': 'exchange_product'},
            'result': {'status': 'preview', 'estimate': True, 'new_variant_sku': 'SKU-LAB-NEW',
                'replacement_inventory': {'sku': 'SKU-LAB-NEW', 'in_stock': True, 'qty': 9}}}
    assert check_answer('SKU-LAB-NEW còn hàng.', [call])[1] is None
    assert check_answer('SKU-UNKNOWN còn hàng.', [call])[1] is not None
    same = {'name': 'inventory.check', 'args': {'sku': 'SKU-LAB-NEW'}, 'result': call['result']['replacement_inventory']}
    assert check_answer('SKU-LAB-NEW còn hàng.', [same, call])[1] is None


def test_preview_refresh_and_failed_refresh_replace_older_estimates():
    from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
    current_state = state()
    args = {'order_id': 'LINE-ORDER', 'action': 'return', 'on': '2034-06-08'}
    first = {'name': 'order.preview_update', 'args': args, 'result': {'status': 'preview', 'estimate': True, 'refund_vnd': 110000}}
    second = {'name': 'order.preview_update', 'args': args, 'result': {'status': 'preview', 'estimate': True, 'refund_vnd': 120000}}
    current_state['tool_calls'] = [first, second]
    view = build_commerce_evidence(current_state)
    assert len(view) == 1 and view[0]['result']['refund_vnd'] == 120000
    assert first['result']['refund_vnd'] == 110000
    current_state['tool_calls'].append({'name': 'order.preview_update', 'args': args, 'result': {'error': 'order_not_owned'}})
    assert not build_commerce_evidence(current_state)


def test_distinct_preview_options_can_supply_estimated_amounts_together():
    from app.agent.guardrails.checks import check_answer
    calls = [{'name': 'order.preview_update', 'args': {'order_id': 'LINE-ORDER', 'line_index': i},
        'result': {'status': 'preview', 'estimate': True, 'refund_vnd': amount}}
        for i, amount in enumerate((110000, 70000))]
    assert check_answer('Dòng thứ nhất hoàn dự kiến 110.000đ; dòng thứ hai hoàn dự kiến 70.000đ.', calls)[1] is None
