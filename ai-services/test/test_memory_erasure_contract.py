"""Contract for a customer's request to stop retaining their data."""

import unittest
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agent.guardrails.checks import check_answer
from app.schemas.brief import HandoffBrief
from app.agent.harness.runtime import DeepHarnessRuntime
from app.mcp_servers.mcp_memory.schemas import WriteInput
from memory_contract import check_snapshot, load_cases
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


CASES = {case["case"]: case for case in load_cases(
    Path(__file__).parent / "fixtures" / "memory_contract_v1.json")}


class MemoryErasureRequestContract(unittest.IsolatedAsyncioTestCase):
    def test_no_purge_action_exists_and_fact_delete_is_not_customer_purge(self):
        with self.assertRaises(ValidationError):
            WriteInput(action="delete_customer", customer_id="C107",
                       session_id=uuid4(), data={})
        single_fact = WriteInput(action="fact", customer_id="C107",
                                 session_id=uuid4(),
                                 data={"key": "blocker", "op": "delete",
                                       "source": "synthetic-test"})
        self.assertEqual(single_fact.action, "fact")

    def test_unverified_request_cannot_be_confirmed_as_completed(self):
        text = CASES["erase_request"]["calls"][0]["turns"][0]["text"]
        answer, reason = check_answer("Dạ, em đã xóa toàn bộ dữ liệu của anh rồi ạ.",
                                      [], text)
        self.assertIsNotNone(reason)
        self.assertNotIn("đã xóa", answer.casefold())

    async def test_verified_request_without_successful_tool_must_not_claim_completion(self):
        text = CASES["erase_request"]["calls"][1]["turns"][0]["text"]
        model = FakeToolModel(replies=[AIMessage(content=
            "Dạ, dữ liệu của chị đã được xóa hoàn toàn khỏi hệ thống.")])
        memory = FakeMemory()
        address = "72 Đường Thử Nghiệm, Hà Nội"
        memory.profile["delivery_address"] = {"key": "delivery_address",
                                              "value": address, "source_kind": "customer"}
        runtime = DeepHarnessRuntime(model, FakeGateway(customer_id="C107"), memory)
        request = turn(text).model_copy(update={"verified_customer_id": "C107",
                                        "verified_phone": "0900000107"})
        response = await runtime.run(request)
        expected = CASES["erase_request"]["calls"][1]["turns"][0]
        actual = {"customer_id": runtime.state_for(request).get("customer_id"),
                  "agent_text": response.agent_text}
        self.assertEqual(check_snapshot(expected["expected_after_turn"], actual), [])
        self.assertEqual(check_snapshot(expected["forbidden"], actual), [])
        self.assertNotIn("đã được xóa", response.agent_text.casefold())
        self.assertNotIn(address, response.agent_text)
        self.assertNotIn("delivery_address", runtime.state_for(request)["profile"])
        self.assertEqual(model.seen, [])

    async def test_unverified_request_routes_to_authorized_handler(self):
        text = CASES["erase_request"]["calls"][0]["turns"][0]["text"]

        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": False}
                if name == "handoff.transfer":
                    return {"ticket_id": "synthetic-ticket", "status": "queued"}
                return {"error": "unavailable"}

        gateway = Gateway()
        model = FakeToolModel(replies=[AIMessage(content=
            "Dạ, em sẽ chuyển yêu cầu của anh đến bộ phận phụ trách.")])
        runtime = DeepHarnessRuntime(model, gateway, FakeMemory())
        request = turn(text).model_copy(update={"channel_identity": "0900000108"})
        response = await runtime.run(request)
        expected = CASES["erase_request"]["calls"][0]["turns"][0]
        actual = {"customer_id": runtime.state_for(request).get("customer_id"),
                  "agent_text": response.agent_text}
        self.assertEqual(check_snapshot(expected["expected_after_turn"], actual), [])
        self.assertEqual(check_snapshot(expected["forbidden"], actual), [])
        self.assertIn("handoff.transfer", [name for name, _ in gateway.calls])
        self.assertTrue(response.needs_handoff)
        self.assertEqual(response.handoff_ticket_id, "synthetic-ticket")
        handoff = next(args["brief"] for name, args in gateway.calls
                       if name == "handoff.transfer")
        self.assertEqual(handoff["customer_phone"], "0900000108")
        self.assertEqual(handoff["escalation_reason"], "khac")
        HandoffBrief.model_validate(handoff)
        self.assertNotIn("0900000108", response.agent_text)

    async def test_request_without_trusted_phone_does_not_forge_handoff(self):
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                return {"found": False} if name == "crm.get_customer" else {"error": "unavailable"}

        gateway = Gateway()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), gateway, FakeMemory())
        request = turn("Xin gỡ toàn bộ hồ sơ cá nhân của tôi.").model_copy(update={
            "channel_identity": "unknown"})
        response = await runtime.run(request)
        self.assertFalse(response.needs_handoff)
        self.assertNotIn("handoff.transfer", [name for name, _ in gateway.calls])
        self.assertIn("xác minh", response.agent_text.casefold())

    async def test_failed_handoff_does_not_claim_request_was_queued(self):
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": True, "customer_id": "C107",
                            "phone": "0900000107", "orders": [], "sessions": []}
                return {"error": "tool_error"}

        gateway = Gateway()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), gateway, FakeMemory())
        request = turn("Tôi muốn xóa hết thông tin cá nhân đã lưu.").model_copy(update={
            "verified_customer_id": "C107", "verified_phone": "0900000107"})
        response = await runtime.run(request)
        self.assertIn("handoff.transfer", [name for name, _ in gateway.calls])
        self.assertFalse(response.needs_handoff)
        self.assertNotIn("đã chuyển", response.agent_text.casefold())
        self.assertNotIn("đã xóa", response.agent_text.casefold())

    async def test_ticket_without_queued_status_is_not_a_successful_handoff(self):
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": False}
                if name == "handoff.transfer":
                    return {"ticket_id": "synthetic-ticket", "status": "failed"}
                return {"error": "unavailable"}

        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), Gateway(), FakeMemory())
        request = turn("Đừng giữ dữ liệu của tôi nữa.").model_copy(update={
            "channel_identity": "0900000108"})
        response = await runtime.run(request)
        self.assertFalse(response.needs_handoff)
        self.assertIsNone(response.handoff_ticket_id)
        self.assertNotIn("đã chuyển", response.agent_text.casefold())

    def test_completion_claim_variants_blocked_but_pending_and_single_fact_are_allowed(self):
        for candidate in (
            "Hồ sơ cá nhân của anh đã được xóa hoàn toàn khỏi hệ thống.",
            "Thông tin của chị đã được gỡ hết rồi ạ.",
            "Em đã xử lý xong yêu cầu xóa dữ liệu của mình rồi ạ.",
            "Yêu cầu xóa dữ liệu đã được xử lý xong.",
            "Trước đây chưa xóa dữ liệu; giờ hồ sơ cá nhân của anh đã được xóa hết.",
            "Dữ liệu cá nhân của anh, em đã xóa hết rồi ạ.",
        ):
            with self.subTest(candidate=candidate):
                _, reason = check_answer(candidate, [], "Xin xóa thông tin của tôi")
                self.assertEqual(reason, "customer_erasure_unverified")
        for candidate in (
            "Dạ, em chưa xóa dữ liệu; em sẽ chuyển yêu cầu để xác minh.",
            "Dạ, em đã bỏ sở thích màu trắng khỏi ghi chú.",
        ):
            with self.subTest(candidate=candidate):
                _, reason = check_answer(candidate, [], "Xin xóa thông tin của tôi")
                self.assertIsNone(reason)

    async def test_deletion_claim_is_blocked_when_optional_answer_checks_are_off(self):
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[AIMessage(content=
            "Dữ liệu cá nhân của anh đã được xóa hoàn toàn.")]),
            FakeGateway(), FakeMemory(), guardrails_enabled=False)
        response = await runtime.run(turn("Xin hỏi thêm về sản phẩm."))
        self.assertNotIn("đã được xóa", response.agent_text.casefold())

    async def test_single_preference_removal_does_not_create_handoff(self):
        gateway = FakeGateway(customer_id="C107")
        model = FakeToolModel(replies=[AIMessage(content="Dạ, em ghi nhận ạ.")
                                       for _ in range(2)])
        runtime = DeepHarnessRuntime(model, gateway, FakeMemory())
        for text in ("Bỏ sở thích màu trắng của tôi nhé.",
                     "Xóa thông tin về màu yêu thích của tôi."):
            response = await runtime.run(turn(text))
            self.assertFalse(response.needs_handoff)
        self.assertNotIn("handoff.transfer", [name for name, _ in gateway.calls])

    async def test_plain_data_deletion_request_is_routed(self):
        class Gateway(FakeGateway):
            async def invoke(self, name, args):
                self.calls.append((name, args))
                if name == "crm.get_customer":
                    return {"found": False}
                if name == "handoff.transfer":
                    return {"ticket_id": "synthetic-ticket", "status": "queued"}
                return {"error": "unavailable"}

        gateway = Gateway()
        runtime = DeepHarnessRuntime(FakeToolModel(replies=[]), gateway, FakeMemory())
        for text in ("Xóa dữ liệu giúp tôi.",
                     "Xóa toàn bộ thông tin cá nhân, gồm cả màu yêu thích.",
                     "Xóa dữ liệu cá nhân và sở thích màu trắng của tôi.",
                     "Xóa hồ sơ của tôi nhé, cả màu yêu thích nữa.",
                     "Xóa thông tin cá nhân của tôi, cả thông tin về màu yêu thích.",
                     "Xóa thông tin về màu yêu thích và xóa hồ sơ cá nhân của tôi."):
            request = turn(text).model_copy(update={"channel_identity": "0900000108"})
            response = await runtime.run(request)
            self.assertTrue(response.needs_handoff)
        self.assertIn("handoff.transfer", [name for name, _ in gateway.calls])
