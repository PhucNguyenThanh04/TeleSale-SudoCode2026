
import unittest
from uuid import uuid4

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agent.guardrails.checks import check_answer
from app.agent.harness.runtime import DeepHarnessRuntime
from app.mcp_servers.mcp_memory.schemas import WriteInput
from test_deep_memory import FakeGateway, FakeMemory, FakeToolModel, turn


class MemoryErasureRequestContract(unittest.IsolatedAsyncioTestCase):
    def test_no_purge_or_legacy_fact_action_exists(self):
        with self.assertRaises(ValidationError):
            WriteInput(action="delete_customer", customer_id="C107",
                       session_id=uuid4(), data={})
        with self.assertRaises(ValidationError):
            WriteInput(action="fact", customer_id="C107", session_id=uuid4(),
                       data={"key": "blocker", "op": "delete",
                             "source": "synthetic-test"})







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

    async def test_unsupported_purge_claim_requires_model_repair_with_optional_checks_off(self):
        reply='Em cần chuyển yêu cầu đến bộ phận phụ trách để xác minh phạm vi xử lý.'
        model=FakeToolModel(replies=[AIMessage(content='Dữ liệu cá nhân của anh đã được xóa hoàn toàn.'),
            AIMessage(content=reply)])
        runtime=DeepHarnessRuntime(model,FakeGateway(),FakeMemory(),guardrails_enabled=False)
        try:
            response=await runtime.run(turn('Tôi cần xác minh việc xử lý hồ sơ.'))
            self.assertEqual(response.agent_text,reply)
            self.assertEqual(len(model.seen),2)
        finally:
            await runtime.close()

    async def test_model_failure_does_not_trigger_coded_erasure_reply_or_handoff(self):
        gateway=FakeGateway()
        runtime=DeepHarnessRuntime(FakeToolModel(replies=[]),gateway,FakeMemory())
        try:
            with self.assertRaisesRegex(RuntimeError,'agent_reply_unavailable'):
                await runtime.run(turn('Tôi yêu cầu xóa dữ liệu cá nhân.'))
            self.assertNotIn('handoff.transfer',[name for name,_ in gateway.calls])
        finally:
            await runtime.close()
