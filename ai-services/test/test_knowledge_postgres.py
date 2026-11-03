"""Opt-in checks against an already provisioned, explicitly selected test DB."""
import os
import unittest
from uuid import uuid4
from sqlalchemy import text


@unittest.skipUnless(os.getenv('KNOWLEDGE_TEST_DSN') and os.getenv('KNOWLEDGE_EXPECTED_TEST_DATABASE'),
                     'Requires KNOWLEDGE_TEST_DSN and an explicitly approved KNOWLEDGE_EXPECTED_TEST_DATABASE')
class KnowledgePostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_transaction_and_role_boundaries(self):
        from app.knowledge.repo import KnowledgeRepo
        from app.knowledge.ingest import record_event
        repo = KnowledgeRepo(os.environ['KNOWLEDGE_TEST_DSN'])
        try:
            async with repo.transaction() as tx:
                name = (await tx.session.execute(text('SELECT current_database()'))).scalar_one()
                self.assertEqual(name, os.environ['KNOWLEDGE_EXPECTED_TEST_DATABASE'],
                                 'Database must match the explicitly approved test identity')
                for table in ('active','decisions','releases','permissions'):
                    allowed = (await tx.session.execute(text('SELECT has_table_privilege(:role,:table,:permission)'),
                        {'role':'knowledge_worker','table':'knowledge.'+table,'permission':'INSERT'})).scalar_one()
                    self.assertFalse(allowed)
            key='test-'+uuid4().hex
            event={'source':'runtime_signal','question':'Kiểm thử tri thức tổng hợp','signal':'no_evidence'}
            a=await record_event(repo,event,key)
            b=await record_event(repo,event,key)
            self.assertEqual(a,b)
            async with repo.transaction() as tx:
                self.assertEqual((await tx.get('events',a['id']))['status'],'pending')
                self.assertEqual((await tx.get('jobs',a['id']))['status'],'pending')
            # Retain only the scoped synthetic records; never reset/clean a DB here.
        finally:
            await repo.close()
