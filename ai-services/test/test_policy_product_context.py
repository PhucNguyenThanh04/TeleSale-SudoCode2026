import asyncio

import pytest
from pydantic import ValidationError

from app.knowledge.policy.rules import apply_policy_rules
from app.mcp_servers.mcp_knowledge.schemas import PolicySearchInput, TrustedPolicyContext
from app.mcp_servers.mcp_knowledge.tools.auth import sign_policy_context, verify_policy_context
from test_policy_rules import chunk


def context(**extra):
    return TrustedPolicyContext(request_id='lab', principal='harness', on='2032-04-09', **extra)


def test_verified_product_clears_only_product_context():
    request = PolicySearchInput(query='warranty', on='2032-04-09', product_sku='LAB-DEVICE')
    trusted = context(verified_product_sku='LAB-DEVICE', product_source='catalog.search')
    policy = chunk(date_basis='on', required_context=['product', 'receipt'], rules=[{
        'scope': 'Registered devices only', 'required_context': ['product', 'registration']}])
    result = apply_policy_rules([policy], request, trusted)[0]
    assert result.applicability.required_context == ['receipt', 'registration']
    assert result.applicability.status == 'conditional'
    dated = chunk(required_context=['product', 'order_date'])
    result = apply_policy_rules([dated], request, trusted)[0]
    assert result.applicability.required_context == ['order_date']


def test_missing_unverified_and_mismatched_products_never_clear_context():
    policy = chunk(date_basis='on', required_context=['product'])
    request = PolicySearchInput(query='warranty', on='2032-04-09')
    assert apply_policy_rules([policy], request, context())[0].applicability.status == 'conditional'
    forged = request.model_copy(update={'product_sku': 'LAB-DEVICE'})
    with pytest.raises(ValueError, match='product'):
        apply_policy_rules([policy], forged, context())
    with pytest.raises(ValidationError):
        context(verified_product_sku='LAB-DEVICE')
    with pytest.raises(ValidationError):
        context(product_source='catalog.search')
    trusted = context(verified_product_sku='LAB-DEVICE', product_source='catalog.search')
    envelope = sign_policy_context(forged, trusted, 'lab-secret')
    assert verify_policy_context(forged, envelope, 'lab-secret').verified_product_sku == 'LAB-DEVICE'
    with pytest.raises(PermissionError):
        verify_policy_context(forged.model_copy(update={'product_sku': 'OTHER'}), envelope, 'lab-secret')
    wrong = trusted.model_copy(update={'verified_product_sku': 'OTHER'})
    with pytest.raises(PermissionError):
        verify_policy_context(forged, sign_policy_context(forged, wrong, 'lab-secret'), 'lab-secret')


@pytest.mark.parametrize('source', ['catalog.search', 'order.status'])
def test_model_to_signed_mcp_propagates_only_verified_product(source):
    from app.agent.implementations.business_agent import BusinessTools
    from app.agent.mcp.gateway import MCPGateway
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    from test_policy_search import search_fixture
    from test_write_authorization import current, NOW

    async def run():
        service, _, _ = await search_fixture([chunk(date_basis='on', required_context=['product'])])
        gateway = MCPGateway(None, None, None, knowledge=create_server(service, context_secret='lab-secret'),
                             context_secret='lab-secret')
        state = current('Cho biết chính sách cho thiết bị đã chọn.')
        if source == 'catalog.search':
            state['tool_calls'] = [{'name': source, 'args': {'query': 'Lab'}, 'result': {'items': [
                {'sku': 'LAB-DEVICE', 'attributes': {}, 'variants': []}]}}]
            raw = {'query': 'warranty', 'product_sku': 'LAB-DEVICE'}
        else:
            state['tool_calls'] = [{'name': source, 'args': {'order_id': 'LAB-ORDER'}, 'result': {'orders': [
                {'order_id': 'LAB-ORDER', 'created_on': '2026-10-15', 'lines': [
                    {'sku': 'LAB-DEVICE', 'qty': 2, 'price_vnd': 100}]}]}}]
            raw = {'query': 'warranty', 'order_id': 'LAB-ORDER'}
        business = BusinessTools(gateway, state, 8, lambda: NOW)
        tool = next(t for t in business.langchain_tools() if t.name == 'policy_search')
        result = await tool.ainvoke(raw)
        assert result['retrieval_status'] == 'ok'
        assert result['context']['product_sku'] == 'LAB-DEVICE'
        assert result['context']['product_source'] == source
        assert result['evidence'][0]['applicability']['status'] == 'applicable'
        before = business.state['tool_count']
        denied = await business.invoke('policy.search', raw | {'product_sku': 'UNKNOWN'})
        assert 'error' in denied and business.state['tool_count'] == before
    asyncio.run(run())


def test_multiline_order_does_not_guess_a_policy_product():
    from app.agent.harness.policy import prepare_tool_call
    from app.agent.harness.state import Decision
    from test_write_authorization import current, NOW
    state = current('Cho biết bảo hành của đơn.')
    state['tool_calls'] = [{'name': 'order.status', 'args': {'order_id': 'LAB'}, 'result': {'orders': [
        {'order_id': 'LAB', 'date': '2026-10-15', 'lines': [{'sku': 'ONE'}, {'sku': 'TWO'}]}]}}]
    state['decision'] = Decision(action='tool', tool_name='policy.search', tool_args={'query': 'warranty', 'order_id': 'LAB'})
    prepared = prepare_tool_call(state, lambda: NOW)
    assert prepared is not None and 'product_sku' not in prepared[1]
    state['decision'].tool_args['product_sku'] = 'TWO'
    assert prepare_tool_call(state, lambda: NOW)[1]['product_sku'] == 'TWO'


@pytest.mark.parametrize('latest', [{'error': 'order_not_owned'}, {'orders': []}])
def test_repeated_owned_order_reads_use_the_latest_product_and_date_together(latest):
    from app.agent.harness.policy import prepare_tool_call
    from app.agent.harness.state import Decision
    from test_write_authorization import current, NOW
    state = current('Cho biết bảo hành của đơn.')
    state['tool_calls'] = [
        {'name': 'order.status', 'args': {}, 'result': {'orders': [
            {'order_id': 'LAB', 'date': '2026-10-14', 'sku': 'OLD'}]}},
        {'name': 'order.status', 'args': {'order_id': 'LAB'}, 'result': {'orders': [
            {'order_id': 'LAB', 'date': '2026-10-15', 'sku': 'CURRENT'}]}}]
    state['decision'] = Decision(action='tool', tool_name='policy.search', tool_args={'query': 'warranty', 'order_id': 'LAB'})
    prepared = prepare_tool_call(state, lambda: NOW)
    assert prepared is not None
    assert prepared[1]['order_date'] == '2026-10-15' and prepared[1]['product_sku'] == 'CURRENT'
    state['tool_calls'].append({'name': 'order.status', 'args': {'order_id': 'LAB'}, 'result': latest})
    assert prepare_tool_call(state, lambda: NOW) is None
