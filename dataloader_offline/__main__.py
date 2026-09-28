"""Run with ``python -m dataloader_offline`` from the repository root."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from .source import read_release

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
    parser = argparse.ArgumentParser(description="Import BTC catalog, CRM and policy into PostgreSQL/Qdrant")
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("BTC_DATA_DIR", DEFAULT_DATA)))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--embedding-model", default=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"))
    parser.add_argument("--dry-run", action="store_true", help="Validate and count data; do not connect to services")
    parser.add_argument("--only-postgres", action="store_true", help="Import PostgreSQL only; skip Qdrant and embeddings")
    parser.add_argument("--verify-postgres", action="store_true", help="Show target database and actual table counts without importing")
    args = parser.parse_args()

    if args.verify_postgres:
        from .postgres import inspect_database

        target = urlsplit(database_url())
        print("Connecting to:", {"host": target.hostname, "port": target.port, "database": target.path.lstrip("/")})
        print("Database inspection:", asyncio.run(inspect_database(database_url())))
        return

    release = read_release(args.data_dir)
    counts = {
        "products": len(release["products"]["products"]),
        "variants": sum(len(p.get("variants", [])) for p in release["products"]["products"]),
        "promotions": len(release["promotions"]["promotions"]),
        "inventory_events": len(release["inventory"]["events"]),
        "customers": len(release["crm"]["customers"]),
        "policy_chunks": len(release["chunks"]),
        "restricted_chunks": sum(c.access_level != "public" for c in release["chunks"]),
    }
    print("BTC source validated:", counts)
    if args.dry_run:
        return

    from .postgres import import_release

    target = urlsplit(database_url())
    print("Importing to:", {"host": target.hostname, "port": target.port, "database": target.path.lstrip("/")})
    pg_counts = asyncio.run(import_release(database_url(), release))
    print("PostgreSQL imported:", pg_counts)
    if args.only_postgres:
        return

    from .vector import import_vectors

    qdrant_counts = import_vectors(args.qdrant_url, args.embedding_model, release)
    print("Qdrant points inserted/updated:", qdrant_counts)


if __name__ == "__main__":
    main()
