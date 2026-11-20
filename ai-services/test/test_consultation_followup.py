import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from test_consultation_shortlist import consultation_state, clock, products
from app.agent.implementations.business_agent import BusinessTools
from app.agent.harness.agent_nodes import AgentNodes
from app.agent.guardrails.checks import check_answer, check_grounding




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
