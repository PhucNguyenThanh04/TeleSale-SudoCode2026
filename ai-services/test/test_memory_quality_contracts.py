"""Evidence-gated supplements and semantic diagnostics across unrelated values."""
import json
from datetime import date
import pytest
from app.agent.memory.langmem_extractor import _supplement_customer_facts
from app.schemas.langmem import ProfileFactCandidate
from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
from eval_harness.memory_recall import _slot_value_matches


@pytest.mark.parametrize('amount', [3210, 6780])
def test_invalid_proposal_does_not_suppress_valid_supplement(amount):
    text = f'Bên kia bán {amount}k, sao shop đắt hơn?'
    candidate = ProfileFactCandidate(key='competitor_price_vnd', value=999000,
        source_kind='customer', source_turn_id='wrong-turn', evidence_quote='bịa giá',
        observed_on=date(2026, 11, 2))
    turn = {'content': json.dumps({'turn_id':'latest', 'on':'2026-11-02', 'customer_text':text})}
    facts = _supplement_customer_facts(turn, [candidate])
    assert any(f.key == 'competitor_price_vnd' and f.value == amount * 1000 for f in facts)


def test_real_conflicts_do_not_depend_on_candidate_order():
    text = 'Bên kia bán 3210k và bên khác bán 6780k.'
    turns = [{'customer_id':'C-LOCAL','session_id':'S-LOCAL','turn_id':'T-LOCAL','customer_text':text}]
    def proposal(value):
        return ProfileFactCandidate(key='competitor_price_vnd', value=value,
            source_kind='customer', source_turn_id='T-LOCAL', evidence_quote=text,
            observed_on=date(2026,11,2))
    accepted, rejected = admit_profile_candidates('C-LOCAL','S-LOCAL',
        [proposal(3210000), proposal(6780000), proposal(3210000)], turns, [])
    assert accepted == []
    assert rejected


@pytest.mark.parametrize('expected,actual,matches', [
    ('can hoi chong','cần hỏi chồng',True),
    ('can hoi vo','cần hỏi bà xã',True),
    ('cần hỏi chồng','đã hỏi chồng',False),
    ('cần hỏi vợ','không cần hỏi vợ',False),
    ('cần hỏi vợ','cần hỏi chồng',False),
    ('so sánh giá','cần cân nhắc thêm',False),
])
def test_blocker_semantics(expected, actual, matches):
    assert _slot_value_matches('blocker', expected, actual) is matches
