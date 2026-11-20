from datetime import date, datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from .knowledge import _enable_ai_imports, policy_sources
from .postgres import _asyncpg_url
from .source import read_release, json_digest, source_fingerprint

KEYS = {'products':('sku',), 'variants':('variant_sku',), 'promotions':('promo_code',),
    'inventory_events':('sku','effective_on'), 'customers':('customer_id',),
    'crm_orders':('order_id',), 'crm_sessions':('session_id',),
    'policy_documents':('document_id',), 'policy_chunks':('chunk_id',)}
JSON_COLUMNS = {'data','attributes','applies_to','conditions'}


def _obj(value):
    return json.loads(value) if isinstance(value,str) else value


def _key(table,row):
    return '|'.join(str(row[k]) for k in KEYS[table])


def _expected_source_rows(release):
    tables = {name:{} for name in KEYS}
    def put(table,row):
        key = _key(table,row)
        if key in tables[table]:
            raise ValueError('Duplicate source key: '+table)
        tables[table][key]=row
    def record(item, **columns):
        return dict(columns,data=item,source_hash=json_digest(item))
    for p in release['products']['products']:
        put('products',record(p,**{k:p[k] for k in ['sku','name','category','brand','list_price_vnd','stock','attributes']}))
        for v in p.get('variants',[]):
            put('variants',record(v,variant_sku=v['variant_sku'],parent_sku=p['sku'],
                size_label=str(v['size']) if v.get('size') is not None else None,color=v.get('color'),
                price_delta_vnd=v['price_delta_vnd'],stock=v['stock']))
    for p in release['promotions']['promotions']:
        put('promotions',record(p,promo_code=p['promo_code'],name=p['name'],promo_type=p['type'],
            starts_on=p['start'],ends_on=p['end'],applies_to=p['applies_to'],conditions=p.get('conditions',{})))
    for e in release['inventory']['events']:
        put('inventory_events',record(e,sku=e['sku'],effective_on=e['date'],qty=e['qty'],note=e.get('note')))
    for c in release['crm']['customers']:
        put('customers',record(c,**{k:c.get(k) for k in ['customer_id','name','honorific','phone','zalo_id','fb_id','region','shared_phone_with']}))
        for o in c.get('orders',[]):
            put('crm_orders',record(o,order_id=o['order_id'],customer_id=c['customer_id'],
                sku=o['sku'],order_date=o.get('date'),status=o['status']))
        for s in c.get('sessions',[]):
            put('crm_sessions',record(s,session_id=s['session_id'],customer_id=c['customer_id'],
                session_date=s['date'],channel=s['channel'],outcome=s.get('outcome')))
    for c in release['chunks']:
        common=dict(document_id=c.document_id,access_level=c.access_level,
            effective_from=c.effective_from,effective_until=c.effective_until,date_basis=c.date_basis)
        tables['policy_documents'][c.document_id]=common
        put('policy_chunks',dict(common,chunk_id=c.chunk_id,title=c.title,body=c.body,source_hash=c.content_hash))
    return tables


def _normal_row(row):
    return {k:(_obj(v) if k in JSON_COLUMNS else v.isoformat() if isinstance(v,(date,datetime)) else v)
            for k,v in dict(row).items()}


def _fields(expected,actual,prefix=''):
    if isinstance(expected,dict) and isinstance(actual,dict):
        result=[]
        for key in sorted(set(expected)|set(actual)):
            path=prefix+'.'+key if prefix else key
            if key not in expected or key not in actual:result.append(path)
            else:result.extend(_fields(expected[key],actual[key],path))
        return result
    return [] if json_digest(expected)==json_digest(actual) else [prefix]


def _comparison(expected,actual):
    missing=sorted(set(expected)-set(actual));extra=sorted(set(actual)-set(expected))
    changed=[{'id':key,'fields':fields} for key in sorted(set(expected)&set(actual))
             if (fields:=_fields(expected[key],actual[key]))]
    return dict(expected=len(expected),actual=len(actual),missing=missing,extra=extra,changed=changed)


def _matches(comparison):
    return not any(comparison[k] for k in ['missing','extra','changed'])


async def _identity(conn):
    return dict(await conn.fetchrow('SELECT current_database() AS database, '
        'extract(epoch from pg_postmaster_start_time())::text AS server_epoch, '
        'inet_server_addr()::text AS server_address, inet_server_port() AS server_port'))


async def verify_ingestion(database_url, source_dir, *, knowledge_database_url,
                           qdrant_url, release_id, runtime_config_path, metadata_path=None):
    _enable_ai_imports()
    import asyncpg
    from qdrant_client import AsyncQdrantClient
    from app.knowledge.schemas import SourceChunk,digest
    from app.knowledge.policy.source import default_metadata
    from app.knowledge.services.publish import _supplement
    from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex,point_id
    report=dict(ingestion_status='failed',release_id=release_id,release_status=None,
        relevance_verified=False,serving_ready=False,checked_at=datetime.now(timezone.utc).isoformat(),
        targets={},counts={},checks={},issues=[])
    stage='source'
    try:
        if not knowledge_database_url:
            raise ValueError('Knowledge database required')
        root=Path(source_dir);meta_path=Path(metadata_path) if metadata_path else None
        source=read_release(root,meta_path)
        expected_tables=_expected_source_rows(source)
        metadata=json.loads(meta_path.read_text()) if meta_path else default_metadata()
        config=PolicyRuntimeConfig.model_validate_json(Path(runtime_config_path).read_text())
        report['relevance_verified']=False
        conn=await asyncpg.connect(_asyncpg_url(database_url),timeout=config.dependency_timeout_seconds)
        try:
            async with conn.transaction(readonly=True):
                source_identity=await _identity(conn)
                report['targets']['source_database']=source_identity
                comparisons={}
                for table,expected in expected_tables.items():
                    records=await conn.fetch(f'SELECT * FROM btc_source.{table}')
                    actual={_key(table,r):_normal_row(r) for r in records}
                    comparisons[table]=_comparison(expected,actual)
                report['counts']['source_tables']=comparisons
                report['checks']['source']=all(_matches(c) for c in comparisons.values())
                if not report['checks']['source']:
                    report['issues'].append({'stage':stage,'code':'source_rows_mismatch'})
        finally:await conn.close()
        stage='knowledge'
        conn=await asyncpg.connect(_asyncpg_url(knowledge_database_url),timeout=config.dependency_timeout_seconds)
        try:
            async with conn.transaction(readonly=True):
                knowledge_identity=await _identity(conn)
                report['targets']['knowledge_database']=knowledge_identity
                report['checks']['database_identity']=all(source_identity[k]==knowledge_identity[k] for k in ['database','server_epoch'])
                if not report['checks']['database_identity']:
                    raise ValueError('Database identity mismatch')
                release=_obj(await conn.fetchval('SELECT data FROM knowledge.releases WHERE id=$1',release_id))
                if not release or release.get('id')!=release_id or release.get('status') not in {'ready','prepared'}:
                    raise ValueError('Release not available for verification')
                report['release_status']=release['status']
                manifest=release['manifest']
                manifest_checks={
                    'manifest_hash':digest(manifest)==release.get('manifest_hash'),
                    'config_hash':digest(config.model_dump(mode='json'))==manifest.get('config_hash'),
                    'metadata_hash':digest(metadata)==manifest.get('metadata_hash'),
                    'index_complete':manifest.get('checks',{}).get('index_complete') is True,
                    'index_kind':manifest.get('index_kind')=='hybrid',
                    'pipeline':manifest.get('schema_version')==3 and manifest.get('pipeline')=='cloudflare_dense_bm25'}
                report['checks']['manifest']=all(manifest_checks.values())
                for key,valid in manifest_checks.items():
                    if not valid:report['issues'].append({'stage':stage,'code':key+'_mismatch'})
                records=await conn.fetch("SELECT data FROM knowledge.policy_sources WHERE data->>'release_id'=$1",release_id)
                snapshot=[_obj(r['data'])['chunk'] for r in records]
                report['checks']['snapshot_integrity']=digest(sorted(snapshot,key=lambda c:c['chunk_id']))==manifest.get('snapshot_hash')
                if not report['checks']['snapshot_integrity']:
                    report['issues'].append({'stage':stage,'code':'snapshot_hash_mismatch'})
                revisions=[]
                for item in manifest.get('items',[]):
                    revision=_obj(await conn.fetchval('SELECT data FROM knowledge.revisions WHERE id=$1',item['id']))
                    if not revision or revision.get('status')!='approved':
                        raise ValueError('Approved supplement unavailable')
                    revisions.append(revision)
                expected_chunks=_supplement(policy_sources(root/'policy',meta_path),revisions)
                comparison=_comparison({c.chunk_id:c.model_dump(mode='json') for c in expected_chunks},
                    {c['chunk_id']:c for c in snapshot})
                report['counts']['snapshots']=comparison
                report['checks']['snapshot_source']=_matches(comparison)
                if not report['checks']['snapshot_source']:
                    report['issues'].append({'stage':stage,'code':'snapshot_source_mismatch'})
                revoked={r['id'] for r in await conn.fetch('SELECT id FROM knowledge.policy_revocations')}
                affected=sorted(revoked & {c['chunk_id'] for c in snapshot})
                report['checks']['revocations']=not affected
                if affected:report['issues'].append({'stage':stage,'code':'source_revoked','ids':affected})
                active=_obj(await conn.fetchval("SELECT data FROM knowledge.active WHERE id=$1",'current')) or {}
        finally:await conn.close()
        stage='index'
        target=urlsplit(qdrant_url)
        report['targets']['qdrant']={'scheme':target.scheme,'host':target.hostname,'port':target.port}
        report['collection']=manifest['collection']
        client=AsyncQdrantClient(url=qdrant_url,timeout=config.dependency_timeout_seconds)
        try:
            count=(await client.count(manifest['collection'],exact=True)).count
            report['counts']['qdrant']={'expected':len(expected_chunks),'actual':count}
            stored=[SourceChunk.model_validate(c) for c in snapshot]
            await HybridPolicyIndex(client).verify(release,config,chunks=stored)
            report['checks']['index']=True
            report['expiry']={'field_present_count':count,
                'dated_chunks':[{'chunk_id':c.chunk_id,'point_id':point_id(release_id,c.chunk_id),
                    'date_basis':c.date_basis,'effective_until':str(c.effective_until)} for c in stored if c.effective_until]}
        finally:await client.close()
        report['relevance_verified']=bool(release['manifest'].get('checks',{}).get('relevance_verified'))
        report['checks']['source_stable']=source['source_fingerprint']==source_fingerprint(root,meta_path)
        if not report['checks']['source_stable']:
            report['issues'].append({'stage':'source','code':'source_changed_during_verification'})
        report['ingestion_status']='passed' if all(report['checks'].values()) and not report['issues'] else 'failed'
        report['serving_ready']=(report['ingestion_status']=='passed' and release['status']=='ready'
            and release['manifest'].get('pipeline')=='cloudflare_dense_bm25'
            and active.get('release_id')==release_id)
    except Exception as exc:
        report['checks'][stage]=False
        issue={'stage':stage,'code':'verification_error','error_type':type(exc).__name__}
        if isinstance(exc,ValueError) and str(exc).startswith('Payload mismatch: '):
            issue['field']=str(exc).removeprefix('Payload mismatch: ')
        report['issues'].append(issue)
    return report
