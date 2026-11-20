from app.knowledge.events.evidence import snapshot
from app.knowledge.schemas import Conflict, digest, timestamp


async def record_event(repo, event, idempotency_key):
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
        raise Conflict('Invalid idempotency key')
    safe = snapshot(event)
    key = digest([safe['source'], safe.get('actor_id'), idempotency_key])
    payload_hash = digest(safe)
    async with repo.transaction() as tx:
        if safe.get('customer_id') and await tx.get('erasures', safe['customer_id']):
            raise Conflict('Customer evidence erased')
        previous = await tx.get('events', key)
        if previous:
            if previous['payload_hash'] != payload_hash:
                raise Conflict('Idempotency key reused for different evidence')
            return {'id': key, 'status': previous['status']}
        await tx.put('events', key, safe | {'id': key, 'payload_hash': payload_hash,
                                          'created_at': timestamp(), 'status': 'pending'})
        await tx.put('jobs', key, {'id': key, 'event_id': key, 'status': 'pending',
                                   'attempts': 0, 'available_at': 0})
        return {'id': key, 'status': 'pending'}
