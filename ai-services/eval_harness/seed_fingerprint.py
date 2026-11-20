
import hashlib
import json

import asyncpg


async def fingerprint_btc_source(dsn: str) -> str:
    connection = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        tables = [row["tablename"] for row in await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='btc_source' ORDER BY tablename")]
        if not tables:
            raise ValueError("btc_source has no tables to fingerprint")
        digest = hashlib.sha256()
        for table in tables:
            columns = await connection.fetch(
                "SELECT column_name,data_type FROM information_schema.columns "
                "WHERE table_schema='btc_source' AND table_name=$1 "
                "ORDER BY ordinal_position", table)
            digest.update(json.dumps({"table": table,
                                      "columns": [(r["column_name"], r["data_type"])
                                                  for r in columns]},
                                     sort_keys=True).encode())
            safe_table = table.replace('"', '""')
            rows = await connection.fetch(f'SELECT * FROM btc_source."{safe_table}"')
            encoded = sorted(json.dumps(dict(row), sort_keys=True,
                                        ensure_ascii=False, default=str)
                             for row in rows)
            for item in encoded:
                digest.update(b"\0")
                digest.update(item.encode())
        return digest.hexdigest()
    finally:
        await connection.close()
