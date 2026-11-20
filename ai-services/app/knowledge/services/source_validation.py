from datetime import date
from app.knowledge.schemas import KnowledgeError


async def validate_sources(tx, refs):
    if not refs or len(refs) > 10:
        raise KnowledgeError('One to ten public source chunks required')
    ids = [r['chunk_id'] for r in refs]
    if len(set(ids)) != len(ids):
        raise KnowledgeError('Duplicate source')
    rows = {r['chunk_id']: r for r in await tx.sources(ids)}
    bases, starts, ends = set(), [], []
    for ref in refs:
        row = rows.get(ref['chunk_id'])
        if not row or row.get('access_level') != 'public' or not row.get('source_hash'):
            raise KnowledgeError('Source unavailable or restricted')
        if row['source_hash'] != ref['source_hash']:
            raise KnowledgeError('Source changed; review again')
        bases.add(row.get('date_basis'))
        if row.get('effective_from'):
            starts.append(str(row['effective_from']))
        if row.get('effective_until'):
            ends.append(str(row['effective_until']))
    if len(bases) != 1 or not bases <= {'call_date', 'order_date'}:
        raise KnowledgeError('Incompatible source date bases; split the revision')
    start, end = max(starts, default=None), min(ends, default=None)
    if start and end and start > end:
        raise KnowledgeError('Sources have no shared validity interval')
    return {'date_basis': next(iter(bases)), 'effective_from': start, 'effective_until': end}


def applicable(metadata, on, order_date=None):
    value = order_date if metadata['date_basis'] == 'order_date' else on
    if not value:
        return False
    date.fromisoformat(value)
    return ((not metadata.get('effective_from') or value >= metadata['effective_from'])
            and (not metadata.get('effective_until') or value <= metadata['effective_until']))
