from uuid import uuid4

from app.agent.memory.deterministic_tool_facts import verified_tool_candidates
from app.mcp_servers.mcp_memory.services.turn_status import public_changes
from app.mcp_servers.mcp_shared.memory_observations import memory_observations


def test_owned_update_status_preview_and_policy_receipts_survive_masked_storage():
    calls = [
        {'name': 'order.update', 'args': {'order_id': 'OD-1', 'action': 'return'},
         'result': {'order_id': 'OD-1', 'status': 'review_pending', 'requires_policy_check': True,
                    'eligibility': {'status': 'pending', 'missing_fields': ['received_on']},
                    'address': '12 đường Hoa Mai', 'customer_phone': '0901234567'}},
        {'name': 'order.status', 'args': {'order_id': 'OD-1'},
         'result': {'order_id': 'OD-1', 'status': 'delivered', 'created_on': '2026-10-01', 'lines': []}},
        {'name': 'order.preview_update', 'args': {'order_id': 'OD-1', 'action': 'return'},
         'result': {'order_id': 'OD-1', 'status': 'preview', 'estimate': True, 'fee_vnd': None}},
        {'name': 'policy.search', 'args': {'query': 'đổi trả', 'on': '2026-10-15'},
         'result': {'retrieval_status': 'ok', 'context': {'on': '2026-10-15', 'knowledge_release_id': 'r1'},
                    'evidence': [{'chunk_id': 'DT-01', 'content': '7 ngày', 'source_hash': 'a'*64}]}}
    ]
    saved = memory_observations(calls)
    assert [call['name'] for call in saved] == [call['name'] for call in calls]
    assert saved[0]['result']['status'] == 'review_pending'
    assert saved[0]['result']['eligibility']['missing_fields'] == ['received_on']
    assert saved[-1]['result']['evidence'][0]['source_hash'] == 'a'*64
    assert '0901234567' not in str(saved) and '12 đường Hoa Mai' not in str(saved)


def test_legacy_successful_callback_receipt_produces_the_same_durable_fact():
    call = {'name': 'schedule.callback', 'args': {'callback_at': '2026-10-15T10:00+07:00'},
            'result': {'callback_id': 'CB0001', 'callback_at': '2026-10-15T10:00+07:00'}}
    saved = memory_observations([call])
    facts = verified_tool_candidates('Em đã đặt lịch gọi lại.', saved, str(uuid4()), '2026-10-15')
    assert any(fact.key == 'callback_scheduled' and fact.value is True for fact in facts)


def test_public_change_uses_actual_fact_provenance():
    changes = public_changes([{'key': 'payment', 'value': 'COD', 'op': 'set',
                               'source_kind': 'tool', 'source_tool': 'order.create'}])
    assert changes[0]['source'] == 'tool'
