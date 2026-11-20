from copy import deepcopy
from uuid import uuid4
import pytest
from test_commerce_evidence import catalog,quote


def evidence():
    sid,tid=str(uuid4()),str(uuid4())
    turns=[{'customer_id':'C','session_id':sid,'turn_id':tid,'on':'2026-11-05',
            'customer_text':'Giá Aster bao nhiêu?', 'agent_text':'Aster giá 900.000đ.'}]
    calls=[{**c,'source_turn_id':tid,'customer_id':'C','session_id':sid} for c in [catalog(),quote()]]
    return sid,turns,calls








def test_memory_observations_preserve_offer_fields_without_inventing_unknowns():
    from app.mcp_servers.mcp_shared.memory_observations import memory_observations
    q=quote();q['result']['freeship']=True;q['result']['expired_promos']=['OTHER-OLD']
    result=memory_observations([q])[0]['result']
    assert result['freeship'] is True and result['expired_promos']==['OTHER-OLD']
    del q['result']['freeship']
    assert 'freeship' not in memory_observations([q])[0]['result']
