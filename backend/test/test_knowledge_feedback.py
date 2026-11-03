import copy
import json
import unittest
from datetime import date
from types import SimpleNamespace
from contextlib import asynccontextmanager
import httpx
from app.services.knowledge_service import feedback, deliver_once
from fastapi import HTTPException


class Result:
    def __init__(self, row=None): self.row = row
    def one_or_none(self): return self.row
    def scalar_one_or_none(self): return self.row


class Session:
    def __init__(self): self.outbox = {}; self.owner = 'staff'
    @asynccontextmanager
    async def begin(self):
        old = copy.deepcopy(self.outbox)
        try: yield
        except Exception:
            self.outbox = old
            raise
    async def execute(self, statement, params=None):
        sql = str(statement)
        if 'FROM runtime.chat_sessions' in sql:
            return Result(SimpleNamespace(customer_id='c', call_date=date(2026,10,15),
                question='số 0123456789', answer='chưa rõ') if params['actor'] == self.owner else None)
        if sql.startswith('SELECT data'):
            return Result(self.outbox.get(params['id']))
        if sql.startswith('INSERT INTO knowledge.backend_outbox'):
            self.outbox.setdefault(params['id'], json.loads(params['data']))
        if sql.startswith('SELECT id,data'):
            return Result(next((SimpleNamespace(id=k, data=copy.deepcopy(v)) for k,v in self.outbox.items()
                                if v['status']=='pending'), None))
        if sql.startswith('UPDATE knowledge.backend_outbox'):
            self.outbox[params['id']] = json.loads(params['data'])
        return Result()


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def payload(self):
        return {'session_id':'11111111-1111-4111-8111-111111111111', 'turn_no':1,
            'rating':False, 'reason':'sai CCCD 123456789012', 'correction':'', 'idempotency_key':'k'}

    async def test_owned_feedback_is_durable_masked_and_idempotent(self):
        db = Session()
        a = await feedback(db, 'staff', self.payload())
        self.assertEqual(a, await feedback(db, 'staff', self.payload()))
        self.assertEqual(len(db.outbox), 1)
        self.assertNotIn('0123456789', str(db.outbox))
        self.assertNotIn('123456789012', str(db.outbox))
        with self.assertRaises(HTTPException) as exc:
            await feedback(db, 'attacker', self.payload())
        self.assertEqual(exc.exception.status_code, 404)
        with self.assertRaises(HTTPException) as exc:
            await feedback(db, 'staff', self.payload() | {'reason':'changed'})
        self.assertEqual(exc.exception.status_code, 409)

    async def test_delivery_failure_keeps_event_then_ack_marks_delivered(self):
        db = Session(); await feedback(db, 'staff', self.payload())
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(503 if len(requests)==1 else 200, json={'detail':'unavailable'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://test') as ai:
            await deliver_once(db, ai)
            self.assertEqual(next(iter(db.outbox.values()))['status'], 'pending')
            await deliver_once(db, ai)
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(next(iter(db.outbox.values()))['status'], 'delivered')

    async def test_erasure_during_delivery_cannot_restore_outbox_payload(self):
        db = Session(); await feedback(db, 'staff', self.payload())
        def handler(request):
            key = next(iter(db.outbox))
            db.outbox[key] = {'id':key, 'status':'erased'}
            return httpx.Response(200, json={'status':'received'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test') as ai:
            await deliver_once(db, ai)
        self.assertEqual(next(iter(db.outbox.values()))['status'], 'erased')
        self.assertNotIn('payload', next(iter(db.outbox.values())))
