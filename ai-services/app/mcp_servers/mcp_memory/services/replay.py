from app.mcp_servers.mcp_shared.pii import mask_pii


async def replay_turn(repo, customer_id, session_id, client_msg_id, request_hash):
    async with repo.transaction() as conn:
        if customer_id:
            await repo.lock_key(conn, f'erasure:{customer_id}')
            if await repo.is_erasure_blocked(conn, customer_id):
                completed = (getattr(repo, 'supports_erasure_state', False) is True
                             and await repo.erasure_state(conn, customer_id) == 'completed')
                return {'error': 'customer_erased' if completed else 'customer_erasure_in_progress'}
        owner = await repo.owner(conn, session_id)
        if owner is not None and owner != customer_id:
            return {'error': 'session_owner_mismatch'}
        row = await repo.replay_turn(conn, session_id, client_msg_id)
        if row is None:
            if (callable(getattr(type(repo), 'has_committed_writes', None))
                    and await repo.has_committed_writes(conn, session_id, client_msg_id)):
                return {'found': True, 'agent_text': '', 'tool_observations': []}
            return {'found': False}
        if row.get('request_hash') != request_hash:
            return {'error': 'turn_retry_conflict'}
        return {'found': True, 'agent_text': mask_pii(row['agent_text']),
                'tool_observations': row['tool_observations']}
