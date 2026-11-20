import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest

from test_commerce_evidence import state, catalog, quote, stock
from test_consultation_shortlist import clock
from app.agent.implementations.business_agent import BusinessTools


def returning_state(text):
    s = state(text)
    s['scoped_facts'] = {'product': {'SKU-ASTER': {'product_advised': {
        'value': 'SKU-ASTER', 'source': f'langmem:{uuid4()}:{uuid4()}',
        'source_kind': 'agent', 'status': 'active'}}}}
    s['history'] = [{'customer': 'Tôi gọi lại về Aster.',
        'agent': 'Aster là mẫu mình đã trao đổi.'}]
    return s


class Gateway:
    def __init__(self):
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == 'catalog.search':
            return catalog()['result']
        if name == 'pricing.get_quote':
            return quote()['result']
        if name == 'inventory.check':
            return stock()['result']
        raise AssertionError(name)














@pytest.mark.parametrize('draft', [
    'Aster giá 169.000đ.',
    'Aster được giảm giá 50.000đ.',
    'Aster hiện không có khuyến mãi giảm giá.',
])
def test_verified_replies_reject_wrong_prices_and_promotion_polarity(draft):
    from app.agent.harness.agent_nodes import AgentNodes
    from app.agent.guardrails.checks import check_answer
    s = state('Aster giá bao nhiêu, có khuyến mãi không?')
    c = catalog()
    c['result']['items'][0]['list_price_vnd'] = 1690000
    q = quote(price=1521000)
    q['result'].update(list_price_vnd=1690000, applied_promos=[{
        'type': 'percent', 'promo_code': 'SALE-10', 'discount_vnd': 169000}])
    s.update(tool_calls=[c, q], agent_draft=draft)
    assert check_answer(draft, s['tool_calls'], s['safe_text'])[1] is not None
    reply = asyncio.run(AgentNodes(None, None, None, 5, 6).verify_agent(s))['agent_text']
    assert reply != draft
    assert check_answer(reply, s['tool_calls'], s['safe_text'])[1] is None
