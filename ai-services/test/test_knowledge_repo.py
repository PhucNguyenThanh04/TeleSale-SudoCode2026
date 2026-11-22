import asyncio
import copy
import unittest
from contextlib import asynccontextmanager


class MemoryRepo:
    def __init__(self, sources=()):
        self.tables = {}
        self.source_rows = {s['chunk_id']: s for s in sources}
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            old = copy.deepcopy(self.tables)
            try:
                yield self
            except Exception:
                self.tables = old
                raise

    async def get(self, table, key):
        return copy.deepcopy(self.tables.get(table, {}).get(key))

    async def get_many(self, table, keys):
        return {key: copy.deepcopy(self.tables[table][key]) for key in keys
                if key in self.tables.get(table, {})}

    async def put(self, table, key, value):
        self.tables.setdefault(table, {})[key] = copy.deepcopy(value)

    async def rows(self, table):
        return copy.deepcopy(list(self.tables.get(table, {}).values()))

    async def sources(self, ids=None):
        return [copy.deepcopy(v) for k, v in self.source_rows.items() if ids is None or k in ids]


class KnowledgeRepoTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_event_and_conflicting_payload(self):
        from app.knowledge.events.ingest import record_event
        from app.knowledge.schemas import Conflict
        repo = MemoryRepo()
        event = {'source': 'operator_feedback', 'question': 'đổi hàng?', 'answer': 'chưa rõ', 'actor_id': 'staff'}
        one = await record_event(repo, event, 'same')
        self.assertEqual(one, await record_event(repo, event, 'same'))
        self.assertEqual(len(await repo.rows('events')), 1)
        with self.assertRaises(Conflict):
            await record_event(repo, event | {'question': 'khác'}, 'same')

    async def test_permissions_are_server_side_and_visitor_is_denied(self):
        from app.knowledge.services.permissions import require_permission
        from app.knowledge.schemas import Forbidden
        repo = MemoryRepo()
        await repo.put('permissions', 'staff', {'id': 'staff', 'permissions': ['knowledge_review']})
        await require_permission(repo, 'staff', 'knowledge_review')
        with self.assertRaises(Forbidden):
            await require_permission(repo, 'web-visitor:fake', 'knowledge_review')
        with self.assertRaises(Forbidden):
            await require_permission(repo, 'other', 'knowledge_review')

    async def test_mask_before_storage_preserves_tool_name(self):
        from app.knowledge.events.ingest import record_event
        repo = MemoryRepo()
        out = await record_event(repo, {'source': 'runtime_signal', 'question': 'số 0123456789',
            'answer': 'CCCD 123456789012', 'tool_calls': [{'name': 'order.create',
            'args': {'customer_phone': '0123456789', 'sku': 'SKU-AP-X', 'price_vnd': 4890000}}]}, 'mask')
        event = await repo.get('events', out['id'])
        self.assertNotIn('0123456789', str(event))
        self.assertNotIn('123456789012', str(event))
        self.assertEqual(event['tool_calls'][0]['name'], 'order.create')
        self.assertEqual(event['tool_calls'][0]['args']['price_vnd'], 4890000)

    def test_settings_load_knowledge_flags_and_hide_credentials(self):
        from app.configs import Settings
        settings = Settings(_env_file=None, llm_api_key='fake', llm_model='fake',
                            knowledge_enabled=True, knowledge_database_url='postgresql+asyncpg://u:password@localhost/db')
        self.assertTrue(settings.knowledge_enabled)
        self.assertNotIn('u:password', repr(settings))
