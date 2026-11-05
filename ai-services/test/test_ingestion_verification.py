"""Read-only ingestion verification; all state here is synthetic and in memory."""
import asyncio
import copy
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


async def setup_verification(tmp_path, monkeypatch, fault=None):
    from dataloader_offline.source import read_release
    from dataloader_offline.knowledge import policy_sources
    from dataloader_offline.verification import _expected_source_rows
    from test_dataloader_postgres import synthetic_release
    from test_policy_embedding import runtime_config
    from app.knowledge.schemas import digest, HybridVector
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex,point_id
    root=tmp_path/'btc';(root/'catalog').mkdir(parents=True);(root/'policy').mkdir()
    raw=synthetic_release()
    for key,name in [('products','products.json'),('promotions','promotions.json'),('inventory','inventory_timeline.json'),('crm','crm_seed.json')]:
        if key!='crm':raw[key]['reference_date']='2026-10-15'
        (root/'catalog'/name).write_text(json.dumps(raw[key]))
    (root/'policy/source.md').write_text('# Synthetic\n\n## [XX-01] Rule\nSafe content')
    metadata={'documents':{'source.md':dict(access='public',version='v1',date_basis='on',effective_from=None,effective_until=None)}}
    meta=tmp_path/'metadata.json';meta.write_text(json.dumps(metadata))
    source=read_release(root,meta);tables=copy.deepcopy(_expected_source_rows(source))
    config=runtime_config(tokenizer_revision='a'*40,relevance_verified=False)
    cfg=tmp_path/'runtime.json';cfg.write_text(config.model_dump_json())
    chunks=policy_sources(root/'policy',meta);snapshot=[c.model_dump(mode='json') for c in chunks]
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder, document_text
    artifact=build_bm25_artifact([document_text(c) for c in chunks],config)
    lexical=BM25Encoder(artifact)
    indices,weights=lexical.encode_document(document_text(chunks[0]))
    manifest=dict(schema_version=3,pipeline='cloudflare_dense_bm25',bm25=artifact,collection='verify_test',index_kind='hybrid',model_fingerprint=config.fingerprint(),
        config_hash=digest(config.model_dump(mode='json')),metadata_hash=digest(metadata),
        source_hashes={c.chunk_id:c.source_hash for c in chunks},content_hashes={c.chunk_id:c.content_hash for c in chunks},
        snapshot_hash=digest(sorted(snapshot,key=lambda c:c['chunk_id'])),items=[],checks={'index_complete':True,'relevance_verified':False})
    release=dict(id='release',status='ready' if fault=='active' else 'prepared',manifest=manifest,manifest_hash=digest(manifest))
    client=AsyncQdrantClient(':memory:')
    await HybridPolicyIndex(client).upsert(release,chunks,[HybridVector(dense=[1,0],sparse_indices=indices,sparse_values=weights)],config=config)
    if fault=='json':tables['products']['P1']['data']['extra']='tampered private marker'
    if fault=='scalar':tables['products']['P1']['stock']=999
    if fault=='extra':tables['products']['extra']=dict(tables['products']['P1'],sku='extra')
    if fault=='missing':tables['products'].clear()
    if fault=='expiry':await client.delete_payload('verify_test',['effective_until'],[point_id('release','XX-01')])
    if fault=='expiry_value':await client.set_payload('verify_test',{'effective_until':'2099-12-31'},[point_id('release','XX-01')])
    if fault=='snapshot':snapshot[0]['effective_until']='2099-12-31'
    if fault=='metadata':metadata['documents']['source.md']['version']='v2';meta.write_text(json.dumps(metadata))
    # Verifier must never mutate the seeded collection or instantiate an encoder.
    for method in ['upsert','create_collection','set_payload','overwrite_payload','delete_collection']:
        monkeypatch.setattr(client,method,AsyncMock(side_effect=AssertionError('read only')))
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    monkeypatch.setattr(PolicyEncoder,'start',AsyncMock(side_effect=AssertionError('no model')))
    queries=[]
    class Conn:
        def __init__(self,knowledge):self.knowledge=knowledge
        @asynccontextmanager
        async def transaction(self,**kwargs):
            assert kwargs == {'readonly':True}
            yield
        async def fetchrow(self,sql,*args):
            queries.append(sql);assert sql.startswith('SELECT')
            return dict(database='other' if fault=='database' and self.knowledge else 'synthetic',server_epoch='1',server_address='127.0.0.1',server_port=5432)
        async def fetch(self,sql,*args):
            queries.append(sql);assert sql.startswith('SELECT')
            if 'btc_source.' in sql:return list(tables[sql.split('btc_source.')[1].split()[0]].values())
            if 'policy_sources' in sql:return [{'data':{'id':'release:'+c['chunk_id'],'release_id':'release','chunk':c}} for c in snapshot]
            if 'policy_revocations' in sql:return []
            raise AssertionError(sql)
        async def fetchval(self,sql,*args):
            queries.append(sql);assert sql.startswith('SELECT')
            if 'knowledge.releases' in sql:return release if args[0]=='release' else None
            if 'knowledge.active' in sql:return {'release_id':'release'} if fault=='active' else None
            raise AssertionError(sql)
        async def close(self):pass
    async def connect(dsn,**kwargs):
        if fault=='connection':raise ConnectionError('do not print credentials')
        return Conn(dsn.endswith('knowledge'))
    monkeypatch.setattr('asyncpg.connect',connect)
    monkeypatch.setattr('qdrant_client.AsyncQdrantClient',lambda **kwargs:client)
    return dict(database_url='postgresql://synthetic/source',source_dir=root,
        knowledge_database_url='postgresql://synthetic/knowledge',qdrant_url='http://memory:6333',
        release_id='other' if fault=='release' else 'release',runtime_config_path=cfg,metadata_path=meta)


def test_read_only_verification_reports_integrity_separately_from_readiness(tmp_path,monkeypatch):
    from dataloader_offline.verification import verify_ingestion
    async def run():
        args=await setup_verification(tmp_path,monkeypatch)
        report=await verify_ingestion(**args)
        assert report['ingestion_status']=='passed',report
        assert report['release_status']=='prepared'
        assert report['relevance_verified'] is False and report['serving_ready'] is False
        assert report['counts']['snapshots']['actual']==1
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['json','scalar','extra','missing','expiry','expiry_value','snapshot','metadata','database','connection','release'])
def test_verification_detects_wrong_content_missing_metadata_and_wrong_target(tmp_path,monkeypatch,fault):
    from dataloader_offline.verification import verify_ingestion
    async def run():
        args=await setup_verification(tmp_path,monkeypatch,fault)
        report=await verify_ingestion(**args)
        assert report['ingestion_status']=='failed'
        assert report['issues']
        assert 'tampered private marker' not in json.dumps(report)
        assert 'Synthetic buyer' not in json.dumps(report)
    asyncio.run(run())


def test_active_integrity_ready_is_serving_ready_without_eval(tmp_path,monkeypatch):
    from dataloader_offline.verification import verify_ingestion
    async def run():
        args=await setup_verification(tmp_path,monkeypatch,'active')
        report=await verify_ingestion(**args)
        assert report['ingestion_status']=='passed',report
        assert report['serving_ready'] is True
        assert report['relevance_verified'] is False
    asyncio.run(run())
