"""Explicit, independent identity boundary contract cases."""

import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from unittest.mock import AsyncMock
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agent.harness.runtime import DeepHarnessRuntime
from app.mcp_servers.mcp_memory.services.memory import read, write
from memory_contract import check_snapshot, load_cases
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn
from test_mcp_memory import TurnRepo


class ContractToolModel(FakeToolModel):
    turn_replies: list[AIMessage] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "MEMORY_FACT_EXTRACTION" in str(messages):
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self.seen.append(str(messages))
        reply = self.replies.pop(0)
        self.turn_replies.append(reply)
        return ChatResult(generations=[ChatGeneration(message=reply)])


class ContractMemory(FakeMemory):
    def __init__(self, model: ContractToolModel | None = None):
        super().__init__()
        self.model = model

    async def commit_turn(self, session_id, customer_id, customer_text, agent_text,
                          on, channel, client_msg_id, facts=None, orders=None,
                          episode_delta=None, outcome="khac", tool_observations=None):
        return await super().commit_turn(
            session_id, customer_id, customer_text, agent_text, on, channel,
            client_msg_id, facts=facts, orders=orders, episode_delta=episode_delta,
            outcome=outcome, tool_observations=tool_observations)


CASES = {case["case"]: case for case in load_cases(
    Path(__file__).parent / "fixtures" / "memory_contract_v1.json")}


class MemoryIdentityContract(unittest.IsolatedAsyncioTestCase):
    async def test_shared_number_exposes_neither_candidate(self):
        case = CASES["shared_phone"]

        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "crm.get_customer":
                    return {"found": True, "ambiguous": True, "candidates": [
                        {"customer_id": "C102", "name": "A", "sessions": [
                            {"session_id": "a", "channel": "hotline", "date": "2026-10-14",
                             "summary": "quạt DC1", "outcome": "khac"}]},
                        {"customer_id": "C103", "name": "B", "sessions": [
                            {"session_id": "b", "channel": "hotline", "date": "2026-10-14",
                             "summary": "đơn của C103", "outcome": "khac"}]}]}
                return {"error": "unavailable"}

        class Memory(FakeMemory):
            async def read_context(self, session_id, customer_id):
                self.asserted_customer_id = customer_id
                return {"history": [], "profile": {}, "episodes": [],
                        "owned_order_ids": []}

        memory = Memory()
        model = FakeToolModel(replies=[AIMessage(content="Dạ, em nghe ạ."),
                                       AIMessage(content="Dạ, mình nói tiếp về quạt ạ.")])
        runtime = DeepHarnessRuntime(model, Gateway(), memory)
        request = turn(case["calls"][0]["turns"][0]["text"]).model_copy(update={
            "channel_identity": "0912283456"})
        response = await runtime.run(request)
        state = runtime.state_for(request)
        actual = {"identity_status": state["identity_status"],
                  "customer_id": state.get("customer_id"),
                  "profile": state.get("profile"), "episodes": state.get("episodes"),
                  "call_brief": response.call_brief, "agent_text": response.agent_text}
        self.assertEqual(check_snapshot(case["calls"][0]["turns"][0]
                                         ["expected_after_turn"], actual), [])
        self.assertEqual(memory.asserted_customer_id, None)
        self.assertNotIn("quạt DC1", model.seen[0])
        self.assertNotIn("đơn của C103", model.seen[0])
        verified = turn(case["calls"][1]["turns"][0]["text"]).model_copy(update={
            "channel_identity": "0912283456", "verified_customer_id": "C102",
            "verified_phone": "0912283456", "on": date(2026, 10, 16)})
        verified_response = await runtime.run(verified)
        verified_actual = {"customer_id": runtime.state_for(verified)["customer_id"],
                           "agent_text": verified_response.agent_text}
        self.assertEqual(check_snapshot(case["calls"][1]["turns"][0]
                                         ["expected_after_turn"], verified_actual), [])
        self.assertEqual(check_snapshot(case["calls"][1]["turns"][0]
                                         ["forbidden"], verified_actual), [])

    async def test_fanpage_to_hotline_loads_same_customer_fact(self):
        case = CASES["cross_channel"]

        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                if name == "crm.get_customer":
                    if args.get("fb_id") == "fb.other.104":
                        return {"found": False}
                    return {"found": True, "customer_id": "C104",
                            "phone": "0934567812", "orders": [], "sessions": []}
                return {"error": "unavailable"}

        model = ContractToolModel(replies=[
            AIMessage(content='Dạ, em ghi nhận ạ.'),
            AIMessage(content="Dạ, em tư vấn tiếp ạ."),
            AIMessage(content="Dạ, em nghe ạ.")])
        memory = ContractMemory(model)
        runtime = DeepHarnessRuntime(model, Gateway(), memory)
        first = turn(case["calls"][0]["turns"][0]["text"]).model_copy(update={
            "channel": "chat_fanpage", "channel_identity": "fb.synthetic.104"})
        await runtime.run(first)
        # Facts are admitted by the asynchronous worker, never by JSON embedded
        # in the sales reply. Exercise its real evidence boundary before projecting
        # the completed result into this identity test's in-memory store.
        from app.schemas.langmem import ProfileFactCandidate
        from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
        sid, tid = str(first.session_id), str(first.client_msg_id)
        accepted, rejected = admit_profile_candidates('C104', sid, [ProfileFactCandidate(
            key='room_area_m2', value=12, source_kind='customer', source_turn_id=tid,
            evidence_quote='Phòng tôi 12 m²', observed_on=first.on)],
            [{'turn_id': tid, 'customer_id': 'C104', 'session_id': sid,
              'customer_text': first.text, 'agent_text': 'Dạ, em ghi nhận ạ.'}], [])
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        memory.profile.update({fact['key']: {**fact, 'status': 'active',
            'source': f'langmem:{sid}:{tid}'} for fact in accepted})
        first_actual = {"customer_id": runtime.state_for(first).get("customer_id"),
                        "profile": memory.profile}
        self.assertEqual(check_snapshot(case["calls"][0]["turns"][0]
                                         ["expected_after_turn"], first_actual), [])
        second = turn(case["calls"][1]["turns"][0]["text"]).model_copy(update={
            "channel": "hotline", "channel_identity": "0934567812",
            "on": date(2026, 10, 17)})
        response = await runtime.run(second)
        state = runtime.state_for(second)
        actual = {"customer_id": state.get("customer_id"),
                  "profile": state.get("profile"), "agent_text": response.agent_text}
        self.assertEqual(check_snapshot(case["calls"][1]["turns"][0]
                                         ["expected_after_turn"], actual), [])
        self.assertEqual(check_snapshot(case["calls"][1]["turns"][0]
                                         ["forbidden"], actual), [])
        other = turn("Tôi cũng muốn hỏi máy lọc.").model_copy(update={
            "channel": "chat_fanpage", "channel_identity": "fb.other.104"})
        await runtime.run(other)
        self.assertIsNone(runtime.state_for(other).get("customer_id"))
        self.assertEqual(runtime.state_for(other).get("profile"), {})
        self.assertIn('"customer_facts": {}', model.seen[2])

    async def test_late_verification_keeps_prior_turn_anonymous(self):
        class Repo(TurnRepo):
            def __init__(self):
                super().__init__()
                self.enqueue_distillation = AsyncMock()
                self.link_order = AsyncMock()

            async def attribute_anonymous_turns(self, _conn, _session_id, _customer_id):
                return []

            async def recent_turns(self, _conn, session_id, maximum):
                return (await self.customer_turns(_conn, session_id, "C102"))[-maximum:]

            async def order_links(self, *_):
                return []

        class Projection:
            async def list_fact_versions(self, _customer_id):
                return []

            async def list_episode_versions(self, _customer_id):
                return []

        repo = Repo()
        session_id = str(uuid4())
        for customer_id, text in ((None, "Tôi đang hỏi cho phòng 12 m²"),
                                  ("C102", "Tôi xác nhận mình cần quạt DC1")):
            await write(repo, "commit_turn", customer_id, session_id, {
                "customer_text": text, "agent_text": "Dạ", "on": "2026-10-15",
                "channel": "hotline", "client_msg_id": str(uuid4())})
        result = await read(repo, "C102", session_id, projector=Projection())
        self.assertEqual([item["customer"] for item in result["history"]],
                         ["Tôi xác nhận mình cần quạt DC1"])
        self.assertEqual(repo.enqueue_distillation.await_count, 1)
        self.assertIsNone(repo.rows[session_id][0]["customer_id"])
