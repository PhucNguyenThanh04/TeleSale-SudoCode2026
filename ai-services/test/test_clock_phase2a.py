"""The injected clock stamps metadata; request.on still controls business dates."""

import json
import unittest
from datetime import datetime, timezone
from uuid import UUID

from langchain_core.messages import AIMessage

from app.agent.policy import prepare_tool_call
from app.agent.runtime import HarnessRuntime
from app.agent.state import Decision
from app.schemas.agent import TextTurnRequest
from fake_memory import InMemoryStore


FIXED_NOW = datetime(2031, 4, 5, 6, 7, 8, tzinfo=timezone.utc)


def fixed_clock():
    return FIXED_NOW


def turn():
    return TextTurnRequest(
        client_msg_id=UUID("11111111-1111-4111-8111-111111111111"),
        session_id=UUID("22222222-2222-4222-8222-222222222222"),
        channel="hotline", channel_identity="0984726714", on="2026-10-15",
        text="Chị gọi lại hỏi mẫu đã xem.", input_mode="clean",
    )


class ReplyModel:
    async def ainvoke(self, _messages):
        return AIMessage(content=json.dumps({"action": "respond",
                                             "response": "Dạ, em hỗ trợ mình ạ."}))


class ReturningCustomerTools:
    async def invoke(self, name, _args):
        if name == "crm.get_customer":
            return {"found": True, "customer_id": "C001", "phone": "0984726714",
                    "sessions": [{"session_id": "old-session", "channel": "hotline",
                                  "date": "2026-10-13", "summary": "Đã trao đổi mẫu máy lọc",
                                  "outcome": "khac"}]}
        return {"error": "unexpected_tool"}


class ClockInjectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_call_brief_uses_injected_real_time_clock(self):
        request = turn()
        runtime = HarnessRuntime(ReplyModel(), ReturningCustomerTools(), InMemoryStore(),
                                 clock=fixed_clock)
        response = await runtime.run(request)
        self.assertEqual(datetime.fromisoformat(response.call_brief["generated_at"]), FIXED_NOW)

    def test_handoff_metadata_uses_clock_and_quote_uses_request_day(self):
        request = turn()
        base = {"request": request, "customer_phone": "0984726714"}
        name, args = prepare_tool_call({
            **base, "decision": Decision(action="tool", tool_name="handoff.transfer",
                                          tool_args={"brief": {"escalation_reason": "need_help"}}),
        }, fixed_clock)
        self.assertEqual(name, "handoff.transfer")
        self.assertEqual(args["brief"]["generated_at"], FIXED_NOW.isoformat())

        name, args = prepare_tool_call({
            **base, "decision": Decision(action="tool", tool_name="pricing.get_quote",
                                          tool_args={"sku": "SKU-AP-X"}),
        }, fixed_clock)
        self.assertEqual(name, "pricing.get_quote")
        self.assertEqual(args["on"], "2026-10-15")


if __name__ == "__main__":
    unittest.main()
