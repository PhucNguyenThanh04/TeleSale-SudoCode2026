"""Phase 1 observations from public inputs, with an entirely scripted model."""

import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import AIMessage

from app.agent.guardrails import _money_claims
from app.agent.runtime import HarnessRuntime
from app.schemas.agent import TextTurnRequest
from fake_memory import InMemoryStore


SAMPLES = Path(__file__).resolve().parents[3] / "BTC-Data-Vong1-TEAMS/test_set/public_sample"
ASK_MODEL = {"action": "respond", "response": "Dạ, anh/chị muốn xem mẫu nào ạ?"}


class ScriptedModel:
    def __init__(self, decision=ASK_MODEL):
        self.decision = decision

    async def ainvoke(self, _messages):
        return AIMessage(content=json.dumps(self.decision, ensure_ascii=False))


class SequenceModel:
    def __init__(self, *decisions):
        self.decisions = list(decisions)

    async def ainvoke(self, _messages):
        return AIMessage(content=json.dumps(self.decisions.pop(0), ensure_ascii=False))


class ScriptedTools:
    def __init__(self):
        self.calls = []

    async def invoke(self, name, args):
        self.calls.append({"name": name, "args": dict(args)})
        if name == "crm.get_customer":
            return {"found": False}
        if name == "catalog.search":
            return {"items": [], "total": 0}
        return {"error": "unexpected_tool"}


class PublicSampleCharacterization(unittest.IsolatedAsyncioTestCase):
    async def test_all_public_sample_turns_keep_observed_tools_and_memory(self):
        # Golden search arguments expose the current phrasing-sensitive behavior.
        catalog_queries = {
            ("SAMPLE-01", "call_1", 3): "Máy này có gì",
            ("SAMPLE-01", "call_2", 2): "Ông xã chị đồng ý rồi vẫn như hôm trước đúng không",
            ("SAMPLE-02", "call_1", 1): "Máy lọc không khí AirPure X bên em",
            ("SAMPLE-03", "call_1", 2): "có gì",
            ("SAMPLE-04", "call_1", 1): "shop oi Giày chạy bộ RunLite 2 Pro gia bn v",
            ("SAMPLE-04", "call_2", 2): "Bên Facebook báo chị 1521k đúng không Còn không",
            ("SAMPLE-05", "call_1", 1): "AirPure X đang 500k đúng không",
            ("SAMPLE-05", "call_2", 1): "Chị gọi lại lấy cái AirPure X 500k hôm trước",
            ("SAMPLE-05", "call_2", 2): "Sao hôm trước em bảo 500k mà",
            ("SAMPLE-06", "call_1", 1): "Alo máy lọc không khí Xiaomi 4 Pro",
        }
        observed_turns = 0
        for path in sorted(SAMPLES.glob("SAMPLE-*.json")):
            sample = json.loads(path.read_text())
            scenario_id = sample["scenario_id"]
            memory = InMemoryStore()
            for call_name, call in sample["calls"].items():
                session_id = uuid5(NAMESPACE_URL, f"{scenario_id}:{call_name}")
                on = date(2026, 10, 15) + timedelta(days=call.get("days_later", 0))
                for number, customer_text in enumerate(call["customer_turns"], 1):
                    observed_turns += 1
                    with self.subTest(scenario=scenario_id, call=call_name, turn=number):
                        turn = TextTurnRequest(
                            client_msg_id=uuid5(NAMESPACE_URL,
                                                f"{scenario_id}:{call_name}:{number}"),
                            session_id=session_id, channel="hotline",
                            channel_identity=sample["customer_phone"], on=on,
                            text=customer_text, input_mode="clean",
                        )
                        tools = ScriptedTools()
                        runtime = HarnessRuntime(ScriptedModel(), tools, memory)
                        response = await runtime.run(turn)
                        state = runtime.state_for(turn)
                        expected = [{"name": "crm.get_customer",
                                     "args": {"phone": sample["customer_phone"]}}]
                        query = catalog_queries.get((scenario_id, call_name, number))
                        if query is not None:
                            expected.append({"name": "catalog.search", "args": {"query": query}})
                        self.assertEqual(tools.calls, expected)
                        self.assertEqual([{"name": item["name"], "args": item["args"]}
                                          for item in state["tool_calls"]], expected)
                        self.assertEqual(response.agent_text, ASK_MODEL["response"])
                        self.assertTrue(response.agent_text.endswith("?"))
                        self.assertEqual(_money_claims(response.agent_text), [])
                        self.assertEqual(state["memory_writes"], [])
                        self.assertEqual(len(memory.sessions[str(session_id)]), number)
        self.assertEqual(observed_turns, 39)

    async def test_sample_02_price_claim_keeps_quote_and_trace_observations(self):
        sample = json.loads((SAMPLES / "SAMPLE-02.json").read_text())
        turn = TextTurnRequest(
            client_msg_id=uuid5(NAMESPACE_URL, "SAMPLE-02:quoted-turn"),
            session_id=uuid5(NAMESPACE_URL, "SAMPLE-02:quoted-call"),
            channel="hotline", channel_identity=sample["customer_phone"],
            on="2026-10-15", text=sample["calls"]["call_1"]["customer_turns"][0],
            input_mode="clean",
        )
        model = SequenceModel(
            {"action": "tool", "tool_name": "catalog.search",
             "tool_args": {"query": "AirPure X"}},
            {"action": "tool", "tool_name": "pricing.get_quote",
             "tool_args": {"sku": "SKU-AP-X"}},
            {"action": "respond", "response": "Dạ, AirPure X giá 4.890.000đ ạ."},
        )

        class PriceTools(ScriptedTools):
            async def invoke(self, name, args):
                if name == "catalog.search":
                    self.calls.append({"name": name, "args": dict(args)})
                    return {"items": [{"sku": "SKU-AP-X", "name": "AirPure X",
                                       "category": "may-loc-khong-khi"}], "total": 1}
                if name == "pricing.get_quote":
                    self.calls.append({"name": name, "args": dict(args)})
                    return {"sku": "SKU-AP-X", "list_price_vnd": 4_890_000,
                            "final_price_vnd": 4_890_000, "applied_promos": [],
                            "freeship": True}
                return await super().invoke(name, args)

        tools = PriceTools()
        runtime = HarnessRuntime(model, tools, InMemoryStore())
        response = await runtime.run(turn)
        state = runtime.state_for(turn)
        self.assertEqual([(call["name"], call["args"]) for call in state["tool_calls"]],
                         [("crm.get_customer", {"phone": sample["customer_phone"]}),
                          ("catalog.search", {"query": "AirPure X"}),
                          ("pricing.get_quote", {"sku": "SKU-AP-X", "on": "2026-10-15"})])
        self.assertEqual(response.agent_text, "Dạ, AirPure X giá 4.890.000đ ạ.")
        self.assertNotIn("?", response.agent_text)
        self.assertEqual(_money_claims(response.agent_text), [(4_890_000, "price", False)])
        self.assertEqual(state["memory_writes"], [])

if __name__ == "__main__":
    unittest.main()
