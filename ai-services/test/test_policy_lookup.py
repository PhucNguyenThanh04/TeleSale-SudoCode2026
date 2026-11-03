"""Policy grounding and trusted dates remain required while retrieval is unavailable."""

import unittest
from datetime import date

from app.agent.guardrails.checks import check_answer
from app.agent.harness.policy import prepare_tool_call
from app.agent.harness.state import Decision
from app.schemas.agent import TextTurnRequest
from uuid import uuid4


class PolicyLookupTest(unittest.TestCase):
    def test_harness_supplies_business_date_and_ignores_model_order_date(self):
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0123456789", on=date(2026, 10, 15),
            text="Chính sách đổi trả?", input_mode="clean")
        state = {"request": request, "decision": Decision(action="tool",
            tool_name="policy.search", tool_args={"query": "đổi trả", "order_date": "2020-01-01"}),
            "tool_calls": []}
        self.assertEqual(prepare_tool_call(state, lambda: None),
                         ("policy.search", {"query": "đổi trả", "on": "2026-10-15"}))

    def test_answer_rejects_old_policy_and_accepts_evidenced_current_window(self):
        calls = [{"name": "policy.search", "args": {"query": "đổi trả", "on": "2026-10-15"},
                  "result": {"evidence": [{"chunk_id": "DT-01",
                                          "content": "Đổi trả trong vòng 7 ngày."}]}}]
        self.assertEqual(check_answer("Chính sách đổi trả trong 7 ngày.", calls)[1], None)
        self.assertIsNotNone(check_answer("Chính sách đổi trả trong 14 ngày.", calls)[1])
        self.assertIsNotNone(check_answer("Chính sách đổi trả trong 7 ngày.", [])[1])

    def test_policy_fee_follow_up_uses_verified_policy_without_authorizing_sale_price(self):
        calls = [{"name": "policy.search", "args": {"query": "đổi size", "on": "2026-10-15"},
                  "result": {"evidence": [{"chunk_id": "DT-03", "content":
                      "Từ lần đổi thứ hai, khách chịu phí vận chuyển 30.000đ/chiều."}]}}]
        question = "Nếu đổi size lần thứ hai thì phí thế nào?"
        answer = "Dạ, từ lần thứ hai, phí vận chuyển là 30.000đ mỗi chiều ạ."
        self.assertEqual(check_answer(answer, calls, question), (answer, None))
        self.assertEqual(check_answer(answer, [], question)[1],
                         "unsupported_policy_or_internal_claim")
        self.assertEqual(check_answer("Dạ, phí vận chuyển là 40.000đ/chiều ạ.",
                                      calls, question)[1], "price_without_quote")
        self.assertEqual(check_answer("Dạ, mẫu này giá 30.000đ ạ.", calls, question)[1],
                         "price_without_quote")

    def test_another_policy_fee_wording_and_non_policy_price_control(self):
        calls = [{"name": "policy.search", "args": {"query": "phí vận chuyển", "on": "2026-10-15"},
                  "result": {"evidence": [{"chunk_id": "VC-02", "content":
                      "Các ngành khác: 25.000đ nội thành, 35.000đ liên tỉnh."}]}}]
        answer = "Dạ, phí giao liên tỉnh là 35.000đ ạ."
        self.assertEqual(check_answer(answer, calls, "Chính sách ship liên tỉnh?"),
                         (answer, None))
        self.assertEqual(check_answer("Dạ, mẫu này giá 35.000đ ạ.", calls,
                                      "Chính sách ship liên tỉnh?")[1], "price_without_quote")


if __name__ == "__main__":
    unittest.main()
