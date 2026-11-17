"""Offline K0 -> K1 -> K0 rehearsal using real lifecycle, hybrid index and MCP."""
import argparse
import asyncio
from contextlib import asynccontextmanager, ExitStack
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import patch

from app.knowledge.schemas import Conflict, Forbidden, KnowledgeError, digest
from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository


class _MemoryRepository(PolicyRepository):
    """Rehearsal-only storage; inherited snapshot reads validate real manifests."""
    def __init__(self, sources):
        self.tables = {}
        self.source_rows = sources
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            before = deepcopy(self.tables)
            try:
                yield self
            except BaseException:
                self.tables = before
                raise

    async def get(self, table, key):
        return deepcopy(self.tables.get(table, {}).get(key))

    async def put(self, table, key, value):
        self.tables.setdefault(table, {})[key] = deepcopy(value)

    async def rows(self, table):
        return deepcopy(list(self.tables.get(table, {}).values()))

    async def sources(self, ids=None):
        return deepcopy([row for row in self.source_rows if ids is None or row['chunk_id'] in ids])


class _FixtureDenseBackend:
    def token_count(self, text):
        return len(text.split()) + 2

    async def encode(self, text, *, deadline):
        return [1., 0.]

    async def close(self):
        pass


def _deny_network(*args, **kwargs):
    raise RuntimeError('Offline rehearsal forbids network connections')


def _check(checks, name, condition):
    checks[name] = bool(condition)
    if not checks[name]:
        raise ValueError('Rollback rehearsal check failed: ' + name)


async def rehearse(btc_root: Path) -> dict:
    from fastmcp import Client
    from qdrant_client import AsyncQdrantClient
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    from app.knowledge.services.lifecycle import command
    from app.knowledge.services.publish import build_policy_release
    from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
    from app.mcp_servers.mcp_knowledge.services.embedding import PolicyEncoder
    from app.mcp_servers.mcp_knowledge.services.knowledge import PolicySearchService
    from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig, PolicySearchInput, TrustedPolicyContext
    from app.mcp_servers.mcp_knowledge.tools.handlers import create_server
    from app.mcp_servers.mcp_knowledge.tools.auth import sign_policy_context

    source_dir, metadata = Path(btc_root)/'policy', default_metadata()
    chunks = parse_policy_sources(source_dir, metadata)
    source = next((c for c in chunks if c.chunk_id == 'DT-02'), None)
    if source is None:
        raise ValueError('DT-02 public policy fixture required')
    source_digest = digest([c.model_dump(mode='json') for c in chunks])
    sources = [{'chunk_id': c.chunk_id, 'source_hash': c.source_hash,
        'access_level': c.access_level, 'date_basis': 'call_date' if c.date_basis == 'on' else c.date_basis,
        'effective_from': c.effective_from.isoformat() if c.effective_from else None,
        'effective_until': c.effective_until.isoformat() if c.effective_until else None,
        'title': c.section_id, 'body': c.content} for c in chunks]
    repo = _MemoryRepository(sources)
    actor = 'offline-fixture-reviewer'
    await repo.put('permissions', actor, {'permissions': ['knowledge_review']})
    await repo.put('gaps', 'offline-gap', {'id': 'offline-gap', 'category': 'content',
                                        'version': 1, 'status': 'triaged'})
    config = PolicyRuntimeConfig(tokenizer_revision='offline-fixture', tokenizer_sha256='a'*64,
        max_tokens=8000, dimension=2, dense_candidates=30, sparse_candidates=30,
        hard_limit=10, dense_threshold=.4, relevance_verified=True, queue_capacity=1,
        deadline_seconds=10, dependency_timeout_seconds=2, breaker_failures=2, breaker_cooldown_seconds=.05)
    # This isolated command never loads Settings/.env or connects to configured services.
    with ExitStack() as stack:
        stack.enter_context(patch('app.configs.get_settings', return_value=SimpleNamespace(
            knowledge_policy_config_file=Path('offline-fixture'))))
        stack.enter_context(patch('app.mcp_servers.mcp_knowledge.config.load_policy_config', return_value=config))
        stack.enter_context(patch.object(socket.socket, 'connect', _deny_network))
        stack.enter_context(patch.object(socket.socket, 'connect_ex', _deny_network))
        stack.enter_context(patch.object(socket, 'create_connection', _deny_network))
        encoder = PolicyEncoder(config, _FixtureDenseBackend())
        client = AsyncQdrantClient(':memory:')
        index = HybridPolicyIndex(client)
        service = PolicySearchService(repo, encoder, index, config)
        build_args = dict(source_dir=source_dir, metadata=metadata, actor_id=actor)
        checks, searches = {}, {}
        try:
            base = await build_policy_release(repo, encoder, index, revision_ids=[], expected_active_id=None, **build_args)
            await command(repo, actor, 'activate_release', {'id': base['id'], 'expected_active_id': None})
            await service.start()
            request = PolicySearchInput(query='Đổi hàng cần giữ nguyên tem nhãn và hộp không?',
                                        on=date(2026, 11, 11), top_k=10)
            async with Client(create_server(service, context_secret='offline-fixture-secret')) as mcp:
                async def lookup(name, pin=None):
                    context = TrustedPolicyContext(request_id=name, principal='harness', on=request.on,
                        release_id=pin, verified_order_date=date(2026, 10, 20), date_source='offline_fixture')
                    result = await mcp.call_tool('policy.search', {**request.model_dump(mode='json'),
                        'trusted_context': sign_policy_context(request, context, 'offline-fixture-secret')})
                    data = result.data if isinstance(result.data, dict) else result.structured_content
                    if not isinstance(data, dict) or data.get('retrieval_status') != 'ok':
                        raise ValueError('MCP policy.search did not return healthy evidence')
                    searches[name] = data
                    return {e['chunk_id'] for e in data['evidence']}

                await lookup('k0')
                revision = await command(repo, actor, 'create_revision', {'gap_id': 'offline-gap', 'kind': 'faq',
                    'question': request.query, 'answer': source.content, 'source_ids': [source.chunk_id],
                    'source_review_note': 'OFFLINE FIXTURE: source-bound draft; no human review claimed.'})
                key = 'KG-' + revision['id']
                try:
                    await build_policy_release(repo, encoder, index, revision_ids=[revision['id']],
                                               expected_active_id=base['id'], **build_args)
                except KnowledgeError:
                    checks['unapproved_build_rejected'] = True
                _check(checks, 'unapproved_build_rejected', checks.get('unapproved_build_rejected')
                       and (await repo.get('active', 'current'))['release_id'] == base['id'])
                await command(repo, actor, 'approve', {'id': revision['id'], 'content_hash': revision['content_hash'],
                    'reason': 'SIMULATED offline review of source and test, not human approval.', 'approve_test': True})
                ready = await build_policy_release(repo, encoder, index, revision_ids=[revision['id']],
                                                   expected_active_id=base['id'], **build_args)
                _check(checks, 'draft_not_visible', key not in await lookup('prepared_not_active')
                       and searches['prepared_not_active']['context']['knowledge_release_id'] == base['id'])
                await command(repo, actor, 'activate_release', {'id': ready['id'], 'expected_active_id': base['id']})
                ids = await lookup('k1')
                _check(checks, 'k1_visible', {key, source.chunk_id} <= ids
                       and any(e['chunk_id'] == key and source.content in e['content'] for e in searches['k1']['evidence'])
                       and searches['k1']['context']['knowledge_release_id'] == ready['id'])
                _check(checks, 'pinned_k0_unchanged', key not in await lookup('pinned_k0', base['id'])
                       and searches['pinned_k0']['evidence'] == searches['k0']['evidence'])
                audit_before = await repo.rows('audit')
                for check_name, rollback_actor, expected, error in (
                    ('stale_rollback_rejected', actor, base['id'], Conflict),
                    ('unauthorized_rollback_rejected', 'offline-no-permission', ready['id'], Forbidden)):
                    try:
                        await command(repo, rollback_actor, 'rollback_release', {'id': base['id'], 'expected_active_id': expected})
                    except error:
                        checks[check_name] = True
                    _check(checks, check_name, checks.get(check_name)
                           and (await repo.get('active', 'current'))['release_id'] == ready['id']
                           and await repo.rows('audit') == audit_before)
                await command(repo, actor, 'rollback_release', {'id': base['id'], 'expected_active_id': ready['id']})
                _check(checks, 'rollback_restores_k0', key not in await lookup('rolled_back')
                       and searches['rolled_back']['context']['knowledge_release_id'] == base['id']
                       and searches['rolled_back']['evidence'] == searches['k0']['evidence']
                       and (await repo.get('active', 'current'))['release_id'] == base['id'])
                _check(checks, 'pinned_k1_preserved', key in await lookup('pinned_k1_after_rollback', ready['id'])
                       and searches['pinned_k1_after_rollback']['evidence'] == searches['k1']['evidence'])
            audit = await repo.rows('audit')
            rollback_audit = [a for a in audit if a['action'] == 'rollback_release']
            _check(checks, 'rollback_audited', len(rollback_audit) == 1 and rollback_audit[0]['actor_id'] == actor
                   and rollback_audit[0]['release_id'] == base['id'] and rollback_audit[0]['previous_release_id'] == ready['id'])
            after_digest = digest([c.model_dump(mode='json') for c in parse_policy_sources(source_dir, metadata)])
            _check(checks, 'corpus_unchanged', source_digest == after_digest)
            gap = await repo.get('gaps', 'offline-gap')
            _check(checks, 'gap_not_auto_resolved', gap['status'] == 'awaiting_verification')
            def reference(release):
                return {'release_id': release['id'], 'manifest_hash': release['manifest_hash'],
                        'snapshot_hash': release['manifest']['snapshot_hash']}
            return {'kind': 'offline_knowledge_rollback_rehearsal', 'schema_version': 1,
                'review_mode': 'simulated_not_human', 'storage': 'in_memory',
                'embedding': 'constant_fixture_not_cloudflare', 'llm_answer_evaluated': False,
                'source_digest_before': source_digest, 'source_digest_after': after_digest,
                'runtime_config': config.model_dump(mode='json'),
                'runtime_config_hash': digest(config.model_dump(mode='json')), 'checks': checks,
                'releases': {'k0': reference(base), 'k1': reference(ready)},
                'revision': await repo.get('revisions', revision['id']),
                'regression_case': await repo.get('regression_cases', revision['id']),
                'decisions': await repo.rows('decisions'), 'gap': gap, 'audit': audit, 'searches': searches,
                'limitations': ['Real lifecycle/hybrid/MCP code with fixture storage and dense vectors; no PostgreSQL/remote Qdrant/provider tested.',
                    'Review and verified order date are simulated fixtures, not human review or agent-verified facts.',
                    'Rollback changes the default release; it does not revoke immutable pinned snapshots.',
                    'No LLM answer quality, learning improvement, production latency or concurrent load is measured.']}
        finally:
            await encoder.close()
            await client.close()


def render_report(report):
    lines = ['# Offline knowledge rollback rehearsal', '',
        'Review: simulated_not_human. Storage: RAM. Dense embeddings: constant fixture.', '',
        '| Check | Passed |', '|---|---|']
    lines += [f'| {name} | {passed} |' for name, passed in report['checks'].items()]
    lines += ['', '| Stage | Release | Evidence IDs |', '|---|---|---|']
    for name, result in report['searches'].items():
        ids = ', '.join(e['chunk_id'] for e in result['evidence'])
        lines.append(f"| {name} | {result['context']['knowledge_release_id']} | {ids} |")
    return '\n'.join(lines + ['', *report['limitations']]) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--btc-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        root, out = args.btc_root.resolve(), args.out.resolve()
        if out == root or root in out.parents:
            raise ValueError('Output must be outside the BTC source package')
        if args.out.exists():
            raise FileExistsError('Choose a new output directory')
        report = asyncio.run(rehearse(args.btc_root))
        if not report.get('checks') or not all(report['checks'].values()):
            raise ValueError('Rehearsal checks incomplete')
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (args.out/'report.md').write_text(render_report(report), encoding='utf-8')
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f'Offline rehearsal failed ({type(exc).__name__}); no passed result is claimed.\n')
    print(f"Offline rollback verified — {args.out/'report.md'}")


if __name__ == '__main__':
    main()
