"""Memory provenance, supersession and replay checks."""

import hashlib
import json
import unittest
from contextlib import asynccontextmanager
from uuid import uuid4

from app.mcp_servers.mcp_memory.services.memory import read, write


class FakeRepo:
    def __init__(self):
        self.active = None
        self.statuses = []
        self.facts = []
        self.operations = {}

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def claim_operation(self, _conn, key, digest):
        old = self.operations.get(key)
        if old and old[0] != digest:
            return {"error": "operation_key_conflict"}
        return old[1] if old else None

    async def finish_operation(self, _conn, key, result):
        self.operations[key] = (self.digest, result)

    async def lock_key(self, *_):
        pass

    async def active_fact(self, *_):
        return self.active

    async def set_fact_status(self, _conn, fact_id, status):
        self.statuses.append((fact_id, status))

    async def insert_fact(self, _conn, fact_id, customer_id, key, value, source, session_id, previous):
        self.facts.append((fact_id, previous))
        self.active = fact_id


class TurnRepo(FakeRepo):
    def __init__(self):
        super().__init__()
        self.rows = {}
        self.episode_summaries = {}

    async def claim_operation(self, conn, key, digest):
        self.digest = digest
        return await super().claim_operation(conn, key, digest)

    async def owner(self, _conn, session_id):
        rows = self.rows.get(session_id, [])
        return rows[0]["customer_id"] if rows else None

    async def next_turn(self, _conn, session_id):
        return len(self.rows.get(session_id, [])) + 1

    async def insert_turn(self, _conn, session_id, number, customer_id,
                          channel, on, customer_text, agent_text):
        self.rows.setdefault(session_id, []).append({
            "turn_no": number, "customer_id": customer_id,
            "customer_text": customer_text, "agent_text": agent_text,
        })

    async def turns(self, _conn, session_id):
        return self.rows.get(session_id, [])

    async def upsert_episode(self, _conn, session_id, _customer_id,
                             _channel, _on, summary, _outcome):
        self.episode_summaries[session_id] = summary


class MemoryServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolved_blocker_is_retracted_before_new_blocker_is_opened(self):
        class BlockerRepo(TurnRepo):
            def __init__(self):
                super().__init__()
                self.values = {}

            async def active_fact_record(self, _conn, customer_id, key):
                return self.values.get((customer_id, key))

            async def set_fact_status(self, _conn, fact_id, status):
                await super().set_fact_status(_conn, fact_id, status)
                for entry in list(self.values):
                    if self.values[entry]["fact_id"] == fact_id:
                        del self.values[entry]

            async def insert_fact(self, _conn, fact_id, customer_id, key, value,
                                  source, session_id, previous, **metadata):
                self.values[(customer_id, key)] = {"fact_id": fact_id,
                                                    "value": json.dumps(value)}

        repo = BlockerRepo()
        session_id = str(uuid4())
        base = {
            "agent_text": "Dạ, em ghi nhận ạ.", "on": "2026-10-15",
            "channel": "hotline", "client_msg_id": str(uuid4())}
        await write(repo, "commit_turn", "C001", session_id, {
            **base, "customer_text": "Tôi phải hỏi chồng đã",
            "facts": [{"key": "blocker", "op": "set", "value": "hỏi chồng",
                       "source_kind": "customer"}],
        }, "prior-blocker")
        result = await write(repo, "commit_turn", "C001", session_id, {
            **base, "client_msg_id": str(uuid4()),
            "customer_text": "Chồng đồng ý nhưng phải chờ lương",
            "facts": [
                {"key": "blocker", "op": "delete", "source_kind": "customer"},
                {"key": "blocker", "op": "set", "value": "chờ lương",
                 "source_kind": "customer"},
            ],
        }, "resolve-and-replace")
        self.assertEqual([item["op"] for item in result["memory_writes"]],
                         ["delete", "set"])
        self.assertEqual(json.loads(repo.values[("C001", "blocker")]["value"]),
                         "chờ lương")

    async def test_anonymous_fact_is_claimed_only_after_verified_identity(self):
        class PendingRepo(TurnRepo):
            def __init__(self):
                super().__init__()
                self.pending = []
                self.values = {}

            async def stage_fact(self, _conn, session_id, source_turn_id,
                                 turn_no, fact, on):
                self.pending.append({"source_turn_id": source_turn_id,
                    "turn_no": turn_no, "key": fact["key"], "value": fact.get("value"),
                    "op": fact["op"], "source_kind": fact["source_kind"],
                    "source_tool": fact.get("source_tool"), "on_date": on})

            async def pending_facts(self, _conn, _session_id):
                return sorted(self.pending, key=lambda item: item["turn_no"])

            async def clear_pending(self, _conn, _session_id):
                self.pending.clear()

            async def bind_owner(self, _conn, session_id, customer_id):
                for row in self.rows[session_id]:
                    row["customer_id"] = customer_id

            async def active_fact_record(self, _conn, customer_id, key):
                return self.values.get((customer_id, key))

            async def insert_fact(self, _conn, fact_id, customer_id, key, value,
                                  source, session_id, previous, **metadata):
                self.values[(customer_id, key)] = {"fact_id": fact_id, "value": value}
                self.facts.append((source, value, metadata))

        repo = PendingRepo()
        session_id, message_id = str(uuid4()), str(uuid4())
        data = {"customer_text": "Phòng anh 25 m²", "agent_text": "Dạ, em ghi nhận ạ.",
                "on": "2026-10-15", "channel": "hotline", "client_msg_id": message_id,
                "facts": [{"key": "room_area_m2", "value": 25, "op": "set",
                           "source_kind": "customer"}]}
        staged = await write(repo, "commit_turn", None, session_id, data, "anonymous-turn")
        self.assertEqual(staged["memory_writes"], [])
        self.assertEqual(repo.facts, [])
        self.assertEqual(len(repo.pending), 1)
        claimed = await write(repo, "claim_pending", "C001", session_id, {}, "claim-1")
        self.assertEqual(claimed["memory_writes"][0]["value"], 25)
        self.assertEqual(repo.facts[0][0], f"{session_id}:{message_id}")
        self.assertEqual(repo.rows[session_id][0]["customer_id"], "C001")
        self.assertEqual((await write(repo, "claim_pending", "C001", session_id, {}, "claim-1")),
                         claimed)
        self.assertEqual(len(repo.facts), 1)

    async def test_turn_write_creates_history_without_prior_session_and_replays_retry(self):
        repo = TurnRepo()
        session_id = str(uuid4())
        first_data = {"customer_text": "Gọi 0984726714 hỏi AirPure X",
                      "agent_text": "Dạ, em thấy AirPure X ạ.",
                      "on": "2026-10-15", "channel": "chat_fanpage"}
        first = await write(repo, "turn", None, session_id, first_data,
                            f"{session_id}:msg-1:turn")
        replay = await write(repo, "turn", None, session_id, first_data,
                             f"{session_id}:msg-1:turn")
        self.assertEqual(first, {"turn_no": 1})
        self.assertEqual(replay, first)
        self.assertEqual(len(repo.rows[session_id]), 1)
        self.assertNotIn("0984726714", repo.rows[session_id][0]["customer_text"])
        self.assertEqual((await read(repo, None, session_id))["history"][0]["agent"],
                         first_data["agent_text"])

        second_data = {**first_data, "customer_text": "Giá bao nhiêu?",
                       "agent_text": "Dạ, em sẽ kiểm tra giá ạ."}
        self.assertEqual(await write(repo, "turn", None, session_id, second_data,
                                     f"{session_id}:msg-2:turn"), {"turn_no": 2})
        self.assertEqual(len((await read(repo, None, session_id))["history"]), 2)

    async def test_known_customer_turn_updates_episode_summary(self):
        repo = TurnRepo()
        session_id = str(uuid4())
        data = {"customer_text": "Tìm AirPure X", "agent_text": "Dạ, có AirPure X ạ.",
                "on": "2026-10-15", "channel": "chat_fanpage"}
        self.assertEqual(await write(repo, "turn", "C001", session_id, data),
                         {"turn_no": 1})
        self.assertIn("AirPure X", repo.episode_summaries[session_id])

    async def test_supersession_and_retry(self):
        repo = FakeRepo()
        session_id = str(uuid4())
        for index, (value, op) in enumerate(((5000000, "set"), (5700000, "supersede")), 1):
            data = {"key": "budget_vnd", "value": value, "op": op, "source": f"turn{index}"}
            repo.digest = hashlib.sha256(json.dumps({"action": "fact", "customer_id": "C001",
                "session_id": session_id, "data": data}, sort_keys=True,
                ensure_ascii=False).encode()).hexdigest()
            first = await write(repo, "fact", "C001", session_id, data, f"op-{index}")
            self.assertEqual(await write(repo, "fact", "C001", session_id, data, f"op-{index}"), first)
        self.assertEqual(len(repo.facts), 2)
        self.assertEqual(repo.statuses, [(repo.facts[0][0], "superseded")])
        self.assertEqual(repo.facts[1][1], repo.facts[0][0])

    async def test_commit_turn_writes_facts_once_and_supersedes_changed_value(self):
        class CommitRepo(TurnRepo):
            def __init__(self):
                super().__init__()
                self.values = {}

            async def active_fact_record(self, _conn, customer_id, key):
                return self.values.get((customer_id, key))

            async def insert_fact(self, _conn, fact_id, customer_id, key, value,
                                  source, session_id, previous, **metadata):
                self.facts.append((fact_id, previous, metadata))
                self.values[(customer_id, key)] = {"fact_id": fact_id, "value": value}

        repo = CommitRepo()
        session_id = str(uuid4())
        first_msg, second_msg = str(uuid4()), str(uuid4())
        base = {"customer_text": "Phòng anh 25 m²", "agent_text": "Dạ, em tư vấn ạ.",
                "on": "2026-10-15", "channel": "hotline", "client_msg_id": first_msg,
                "facts": [{"key": "room_area_m2", "value": 25, "op": "set",
                           "source_kind": "customer"}]}
        first = await write(repo, "commit_turn", "C001", session_id, base, "commit-1")
        replay = await write(repo, "commit_turn", "C001", session_id, base, "commit-1")
        self.assertEqual(first, replay)
        self.assertEqual(first["memory_writes"][0]["op"], "set")
        self.assertEqual(first["memory_writes"][0]["source"], f"{session_id}:{first_msg}")
        self.assertEqual(len(repo.rows[session_id]), 1)
        self.assertEqual(len(repo.facts), 1)
        self.assertEqual(repo.facts[0][2]["on_date"].isoformat(), "2026-10-15")

        same = await write(repo, "commit_turn", "C001", session_id,
                           {**base, "client_msg_id": second_msg}, "commit-2")
        self.assertEqual(same["memory_writes"], [])
        changed = await write(repo, "commit_turn", "C001", session_id,
                              {**base, "client_msg_id": str(uuid4()),
                               "customer_text": "Phòng anh 28 m²",
                               "facts": [{"key": "room_area_m2", "value": 28,
                                          "op": "set", "source_kind": "customer"}]},
                              "commit-3")
        self.assertEqual(changed["memory_writes"][0]["op"], "supersede")
        self.assertEqual(repo.statuses, [(repo.facts[0][0], "superseded")])
        self.assertEqual(len(repo.facts), 2)


if __name__ == "__main__":
    unittest.main()
