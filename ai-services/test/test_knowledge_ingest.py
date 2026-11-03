import unittest
from test_knowledge_repo import MemoryRepo
from app.knowledge.events.ingest import record_event


class IngestTests(unittest.IsolatedAsyncioTestCase):
    async def test_erased_customer_cannot_reenter_queue(self):
        from app.knowledge.services.erasure import erase_customer
        from app.knowledge.schemas import Conflict
        repo = MemoryRepo()
        event = {'source': 'runtime_signal', 'question': 'đổi hàng', 'customer_id': 'c'}
        await record_event(repo, event, 'one')
        await erase_customer(repo, 'c')
        with self.assertRaises(Conflict):
            await record_event(repo, event, 'two')
        self.assertNotIn('đổi hàng', str(await repo.rows('events')))

    def test_runtime_signal_selection_preserves_tool_names(self):
        from app.knowledge.events.runtime import turn_event
        event = turn_event({'customer_text': 'đổi', 'agent_text': 'chưa có thông tin',
            'on': '2026-10-15', 'client_msg_id': 'msg', 'outcome': 'khac',
            'tool_observations': [{'name': 'policy.search', 'args': {'query': 'đổi'},
                'result': {'retrieval_status': 'no_evidence', 'evidence': []}}]}, 'session', 'c')
        self.assertEqual(event['signal'], 'no_evidence')
        self.assertEqual(event['tool_calls'][0]['name'], 'policy.search')
        self.assertEqual(event['customer_id'], 'c')
