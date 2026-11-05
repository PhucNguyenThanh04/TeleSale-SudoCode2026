"""Build immutable hybrid generations outside the approval/CAS transaction."""
from app.knowledge.config import qdrant_url
import time
from app.knowledge.services.permissions import require_permission
from app.knowledge.schemas import Conflict, KnowledgeError, digest, timestamp
from app.knowledge.schemas import SourceChunk, HybridVector
from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder, document_text
from app.knowledge.policy.source import parse_policy_sources, content_hash
from app.knowledge.services.source_validation import validate_sources


async def _approved(tx, revision_ids):
    items=[]
    if len(revision_ids)>100 or len(set(revision_ids)) != len(revision_ids):
        raise KnowledgeError('Distinct revision IDs required')
    for rid in revision_ids:
        revision=await tx.get('revisions',rid)
        case=await tx.get('regression_cases',rid)
        if not revision or revision.get('status')!='approved' or not case or not case.get('approved'):
            raise KnowledgeError('Approved revision and test required')
        if revision.get('test_hash')!=digest(case):
            raise Conflict('Reviewed test changed')
        await validate_sources(tx,revision['sources'])
        items.append(revision)
    return items


def _supplement(chunks, items):
    rows={c.chunk_id:c for c in chunks}
    for item in items:
        refs=item['sources']
        sources=[rows.get(ref['chunk_id']) for ref in refs]
        if not sources or any(s is None for s in sources):
            raise KnowledgeError('Supplement serving source unavailable')
        if any(ref['source_hash'] != source.source_hash for ref, source in zip(refs, sources, strict=True)):
            raise Conflict('Supplement source hash differs from source file')
        if item['kind']=='aliases':
            for source in sources:
                rows[source.chunk_id]=source.model_copy(update={
                    'search_aliases':sorted(set(source.search_aliases+item.get('aliases',[])))})
            continue
        body=item['answer']
        source_ids=[s.chunk_id for s in sources]
        basis={s.date_basis for s in sources}
        if len(basis)!=1:
            raise KnowledgeError('Incompatible supplement dates')
        starts=[s.effective_from for s in sources if s.effective_from]
        ends=[s.effective_until for s in sources if s.effective_until]
        if starts and ends and max(starts)>min(ends):
            raise KnowledgeError('Empty supplement validity interval')
        key='KG-'+item['id']
        rows[key]=SourceChunk(chunk_id=key,section_id=key,document_id='approved-faq',
            content=body,source={'file':'approved-faq','revision':item['id'],'source_ids':source_ids},
            source_hash=digest(refs),content_hash=content_hash(body),date_basis=next(iter(basis)),
            effective_from=max(starts) if starts else None,effective_until=min(ends) if ends else None,
            required_context=sorted({key for s in sources for key in s.required_context}),
            required_links=source_ids,source_references=refs,supplement=True,
            search_aliases=[item['question']])
    return list(rows.values())


def _check_policy_sources(source_dir,metadata,items,snapshot_hash):
    current=[c.model_dump(mode='json') for c in _supplement(parse_policy_sources(source_dir,metadata),items)]
    if digest(sorted(current,key=lambda row:row['chunk_id']))!=snapshot_hash:
        raise Conflict('Policy source changed during build')


async def build_policy_release(repo, encoder, index, *, source_dir, metadata, revision_ids,
                               expected_active_id, actor_id):
    async with repo.transaction() as tx:
        await require_permission(tx,actor_id)
        if (await tx.get('active','current') or {}).get('release_id')!=expected_active_id:
            raise Conflict('Active release changed')
        items=await _approved(tx,revision_ids)
    config=encoder.config
    chunks=sorted(_supplement(parse_policy_sources(source_dir,metadata),items), key=lambda c:c.chunk_id)
    snapshot=[c.model_dump(mode='json') for c in chunks]
    release_id='policy-'+digest({'chunks':snapshot,'config':config.model_dump(mode='json'),
        'items':items,'base':expected_active_id})[:32]
    manifest={'index_kind':'hybrid','schema_version':3,'pipeline':'cloudflare_dense_bm25',
        'bm25':build_bm25_artifact([document_text(c) for c in chunks],config),'shards':1,'collection':release_id.replace('-','_'),
        'model_fingerprint':config.fingerprint(),'config':config.model_dump(mode='json'),
        'config_hash':digest(config.model_dump(mode='json')),'metadata_hash':digest(metadata),
        'source_hashes':{c.chunk_id:c.source_hash for c in chunks},
        'content_hashes':{c.chunk_id:c.content_hash for c in chunks},
        'snapshot_hash':digest(sorted(snapshot,key=lambda row:row['chunk_id'])),'items':[{key:item[key] for key in ('id','gap_id','kind','sources','content_hash','test_hash')} for item in items],'checks':{'index_complete':False}}
    release={'id':release_id,'manifest':manifest,'manifest_hash':digest(manifest),'status':'building',
        'base_release_id':expected_active_id,'prepared_by':actor_id,'created_at':timestamp()}
    cached = None
    async with repo.transaction() as tx:
        previous=await tx.get('releases',release_id)
        if previous and previous.get('status') in {'erased','revoked'}:
            raise Conflict('Release revoked')
        if previous and previous.get('status')=='ready':
            if previous['manifest'].get('snapshot_hash')!=manifest['snapshot_hash']:
                raise Conflict('Immutable release mismatch')
            cached = previous
        else:
            await tx.put('releases',release_id,release)
            for chunk in snapshot:
                if await tx.get('policy_revocations',chunk['chunk_id']):
                    raise Conflict('Source revoked')
                await tx.put('policy_sources',release_id+':'+chunk['chunk_id'],
                    {'id':release_id+':'+chunk['chunk_id'],'release_id':release_id,'chunk':chunk})
    if cached:
        await index.verify(cached,config,chunks=chunks)
        _check_policy_sources(source_dir,metadata,items,manifest['snapshot_hash'])
        async with repo.transaction() as tx:
            await require_permission(tx,actor_id)
            if ((await tx.get('active','current') or {}).get('release_id')!=expected_active_id
                    or await tx.get('releases',release_id)!=cached):
                raise Conflict('Release changed during verification')
            if await _approved(tx,revision_ids)!=items:
                raise Conflict('Approval changed during verification')
            for chunk in chunks:
                if await tx.get('policy_revocations',chunk.chunk_id):
                    raise Conflict('Source revoked')
        return cached
    if not encoder.ready:
        await encoder.start()
    lexical=BM25Encoder(manifest['bm25'])
    for chunk in chunks:
        text=document_text(chunk)
        dense=await encoder.encode(text,deadline=time.monotonic()+config.deadline_seconds)
        indices,weights=lexical.encode_document(text)
        vector=HybridVector(dense=dense,sparse_indices=indices,sparse_values=weights)
        await index.upsert(release,[chunk],[vector],config=config)
    await index.verify(release,config,chunks=chunks)
    _check_policy_sources(source_dir,metadata,items,manifest['snapshot_hash'])
    async with repo.transaction() as tx:
        await require_permission(tx,actor_id)
        if (await tx.get('active','current') or {}).get('release_id')!=expected_active_id:
            raise Conflict('Active release changed during build')
        if await _approved(tx,revision_ids)!=items:
            raise Conflict('Approval changed during build')
        current=await tx.get('releases',release_id)
        if not current or current.get('status') in {'erased','revoked'}:
            raise Conflict('Release revoked during build')
        for chunk in chunks:
            if await tx.get('policy_revocations',chunk.chunk_id):
                raise Conflict('Source revoked during build')
        manifest['checks']={'index_complete':True,'relevance_verified':config.relevance_verified}
        release.update(manifest_hash=digest(manifest),status='ready')
        await tx.put('releases',release_id,release)
        await tx.put('audit','build-'+release_id,{'id':'build-'+release_id,'action':'prepare_hybrid',
            'release_id':release_id,'actor_id':actor_id,'at':timestamp()})
    return release


async def validate_hybrid_release(tx,release):
    manifest=release['manifest']
    if manifest.get('index_kind')!='hybrid' or not manifest.get('checks',{}).get('index_complete'):
        raise Conflict('Hybrid index not ready')
    if manifest.get('schema_version') != 3 or manifest.get('pipeline') != 'cloudflare_dense_bm25':
        raise Conflict('Release requires Cloudflare dense/BM25 rebuild')
    BM25Encoder(manifest['bm25'])
    snapshot = []
    for key,source_hash in manifest['source_hashes'].items():
        if await tx.get('policy_revocations',key):
            raise Conflict('Source revoked')
        row=await tx.get('policy_sources',release['id']+':'+key)
        if not row or row['chunk']['source_hash']!=source_hash:
            raise Conflict('Serving snapshot missing or changed')
        snapshot.append(row['chunk'])
    if digest(sorted(snapshot,key=lambda row:row['chunk_id'])) != manifest.get('snapshot_hash'):
        raise Conflict('Serving snapshot metadata changed')


async def build_configured_policy_release(repo, revision_ids, expected_active_id, actor_id, *,
                                           source_dir=None, metadata_path=None, config_path=None):
    """Explicit administrative build; called only by a reviewer prepare operation."""
    import json
    from pathlib import Path
    from qdrant_client import AsyncQdrantClient
    from app.configs import get_settings
    from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig
    from app.knowledge.policy.source import default_metadata
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    settings=get_settings()
    source_dir=source_dir or settings.knowledge_policy_source_dir
    config_path=config_path or settings.knowledge_policy_config_file
    if not source_dir or not config_path:
        raise KnowledgeError('Policy source directory and runtime config required')
    async with repo.transaction() as tx:
        await require_permission(tx,actor_id)
    config=PolicyRuntimeConfig.model_validate(json.loads(Path(config_path).read_text(encoding='utf-8')))
    metadata=json.loads(Path(metadata_path).read_text(encoding='utf-8')) if metadata_path else default_metadata()
    encoder=PolicyEncoder(config)
    client=AsyncQdrantClient(url=qdrant_url(),timeout=config.dependency_timeout_seconds)
    try:
        return await build_policy_release(repo,encoder,HybridPolicyIndex(client),source_dir=Path(source_dir),
            metadata=metadata,revision_ids=revision_ids,expected_active_id=expected_active_id,actor_id=actor_id)
    finally:
        await encoder.close()
        await client.close()
