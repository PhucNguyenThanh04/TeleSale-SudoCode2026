
from __future__ import annotations

import argparse
import asyncio
import os
import json
from pathlib import Path
from urllib.parse import urlsplit

from .source import read_release, release_counts, source_fingerprint

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT.parent / "BTC-Data-Vong1-TEAMS"


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if value:
        return value
    path = ROOT / "backend" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"\'')
    raise ValueError("Set DATABASE_URL or backend/.env before importing")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import BTC catalog, CRM and policy into PostgreSQL")
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("BTC_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--dry-run", action="store_true", help="Validate and count data; do not connect to services")
    parser.add_argument("--only-postgres", action="store_true", help="Compatibility option; cannot be combined with --prepare-policy")
    parser.add_argument("--verify-postgres", action="store_true", help="Show target database and actual table counts without importing")
    parser.add_argument("--verify-ingestion", action="store_true", help="Read-only comparison of source, PostgreSQL snapshot and Qdrant")
    parser.add_argument("--release-id", help="Exact release to verify (required with --verify-ingestion)")
    parser.add_argument("--metadata", type=Path, help="Reviewed policy metadata shared with the index build")
    parser.add_argument("--prepare-policy", action="store_true", help="Explicitly encode/build an MCP Knowledge release after source import; never activates")
    parser.add_argument("--actor", help="Reviewer actor with knowledge_review permission")
    parser.add_argument("--runtime-config", type=Path, help="Reviewed Cloudflare dense/BM25 runtime JSON")
    parser.add_argument("--expected-active", help="Current active release ID; omit for the first build")
    parser.add_argument("--revision-id", action="append", default=[], help="Approved supplement revision to include")
    args = parser.parse_args()
    if args.verify_ingestion:
        if args.prepare_policy or args.verify_postgres or args.only_postgres or args.dry_run:
            parser.error('--verify-ingestion cannot be combined with other import/inspection modes')
        if not args.release_id or not args.runtime_config:
            parser.error('--verify-ingestion requires --release-id and --runtime-config')
        if not args.runtime_config.is_file():
            parser.error('--runtime-config file does not exist: '+str(args.runtime_config))
    elif args.release_id:
        parser.error('--release-id requires --verify-ingestion')
    if args.verify_postgres and args.dry_run:
        parser.error("--verify-postgres cannot be combined with --dry-run")
    if args.prepare_policy:
        if args.only_postgres or args.verify_postgres:
            parser.error("--prepare-policy cannot be combined with --only-postgres or --verify-postgres")
        if not args.actor or not args.runtime_config:
            parser.error("--prepare-policy requires --actor and --runtime-config")
        if not args.dry_run and not args.runtime_config.is_file():
            parser.error(
                f"--runtime-config file does not exist: {args.runtime_config}. "
                "Provide an existing policy runtime JSON; /path/to/... is only an example. "
                "See the setup section in the root README.md."
            )
    elif args.actor or (args.runtime_config and not args.verify_ingestion) or args.expected_active or args.revision_id:
        parser.error("Policy build options require --prepare-policy")

    if args.verify_ingestion:
        from .knowledge import _enable_ai_imports
        _enable_ai_imports()
        from app.knowledge.config import configured_url, qdrant_url
        from .verification import verify_ingestion
        report = asyncio.run(verify_ingestion(database_url(),args.data_dir,
            knowledge_database_url=configured_url('KNOWLEDGE_DATABASE_URL'),qdrant_url=qdrant_url(),
            release_id=args.release_id,runtime_config_path=args.runtime_config,metadata_path=args.metadata))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        raise SystemExit(0 if report['ingestion_status']=='passed' else 1)

    if args.verify_postgres:
        from .postgres import inspect_database

        target = urlsplit(database_url())
        print("Connecting to:", {"host": target.hostname, "port": target.port, "database": target.path.lstrip("/")})
        print("Database inspection:", asyncio.run(inspect_database(database_url())))
        return

    try:
        release = read_release(args.data_dir, metadata_path=args.metadata)
    except Exception as exc:
        parser.exit(1,'BTC source validation failed ('+type(exc).__name__+')\n')
    counts = release_counts(release)
    print("BTC source validated:", counts)
    if args.dry_run:
        return

    target = urlsplit(database_url())
    print("Importing to:", {"host": target.hostname, "port": target.port, "database": target.path.lstrip("/")})
    try:
        asyncio.run(import_data(args, release))
    except ImportStageError as exc:
        parser.exit(1, str(exc)+'\n')


class ImportStageError(ValueError):
    pass


async def import_data(args, release):
    from .postgres import import_release, SourceSnapshotMismatch
    from .knowledge import prepare_policy, validate_policy_prepare

    stage, committed = 'preflight', False
    try:
        if args.prepare_policy:
            await validate_policy_prepare(actor=args.actor, runtime_config=args.runtime_config,
                expected_active=args.expected_active, source_database_url=database_url())
        if release.get('source_fingerprint') and source_fingerprint(args.data_dir,args.metadata)!=release['source_fingerprint']:
            raise ValueError('BTC source changed before import')
        stage = 'postgres'
        pg_counts = await import_release(database_url(), release)
        committed = True
        print("PostgreSQL imported:", pg_counts)
        if args.prepare_policy:
            stage = 'policy_prepare'
            if release.get('source_fingerprint') and source_fingerprint(args.data_dir,args.metadata)!=release['source_fingerprint']:
                raise ValueError('BTC source changed before policy preparation')
            prepared = await prepare_policy(args.data_dir.resolve(), actor=args.actor,
                runtime_config=args.runtime_config, metadata_path=args.metadata,
                expected_active=args.expected_active, revision_ids=args.revision_id)
            if release.get('source_fingerprint') and source_fingerprint(args.data_dir,args.metadata)!=release['source_fingerprint']:
                raise ValueError('BTC source changed during policy preparation')
            print("MCP Knowledge release built (not activated):", {
                "release_id": prepared['id'], "status": prepared['status']})
        else:
            print("MCP Knowledge index not built; use --prepare-policy for an explicit build.")
    except Exception as exc:
        details = 'reason='+type(exc).__name__
        if isinstance(exc, SourceSnapshotMismatch):
            details = 'reason=source_snapshot_mismatch; '+str(exc)
        try:
            from app.mcp_servers.mcp_knowledge.services.cloudflare import PolicyProviderError
        except ImportError:
            PolicyProviderError = None
        if PolicyProviderError is not None and isinstance(exc, PolicyProviderError):
            details = (f'provider=cloudflare; reason={exc.reason}; '
                       f'http_status={exc.status}; provider_code={exc.provider_code}')
        raise ImportStageError(f'Import failed: stage={stage}; source_commit_confirmed={committed}; {details}') from None


if __name__ == "__main__":
    main()
