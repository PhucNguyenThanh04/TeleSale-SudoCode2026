"""Scoped uniqueness migration on a temporary PostgreSQL table."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

import asyncpg


@unittest.skipUnless(os.getenv("MEMORY_MIGRATION_TEST_DSN"),
                     "requires MEMORY_MIGRATION_TEST_DSN")
class ScopedFactMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_fact_remains_global_and_products_can_share_key(self):
        connection = await asyncpg.connect(os.environ["MEMORY_MIGRATION_TEST_DSN"])
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute("""CREATE TEMP TABLE facts (
                fact_id uuid PRIMARY KEY, customer_id text, key text,
                source_session_id uuid, source_turn_id uuid, status text)""")
            legacy = uuid4()
            await connection.execute("""INSERT INTO pg_temp.facts
                (fact_id,customer_id,key,source_session_id,source_turn_id,status)
                VALUES ($1,'C901','price_quoted_vnd',$2,$3,'active')""",
                legacy, uuid4(), uuid4())
            migration = (Path(__file__).resolve().parents[1] / "migrations" /
                         "0001_memory.sql").read_text().split(
                             "-- BEGIN 0008_scoped_facts\n", 1)[1].split(
                             "-- END 0008_scoped_facts", 1)[0]
            await connection.execute(migration.replace("ai_memory.", "pg_temp."))
            row = await connection.fetchrow("""SELECT scope_type,scope_id FROM pg_temp.facts
                WHERE fact_id=$1""", legacy)
            self.assertEqual((row["scope_type"], row["scope_id"]), ("global", ""))
            for sku in ("SKU-ALPHA", "SKU-BETA"):
                await connection.execute("""INSERT INTO pg_temp.facts
                    (fact_id,customer_id,key,source_session_id,source_turn_id,
                     status,scope_type,scope_id)
                    VALUES ($1,'C901','price_quoted_vnd',$2,$3,'active','product',$4)""",
                    uuid4(), uuid4(), uuid4(), sku)
            with self.assertRaises(asyncpg.UniqueViolationError):
                await connection.execute("""INSERT INTO pg_temp.facts
                    (fact_id,customer_id,key,source_session_id,source_turn_id,
                     status,scope_type,scope_id)
                    VALUES ($1,'C901','price_quoted_vnd',$2,$3,'active','product','SKU-ALPHA')""",
                    uuid4(), uuid4(), uuid4())
        finally:
            await transaction.rollback()
            await connection.close()
