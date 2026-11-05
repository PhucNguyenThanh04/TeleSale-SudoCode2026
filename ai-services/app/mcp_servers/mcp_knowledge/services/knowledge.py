"""Hybrid policy evidence service. No fallback and no answer generation."""
import asyncio
import logging
import time
from app.knowledge.schemas import digest
from app.mcp_servers.mcp_knowledge.services.embedding import PolicyOverloaded, PolicyInputError
from app.knowledge.policy.rules import apply_policy_rules
from app.mcp_servers.mcp_knowledge.services.dependencies import PolicyDependencies
from app.knowledge.schemas import EvidenceSet, HybridVector
from app.mcp_servers.mcp_knowledge.services.bm25 import BM25Encoder
from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_knowledge.schemas import PolicySearchResult

LOGGER=logging.getLogger('app.mcp.knowledge')


class PolicySearchService:
    def __init__(self,repo,encoder,index,config,*,clock=time.monotonic):
        self.repo,self.encoder,self.index,self.config=repo,encoder,index,config
        self.clock=clock
        self.dependencies=PolicyDependencies(config,clock=clock)
        self.ready=False

    def _validate_release(self,release):
        manifest=release['manifest']
        if (release.get('status')!='ready' or manifest.get('index_kind')!='hybrid'
                or digest(manifest)!=release.get('manifest_hash')
                or manifest.get('model_fingerprint')!=self.config.fingerprint()
                or manifest.get('config_hash')!=digest(self.config.model_dump(mode='json'))
                or not manifest.get('checks',{}).get('index_complete')
                or manifest.get('schema_version') != 3
                or manifest.get('pipeline') != 'cloudflare_dense_bm25'):
            raise ValueError('Release incompatible or incomplete')
        BM25Encoder(manifest['bm25'])

    async def start(self):
        try:
            await self.encoder.start()
            release=await self.repo.resolve_release()
            self._validate_release(release)
            chunks=await self.repo.snapshot(release)
            await self.index.verify(release,self.config,chunks=chunks)
        except BaseException:
            await self.encoder.close()
            raise
        self.ready=True

    async def close(self):
        self.ready = False
        await self.encoder.close()
        if hasattr(self.index, 'client'):
            await self.index.client.close()
        if hasattr(self.repo, 'engine'):
            await self.repo.close()

    async def release_ref(self, release_id=None):
        """Return an authenticated, revalidated reference for harness pinning."""
        if not self.ready:
            raise RuntimeError("Knowledge service is not ready")
        release = await self.repo.resolve_release(release_id)
        self._validate_release(release)
        chunks = await self.repo.snapshot(release)
        await self.index.verify(release, self.config, chunks=chunks)
        return {'release_id': release['id'], 'manifest_hash': release['manifest_hash']}

    async def search(self,request,context):
        if request.on!=context.on or (request.order_date and request.order_date!=context.verified_order_date):
            raise ValueError('Request business dates are not trusted')
        output_context={'on':context.on.isoformat(),
            'order_date':context.verified_order_date.isoformat() if context.verified_order_date else None,
            'customer_reported_order_date':request.customer_reported_order_date.isoformat() if request.customer_reported_order_date else None,
            'knowledge_release_id':context.release_id}
        if not self.ready:
            return PolicySearchResult(retrieval_status='unavailable',context=output_context,error='knowledge_unavailable')
        start=self.clock()
        deadline=start+self.config.deadline_seconds
        phase='manifest'
        try:
            async with asyncio.timeout(self.config.deadline_seconds):
                call=self.dependencies.call_dependency
                release=await call('postgres',lambda:self.repo.resolve_release(context.release_id),deadline=deadline)
                output_context['knowledge_release_id']=release['id']
                self._validate_release(release)
                phase='encode'
                dense=await self.encoder.encode(request.query,deadline=deadline)
                lexical=BM25Encoder(release['manifest']['bm25'])
                indices,weights=lexical.encode_query(mask_pii(request.query))
                vector=HybridVector(dense=dense,sparse_indices=indices,sparse_values=weights)
                phase='qdrant'
                hits=await call('qdrant',lambda:self.index.query(vector,release=release,access_filter='public',
                    config=self.config,include_supplements=context.include_supplements),deadline=deadline)
                phase='source'
                chunks=await call('postgres',lambda:self.repo.snapshot(release),deadline=deadline)
                allowed={c.chunk_id:c for c in chunks if context.include_supplements or not c.supplement}
                applicable={e.chunk_id:e for e in apply_policy_rules(list(allowed.values()),request,context)}
                selected={}
                for hit in hits:
                    if hit.chunk_id not in allowed:
                        raise ValueError('Unauthorized index hit')
                    chunk=allowed[hit.chunk_id]
                    if chunk.source_hash!=hit.source_hash or chunk.content_hash!=hit.content_hash:
                        raise ValueError('Index/source hash mismatch')
                phase='selection'
                for hit in hits:
                    if len(selected)>=request.top_k:
                        break
                    key=hit.chunk_id
                    if key not in applicable or key in selected:
                        continue
                    selected[key]=applicable[key]
                    for related in allowed[key].required_links:
                        if related in applicable and related not in selected and len(selected)<self.config.hard_limit:
                            selected[related]=applicable[related].model_copy(update={'retrieved_via':'linked'})
                missing_all=set()
                for key,evidence in selected.items():
                    missing=sorted(set(allowed[key].required_links)-selected.keys())
                    if missing:
                        if evidence.applicability.status != 'conflict':
                            evidence.applicability.status='conditional'
                        evidence.applicability.missing_required_section_ids=missing
                        missing_all.update(missing)
                # Recheck revocation after vector and selection work, including pinned releases.
                await call('postgres',lambda:self.repo.snapshot(release),deadline=deadline)
                result=PolicySearchResult(retrieval_status='ok' if selected else 'no_evidence',
                    context=output_context,evidence=list(selected.values()),evidence_set=EvidenceSet(
                        required_dependencies_complete=not missing_all,missing_required_section_ids=sorted(missing_all)))
                phase='serialization'
                result.model_dump_json()
                if self.clock()>=deadline:
                    raise TimeoutError('Serialization deadline')
                return result
        except PolicyProviderError as exc:
            LOGGER.warning('knowledge failure component=cloudflare provider=cloudflare model=%s reason=%s http_status=%s provider_code=%s request_id=%s release_id=%s',
                self.config.model_name,exc.reason,exc.status,exc.provider_code,context.request_id,output_context.get('knowledge_release_id'))
            return PolicySearchResult(retrieval_status='unavailable',context=output_context,error='knowledge_unavailable')
        except PolicyInputError:
            raise
        except PolicyOverloaded:
            return PolicySearchResult(retrieval_status='overloaded',context=output_context,error='knowledge_overloaded')
        except TimeoutError:
            return PolicySearchResult(retrieval_status='timeout',context=output_context,error='knowledge_timeout')
        except Exception as exc:
            LOGGER.warning('knowledge failure component=%s reason=%s request_id=%s release_id=%s',
                phase,type(exc).__name__,context.request_id,output_context.get('knowledge_release_id'))
            return PolicySearchResult(retrieval_status='unavailable',context=output_context,error='knowledge_unavailable')
        finally:
            LOGGER.info('knowledge request request_id=%s release_id=%s phase=%s elapsed_ms=%.2f',
                context.request_id,output_context.get('knowledge_release_id'),phase,(self.clock()-start)*1000)
