import json
from datetime import date
import pytest
from app.schemas.langmem import ProfileFactCandidate
from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
from eval_harness.memory_recall import _slot_value_matches




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
