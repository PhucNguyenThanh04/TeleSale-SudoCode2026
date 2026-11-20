from app.knowledge.events.evidence import snapshot
from app.knowledge.schemas import digest, timestamp


def turn_event(data, session_id, customer_id):
    calls = data.get('tool_observations', [])
    statuses = [c.get('result', {}).get('retrieval_status') for c in calls
                if c.get('name') == 'policy.search' and isinstance(c.get('result'), dict)]
    knowledge = data.get('knowledge_evidence', {})
    signal = 'mcp_unavailable' if any(v in {'unavailable','timeout','overloaded'} for v in statuses) else knowledge.get('signal')
    signal = signal or next((v for v in statuses if v in {'no_evidence'}), None)
    if not signal and data.get('knowledge_signal'):
        signal = data['knowledge_signal']
    if not signal and data.get('outcome', 'khac') != 'khac':
        signal = data['outcome']
    if not signal and any(isinstance(c.get('result'), dict) and 'error' in c['result'] for c in calls):
        signal = 'tool_timeout'
    if not signal and any(k in data.get('agent_text', '').lower() for k in
                          ('chưa có thông tin', 'không có thông tin', 'chưa thể xác minh')):
        signal = 'fallback'
    if not signal:
        return None
    ids = [c.get('chunk_id') for call in calls if call.get('name') == 'policy.search'
           for c in call.get('result', {}).get('evidence', []) if c.get('chunk_id')]
    return snapshot({'source': 'business_outcome' if signal in {'chot_don', 'hen_goi_lai', 'chuyen_may'} else 'runtime_signal',
        'question': data['customer_text'], 'answer': data['agent_text'], 'on': data['on'],
        'session_id': session_id, 'message_id': data['client_msg_id'], 'customer_id': customer_id,
        'signal': signal, 'tool_calls': knowledge.get('tool_calls', calls), 'retrieved_ids': knowledge.get('retrieved_ids', ids)})


async def enqueue_turn(conn, data, session_id, customer_id):
    from app.knowledge.repos.postgres import AsyncpgUnitOfWork
    event = turn_event(data, session_id, customer_id)
    if event is None:
        return
    await conn.execute('SELECT pg_advisory_xact_lock(714221, 1)')
    tx = AsyncpgUnitOfWork(conn)
    if customer_id and await tx.get('erasures', customer_id):
        return
    key = digest(['runtime', session_id, data['client_msg_id']])
    if await tx.get('events', key):
        return
    await tx.put('events', key, event | {'id': key, 'payload_hash': digest(event),
                                       'status': 'pending', 'created_at': timestamp()})
    await tx.put('jobs', key, {'id': key, 'event_id': key, 'status': 'pending', 'attempts': 0, 'available_at': 0})
