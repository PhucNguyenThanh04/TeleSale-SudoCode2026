
import os
import unittest
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

from app.configs import Settings
from app.mcp_servers.mcp_shared.config import database_url


class SeedFingerprintTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("EVAL_RESET_TEST_DB") == "1", "requires isolated PostgreSQL")
    async def test_fingerprint_ignores_row_order_but_detects_changed_source_data(self):
        from eval_harness.seed_fingerprint import fingerprint_btc_source

        source = make_url(database_url(Settings()))
        admin = await asyncpg.connect(source.set(database="postgres")
                                      .render_as_string(hide_password=False)
                                      .replace("postgresql+asyncpg://", "postgresql://", 1))
        name = "telesale_eval_seed_" + uuid4().hex[:12]
        try:
            await admin.execute(f'CREATE DATABASE "{name}"')
            dsn = source.set(database=name).render_as_string(hide_password=False)
            db = await asyncpg.connect(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
            try:
                await db.execute("CREATE SCHEMA btc_source")
                await db.execute("CREATE TABLE btc_source.products (sku text, price integer)")
                await db.execute("INSERT INTO btc_source.products VALUES ('A', 10), ('B', 20)")
                before = await fingerprint_btc_source(dsn)
                await db.execute("TRUNCATE btc_source.products")
                await db.execute("INSERT INTO btc_source.products VALUES ('B', 20), ('A', 10)")
                self.assertEqual(before, await fingerprint_btc_source(dsn))
                await db.execute("UPDATE btc_source.products SET price=30 WHERE sku='B'")
                self.assertNotEqual(before, await fingerprint_btc_source(dsn))
            finally:
                await db.close()
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.close()
