"""Read-only chronological history; never rank by query or generate summaries."""
import asyncio
from datetime import date

from app.mcp_servers.mcp_memory.repos.langmem_projection import select_episodes
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.schemas.timeline import TimelineItem, TimelinePage


async def read_timeline(repo, customer_id, session_id, on, offset=0, limit=10,
                        crm_sessions=(), projector=None):
    on = date.fromisoformat(on) if isinstance(on, str) else on
    try:
        async with asyncio.timeout(2):
            async with repo.transaction() as conn:
                if customer_id:
                    await repo.lock_key(conn, f'erasure:{customer_id}')
                    if await repo.is_erasure_blocked(conn, customer_id):
                        return {'error': 'customer_erasure_in_progress'}
                owner = await repo.owner(conn, session_id)
                if owner is not None and owner != customer_id:
                    return {'error': 'session_owner_mismatch'}
                if not customer_id:
                    return TimelinePage(status='not_applicable', offset=offset, limit=limit).model_dump(mode='json')
                if projector is None:
                    return {'error': 'memory_store_unavailable'}
                await repo.lock_key(conn, f'langmem:{customer_id}')
                versions = await projector.list_episode_versions(customer_id)
                revisions = sorted({v['revision'] for v in versions if isinstance(v, dict)
                    and type(v.get('revision')) is int and v['revision'] > 0})
                completed = await repo.completed_job_revisions(conn, customer_id, revisions)
                latest = select_episodes(versions, completed)
                asof = [v for v in versions if isinstance(v, dict)
                        and (v.get('on') or v.get('on_date'))
                        and str(v.get('on') or v.get('on_date')) <= on.isoformat()]
                episodes = select_episodes(asof, completed)
                sessions = await repo.timeline_sessions(conn, customer_id, on)
                hidden = {str(v['session_id']) for v in [*latest, *episodes]
                          if v.get('deleted') or v.get('status', 'active') != 'active'}
                records = {str(v['session_id']): dict(v) for v in crm_sessions
                           if str(v['date']) <= on.isoformat()}
                for episode in episodes:
                    if episode.get('customer_id', customer_id) != customer_id:
                        hidden.add(str(episode['session_id']))
                        continue
                    records[str(episode['session_id'])] = dict(episode)
                for session in sessions:
                    sid = str(session['session_id'])
                    record = records.setdefault(sid, {})
                    record.update(session_id=sid, on=session['on_date'], channel=session['channel'])
                    if session.get('outcome') and session['outcome'] != 'khac':
                        record['outcome'] = session['outcome']
                    if session.get('memory_status') in {'pending', 'leased'}:
                        record['summary_status'] = 'pending'
                items = []
                for sid, record in records.items():
                    if sid in hidden:
                        continue
                    summary = record.get('summary', '').strip()
                    item = TimelineItem(session_id=sid,
                        on=record.get('on') or record.get('on_date') or record.get('date'),
                        channel=record.get('channel', 'other'),
                        summary=mask_pii(summary)[:800] if summary else 'Chưa có bản tóm tắt được xác minh.',
                        outcome=record.get('outcome') or 'khac',
                        summary_status=record.get('summary_status') or ('ready' if summary else 'unavailable'))
                    if item.on <= on:
                        items.append(item)
                # shortcut: scan one customer's versions/metadata before paging; use a
                # keyset query if long histories exceed the two-second read budget.
                items.sort(key=lambda item: (item.on, item.session_id), reverse=True)
                page = items[offset:offset+limit]
                end = offset + len(page)
                return TimelinePage(items=page, offset=offset, limit=limit, total=len(items),
                    next_offset=end if end < len(items) else None).model_dump(mode='json')
    except TimeoutError:
        return {'error': 'memory_store_unavailable'}
