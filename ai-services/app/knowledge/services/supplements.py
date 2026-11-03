"""Eligible supplements derived from currently authorized source rows."""
from app.knowledge.schemas import Conflict, KnowledgeError, Missing, digest
from app.knowledge.services.source_validation import applicable, validate_sources
from app.knowledge.context import BASE_ONLY


async def supplement_candidates(tx, release_id, on, order_date=None):
    if release_id == BASE_ONLY:
        return []
    if release_id is None:
        release_id = (await tx.get('active', 'current') or {}).get('release_id')
    if not release_id or release_id == BASE_ONLY:
        return []
    release = await tx.get('releases', release_id)
    if not release:
        raise Missing('Pinned knowledge release unavailable')
    if release.get('status') != 'ready' or digest(release['manifest']) != release['manifest_hash']:
        raise Conflict('Knowledge generation invalid')
    result = []
    for item in release['manifest']['items']:
        try:
            metadata = await validate_sources(tx, item['sources'])
        except KnowledgeError:
            continue
        if not applicable(metadata, on, order_date):
            continue
        sources = await tx.sources(item['source_ids'])
        if item['kind'] == 'aliases':
            for source in sources:
                result.append(dict(source, title=source['title']+' '+item['question']+' '+' '.join(item['aliases']),
                                   knowledge_revision_id=item['id'], source_chunk_ids=item['source_ids']))
        else:
            result.append({'chunk_id': 'KG-'+item['id'], 'document_id': 'knowledge:'+release_id,
                'title': item['question'], 'body': ((('Phạm vi áp dụng: '+item['scope']+'\n') if item.get('scope') else '')+item['answer']), 'source_hash': item['content_hash'],
                'source_chunk_ids': item['source_ids'], 'knowledge_revision_id': item['id'], **metadata})
    return result
