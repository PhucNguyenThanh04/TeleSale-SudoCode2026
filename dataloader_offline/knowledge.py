import argparse
import json
import sys
import re
import importlib.util
from pathlib import Path


def _enable_ai_imports():
    path = str(Path(__file__).resolve().parents[1] / 'ai-services')
    if path not in sys.path:
        sys.path.insert(0, path)


def policy_sources(directory, metadata_path=None):
    _enable_ai_imports()
    from app.knowledge.policy.source import default_metadata, parse_policy_sources
    metadata = (json.loads(Path(metadata_path).read_text(encoding='utf-8'))
                if metadata_path else default_metadata())
    return parse_policy_sources(directory, metadata)


def _validate_provider_runtime(config):
    from app.configs import get_settings
    from app.mcp_servers.mcp_knowledge.services.embedding import load_tokenizer
    from app.knowledge.schemas import KnowledgeError
    settings = get_settings()
    if not re.fullmatch(r'[a-fA-F0-9]{32}', settings.cloudflare_account_id or ''):
        raise KnowledgeError('CLOUDFLARE_ACCOUNT_ID required (32 hex characters)')
    if not settings.cloudflare_api_token or not settings.cloudflare_api_token.get_secret_value().strip():
        raise KnowledgeError('CLOUDFLARE_API_TOKEN required')
    load_tokenizer(config)


async def _check_prepare_dependencies(config, dsn, source_database_url):
    import asyncpg
    from qdrant_client import AsyncQdrantClient
    from app.knowledge.config import qdrant_url
    from app.knowledge.schemas import KnowledgeError
    from .postgres import _asyncpg_url
    _validate_provider_runtime(config)
    async def identity(url, check_schema=False):
        conn = await asyncpg.connect(_asyncpg_url(url), timeout=config.dependency_timeout_seconds)
        try:
            async with conn.transaction(readonly=True):
                result = dict(await conn.fetchrow("SELECT current_database() AS database, "
                    "extract(epoch from pg_postmaster_start_time())::text AS server_epoch"))
                if check_schema:
                    for table in ['permissions','active','releases','policy_sources','policy_revocations',
                                  'revisions','regression_cases','audit']:
                        name = 'knowledge.'+table
                        if not await conn.fetchval('SELECT to_regclass($1) IS NOT NULL', name):
                            raise KnowledgeError('Missing table: '+name)
                        if not await conn.fetchval("SELECT has_table_privilege(current_user,$1,'SELECT')", name):
                            raise KnowledgeError('Missing SELECT privilege: '+name)
                    for table in ['releases','policy_sources','audit']:
                        for permission in ['INSERT','UPDATE']:
                            if not await conn.fetchval('SELECT has_table_privilege(current_user,$1,$2)', 'knowledge.'+table, permission):
                                raise KnowledgeError('Missing '+permission+' privilege: knowledge.'+table)
                    if not await conn.fetchval("SELECT has_table_privilege(current_user,'btc_source.policy_chunks','SELECT')"):
                        raise KnowledgeError('Missing SELECT privilege: btc_source.policy_chunks')
                return result
        finally:
            await conn.close()
    reviewer = await identity(dsn, True)
    if source_database_url and await identity(source_database_url) != reviewer:
        raise KnowledgeError('Source and reviewer database identity mismatch')
    client = AsyncQdrantClient(url=qdrant_url(), timeout=config.dependency_timeout_seconds)
    try:
        await client.get_collections()
    finally:
        await client.close()


async def validate_policy_prepare(*, actor, runtime_config, expected_active, source_database_url=None):
    _enable_ai_imports()
    from app.knowledge.config import configured_url
    from app.knowledge.repos.postgres import KnowledgeRepo
    from app.knowledge.schemas import Conflict, KnowledgeError
    from app.knowledge.services.permissions import require_permission
    from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig

    config = PolicyRuntimeConfig.model_validate(json.loads(Path(runtime_config).read_text(encoding='utf-8')))
    dsn = configured_url('KNOWLEDGE_DATABASE_URL')
    if not dsn:
        raise KnowledgeError('KNOWLEDGE_DATABASE_URL required for --prepare-policy')
    repo = KnowledgeRepo(dsn)
    try:
        async with repo.transaction() as tx:
            await require_permission(tx, actor)
            if (await tx.get('active', 'current') or {}).get('release_id') != expected_active:
                raise Conflict('Active release changed')
    finally:
        await repo.close()
    await _check_prepare_dependencies(config, dsn, source_database_url)


async def prepare_policy(source_dir, *, actor, runtime_config, metadata_path,
                         expected_active, revision_ids):
    _enable_ai_imports()
    from app.knowledge.cli import execute
    return await execute(argparse.Namespace(
        action='policy-prepare', actor=actor, source_dir=Path(source_dir) / 'policy',
        metadata=metadata_path, runtime_config=runtime_config,
        revision_id=revision_ids, expected_active=expected_active))
