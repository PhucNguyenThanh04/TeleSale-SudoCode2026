"""Owner-checked feedback and durable, acknowledged delivery to knowledge API."""
import asyncio
import hashlib
import json
import re
import time
from uuid import uuid4
from uuid import UUID
import httpx
from fastapi import HTTPException
from sqlalchemy import text


def clean(value):
    value = re.sub(r'(?<!\d)\d[\d .-]{8,}\d(?!\d)', '[REDACTED]', value)
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', value)
    # Free-text addresses are not needed in gap evidence.
    value = re.sub(r'(?i)(?:địa chỉ|dia chi|cccd|số tài khoản|stk)\s*[:：]?[^\n;]+', '[PRIVATE]', value)
    return value


async def internal_request(ai, method, path, **kwargs):
    try:
        response = await (ai.get(path, **kwargs) if method == 'GET' else ai.post(path, **kwargs))
        if response.status_code >= 400:
            detail = response.json().get('detail', 'Knowledge request failed')
            raise HTTPException(response.status_code, detail)
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, 'Knowledge service unavailable') from exc


async def feedback(db, actor, payload):
    try:
        UUID(payload['session_id'])
    except ValueError:
        raise HTTPException(422, 'Invalid session')
    async with db.begin():
        row = (await db.execute(text('''SELECT s.customer_id,s.call_date,
            (SELECT content FROM runtime.chat_messages WHERE session_id=s.id AND turn_no=:turn AND role='customer' LIMIT 1) AS question,
            (SELECT content FROM runtime.chat_messages WHERE session_id=s.id AND turn_no=:turn AND role='agent' LIMIT 1) AS answer
            FROM runtime.chat_sessions s WHERE s.id=:sid AND s.created_by=:actor'''),
            {'sid': payload['session_id'], 'turn': payload['turn_no'], 'actor': actor})).one_or_none()
        if row is None or row.answer is None:
            raise HTTPException(404, 'Owned agent message not found')
        event = {'source': 'operator_feedback', 'actor_id': actor,
            'session_id': payload['session_id'], 'message_id': str(payload['turn_no']),
            'customer_id': row.customer_id, 'on': row.call_date.isoformat(),
            'question': clean(row.question or ''), 'answer': clean(row.answer),
            'rating': payload['rating'], 'reason': clean(payload['reason']),
            'correction': clean(payload['correction'])}
        await db.execute(text('SELECT pg_advisory_xact_lock(714221, 1)'))
        if row.customer_id and (await db.execute(text('SELECT id FROM knowledge.erasures WHERE id=:id'), {'id':row.customer_id})).one_or_none():
            raise HTTPException(410, 'Customer evidence has been erased')
        key = hashlib.sha256((actor+':'+payload['idempotency_key']).encode()).hexdigest()
        data = json.dumps({'id': key, 'event': event, 'idempotency_key': key}, sort_keys=True, ensure_ascii=False)
        existing = (await db.execute(text('SELECT data FROM knowledge.backend_outbox WHERE id=:id FOR UPDATE'), {'id': key})).scalar_one_or_none()
        if existing and existing['payload'] != json.loads(data):
            raise HTTPException(409, 'Feedback key reused')
        await db.execute(text('''INSERT INTO knowledge.backend_outbox(id,data) VALUES(:id,CAST(:data AS jsonb))
            ON CONFLICT(id) DO NOTHING'''), {'id': key, 'data': json.dumps({'id': key,
                'payload': json.loads(data), 'status': 'pending', 'attempts': 0})})
    return {'id': key, 'status': 'queued'}


async def deliver_once(db, ai):
    # Claim with a lease, then release the DB row lock before remote I/O.
    # Erasure holds the knowledge lock and may redact this outbox meanwhile.
    async with db.begin():
        row = (await db.execute(text("""SELECT id,data FROM knowledge.backend_outbox
            WHERE data->>'status'='pending' OR
              (data->>'status'='running' AND CAST(data->>'lease_until' AS double precision)<:now)
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1"""), {'now':time.time()})).one_or_none()
        if row is None:
            return False
        data = row.data
        lease = str(uuid4())
        data.update(status='running', lease_token=lease, lease_until=time.time()+30)
        await db.execute(text('UPDATE knowledge.backend_outbox SET data=CAST(:data AS jsonb) WHERE id=:id'),
                         {'id':row.id, 'data':json.dumps(data)})
    error = None
    try:
        await internal_request(ai, 'POST', '/v1/knowledge/events', json={
            'event':data['payload']['event'], 'idempotency_key':data['payload']['idempotency_key']})
    except HTTPException as exc:
        error = 'knowledge_http_'+str(exc.status_code)
    async with db.begin():
        current = (await db.execute(text('SELECT data FROM knowledge.backend_outbox WHERE id=:id FOR UPDATE'),
                                   {'id':row.id})).scalar_one_or_none()
        if not current or current.get('lease_token') != lease or current.get('status') == 'erased':
            return True
        if error:
            current['attempts'] += 1
            current.update(status='failed' if current['attempts']>=5 else 'pending', error_code=error)
        else:
            current['status'] = 'delivered'
        await db.execute(text('UPDATE knowledge.backend_outbox SET data=CAST(:data AS jsonb) WHERE id=:id'),
                         {'id':row.id, 'data':json.dumps(current)})
    return True


async def main():
    from app.configs import get_settings
    from app.database.pg_session import create_pg_engine, create_pg_sessionmaker
    cfg = get_settings()
    engine = create_pg_engine(cfg.database_url)
    sessions = create_pg_sessionmaker(engine)
    headers = {'X-AI-Internal-Token': cfg.ai_internal_token.get_secret_value()} if cfg.ai_internal_token else {}
    try:
        async with httpx.AsyncClient(base_url=cfg.ai_service_url, headers=headers, timeout=10) as ai:
            while True:
                async with sessions() as db:
                    delivered = await deliver_once(db, ai)
                await asyncio.sleep(1 if delivered else 3)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
