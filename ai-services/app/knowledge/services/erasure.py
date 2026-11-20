from app.knowledge.schemas import timestamp


async def erase_in_transaction(tx, customer_id):
    await tx.put('erasures', customer_id, {'id': customer_id, 'at': timestamp()})
    affected = set()
    for event in await tx.rows('events'):
        if event.get('customer_id') == customer_id:
            affected.add(event['id'])
            await tx.put('events', event['id'], {'id': event['id'], 'status': 'erased', 'source': event['source']})
            job = await tx.get('jobs', event['id'])
            if job:
                await tx.put('jobs', job['id'], {'id': job['id'], 'status': 'erased', 'event_id': event['id'], 'attempts': 0})
    gaps = set()
    for gap in await tx.rows('gaps'):
        if set(gap.get('event_ids', [])) & affected:
            gaps.add(gap['id'])
            await tx.put('gaps', gap['id'], {'id': gap['id'], 'status': 'erased', 'version': gap['version']+1, 'event_ids': []})
    revisions = set()
    for revision in await tx.rows('revisions'):
        if revision.get('gap_id') in gaps:
            revisions.add(revision['id'])
            await tx.put('revisions', revision['id'], {'id': revision['id'], 'status': 'erased'})
            await tx.put('regression_cases', revision['id'], {'id': revision['id'], 'approved': False, 'status': 'erased'})
    for decision in await tx.rows('decisions'):
        if decision.get('revision_id') in revisions:
            await tx.put('decisions', decision['id'], {k: v for k, v in decision.items() if k != 'reason'})
    for release in await tx.rows('releases'):
        if any(i.get('id') in revisions for i in release.get('manifest', {}).get('items', [])):
            if release.get('manifest', {}).get('index_kind') == 'hybrid':
                for item in release['manifest']['items']:
                    if item.get('id') in revisions:
                        key = 'KG-' + item['id']
                        await tx.put('policy_revocations', key, {'id': key, 'at': timestamp()})
                for row in await tx.rows('policy_sources'):
                    if row.get('release_id') == release['id']:
                        await tx.put('policy_sources', row['id'], {'id': row['id'], 'status': 'erased'})
            await tx.put('releases', release['id'], {'id': release['id'], 'status': 'erased'})
            active = await tx.get('active', 'current')
            if active and active.get('release_id') == release['id']:
                await tx.put('active', 'current', {'id': 'current', 'release_id': 'btc-only', 'reason': 'erasure'})
    for outbox in await tx.rows('backend_outbox'):
        if outbox.get('payload', {}).get('event', {}).get('customer_id') == customer_id:
            await tx.put('backend_outbox', outbox['id'], {'id': outbox['id'], 'status': 'erased'})
    return {'status': 'completed', 'erased_events': len(affected), 'erased_revisions': len(revisions)}


async def erase_customer(repo, customer_id):
    async with repo.transaction() as tx:
        return await erase_in_transaction(tx, customer_id)
