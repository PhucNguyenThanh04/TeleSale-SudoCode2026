from app.knowledge.config import qdrant_url
from app.knowledge.config import configured_url
import argparse
import asyncio
import json
from pathlib import Path
from app.knowledge.repos.postgres import KnowledgeRepo
from app.knowledge.schemas import TABLES, KnowledgeError, timestamp
from app.knowledge.services.permissions import require_permission


async def execute(args):
    env = 'KNOWLEDGE_ADMIN_DATABASE_URL' if args.action in {'grant', 'revoke'} else 'KNOWLEDGE_DATABASE_URL'
    dsn = configured_url(env)
    if not dsn:
        raise SystemExit(env+' required')
    repo = KnowledgeRepo(dsn)
    try:
        if args.action == 'policy-prepare':
            from app.knowledge.services.publish import build_configured_policy_release
            return await build_configured_policy_release(repo, args.revision_id, args.expected_active, args.actor,
                source_dir=args.source_dir, metadata_path=args.metadata, config_path=args.runtime_config)
        if args.action in {'policy-activate', 'policy-rollback'}:
            if not args.release_id:
                raise KnowledgeError('--release-id required')
            from app.knowledge.services.releases import activate_release, rollback_release
            from app.mcp_servers.mcp_knowledge.repos.postgres import PolicyRepository
            policy_repo = PolicyRepository(dsn)
            try:
                release = await policy_repo.resolve_release(args.release_id)
                from app.mcp_servers.mcp_knowledge.config import load_policy_config
                from app.configs import get_settings
                from app.mcp_servers.mcp_knowledge.repos.qdrant import HybridPolicyIndex
                from qdrant_client import AsyncQdrantClient
                settings = get_settings()
                if args.runtime_config:
                    settings = settings.model_copy(update={'knowledge_policy_config_file': args.runtime_config})
                config = load_policy_config(settings)
                client = AsyncQdrantClient(url=qdrant_url(), timeout=config.dependency_timeout_seconds)
                try:
                    await HybridPolicyIndex(client).verify(release, config)
                finally:
                    await client.close()
            finally:
                await policy_repo.close()
            operation = activate_release if args.action == 'policy-activate' else rollback_release
            return await operation(repo, release['id'], args.expected_active, args.actor)
        if args.action == 'policy-revoke':
            if not args.section_id:
                raise KnowledgeError('--section-id required')
            async with repo.transaction() as tx:
                await require_permission(tx, args.actor)
                await tx.put('policy_revocations', args.section_id, {'id': args.section_id, 'at': timestamp()})
                await tx.put('audit', 'revoke-'+args.section_id, {'id':'revoke-'+args.section_id,
                    'action':'revoke_policy_source', 'section_id':args.section_id, 'actor_id':args.actor, 'at':timestamp()})
            return {'status':'revoked','section_id':args.section_id}
        async with repo.transaction() as tx:
            if args.action in {'grant', 'revoke'}:
                if not args.actor or args.actor.startswith('web-visitor:'):
                    raise KnowledgeError('Internal actor required')
                await tx.put('permissions', args.actor, {'id': args.actor,
                    'permissions': ['knowledge_review'] if args.action == 'grant' else [], 'updated_at': timestamp()})
                return {'actor_id': args.actor, 'permission': args.action}
            await require_permission(tx, args.actor)
            if args.action == 'export':
                if not args.out:
                    raise KnowledgeError('--out required')
                export = {table: await tx.rows(table) for table in sorted(TABLES-{'permissions', 'erasures', 'backend_outbox'})}
                args.out.parent.mkdir(parents=True, exist_ok=True)
                with args.out.open('x', encoding='utf-8') as stream:
                    json.dump(export, stream, ensure_ascii=False, indent=2)
                return {'exported': str(args.out)}
    finally:
        await repo.close()


def main():
    p = argparse.ArgumentParser(description='Administrative knowledge lifecycle; policy-prepare explicitly encodes with a cached local model.')
    p.add_argument('action', choices=['grant', 'revoke', 'export', 'policy-prepare', 'policy-activate', 'policy-rollback', 'policy-revoke'])
    p.add_argument('--actor', required=True)
    p.add_argument('--out', type=Path)
    p.add_argument('--source-dir', type=Path)
    p.add_argument('--metadata', type=Path)
    p.add_argument('--runtime-config', type=Path)
    p.add_argument('--revision-id', action='append', default=[])
    p.add_argument('--expected-active')
    p.add_argument('--release-id')
    p.add_argument('--section-id')
    args = p.parse_args()
    print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False))


if __name__ == '__main__':
    main()
