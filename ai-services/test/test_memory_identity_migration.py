"""Exercise the identity cleanup on temporary PostgreSQL tables only."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

import asyncpg


@unittest.skipUnless(os.getenv("MEMORY_MIGRATION_TEST_DSN"),
                     "requires MEMORY_MIGRATION_TEST_DSN")
class MemoryIdentityMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_claimed_turns_are_unbound_before_episode_rebuild(self):
        connection = await asyncpg.connect(os.environ["MEMORY_MIGRATION_TEST_DSN"])
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute("""CREATE TEMP TABLE turns
                (session_id uuid, turn_no int, customer_id text,
                 customer_text text, agent_text text)""")
            await connection.execute("""CREATE TEMP TABLE episodes
                (session_id uuid, customer_id text, summary text,
                 updated_at timestamptz)""")
            await connection.execute("""CREATE TEMP TABLE facts
                (fact_id uuid, source_session_id uuid, source_turn_id uuid,
                 status text)""")
            await connection.execute("""CREATE TEMP TABLE write_operations
                (operation_key text, result jsonb, created_at timestamptz)""")

            mixed, clean, failed_claim = uuid4(), uuid4(), uuid4()
            anonymous_message, unkeyed_message, known_message = uuid4(), uuid4(), uuid4()
            anonymous_fact, unkeyed_fact, known_fact = uuid4(), uuid4(), uuid4()
            await connection.execute("""INSERT INTO pg_temp.turns VALUES
                ($1,1,'C001','Phòng 48 m²','Dạ'),
                ($1,2,'C001','Muốn máy êm','Dạ'),
                ($2,1,'C002','Tôi thích mẫu nhỏ','Dạ'),
                ($3,1,'C003','Tôi chọn màu xanh','Dạ')""", mixed, clean, failed_claim)
            await connection.execute("""INSERT INTO pg_temp.episodes VALUES
                ($1,'C001','Phòng 48 m² | Muốn máy êm',now()),
                ($2,'C002','Tôi thích mẫu nhỏ',now()),
                ($3,'C003','Tôi chọn màu xanh',now())""", mixed, clean, failed_claim)
            await connection.execute("""INSERT INTO pg_temp.facts VALUES
                ($1,$4,$5,'active'),($2,$4,$6,'active'),($3,$4,$7,'active')""",
                anonymous_fact, unkeyed_fact, known_fact, mixed,
                anonymous_message, unkeyed_message, known_message)
            await connection.execute("""INSERT INTO pg_temp.write_operations VALUES
                ($1,$2::jsonb,'2026-10-15 10:00:00+00'),
                ($3,$4::jsonb,'2026-10-15 10:01:00+00'),
                ($5,$6::jsonb,'2026-10-15 10:02:00+00')""",
                f"{mixed}:{anonymous_message}:commit_turn", '{"turn_no":1}',
                f"{mixed}:C001:{known_message}:claim_pending",
                '{"memory_writes":[{"fact_id":"' + str(unkeyed_fact) + '"}]}',
                f"{mixed}:{known_message}:commit_turn", '{"turn_no":2}')
            await connection.execute("""INSERT INTO pg_temp.write_operations VALUES
                ($1,$2::jsonb,'2026-10-15 10:03:00+00')""",
                f"{failed_claim}:C999:{uuid4()}:claim_pending",
                '{"error":"session_owner_mismatch"}')
            await connection.execute("""INSERT INTO pg_temp.write_operations VALUES
                ($1,$2::jsonb,'2026-10-15 10:04:00+00')""",
                f"{'-' * 36}:C999:{uuid4()}:claim_pending",
                '{"memory_writes":[]}')

            migration = (Path(__file__).resolve().parents[1] / "migrations" /
                         "0006_episode_identity_boundary.sql").read_text()
            await connection.execute(migration.replace("ai_memory.", "pg_temp."))

            rows = await connection.fetch("""SELECT session_id,turn_no,customer_id
                FROM pg_temp.turns ORDER BY session_id,turn_no""")
            owner = {(row["session_id"], row["turn_no"]): row["customer_id"]
                     for row in rows}
            self.assertIsNone(owner[(mixed, 1)])
            self.assertEqual(owner[(mixed, 2)], "C001")
            self.assertEqual(owner[(clean, 1)], "C002")
            self.assertEqual(owner[(failed_claim, 1)], "C003")
            summary = await connection.fetchval(
                "SELECT summary FROM pg_temp.episodes WHERE session_id=$1", mixed)
            self.assertNotIn("48 m²", summary)
            self.assertIn("Muốn máy êm", summary)
            facts = await connection.fetch("""SELECT source_turn_id,status
                FROM pg_temp.facts WHERE source_session_id=$1""", mixed)
            statuses = {row["source_turn_id"]: row["status"] for row in facts}
            self.assertEqual(statuses[anonymous_message], "retracted")
            self.assertEqual(statuses[unkeyed_message], "retracted")
            self.assertEqual(statuses[known_message], "active")
        finally:
            await transaction.rollback()
            await connection.close()
