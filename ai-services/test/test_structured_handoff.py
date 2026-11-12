"""Handoff carries unresolved questions without resurrecting resolved ones."""

import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.agent.harness.handoff_brief import build_handoff_brief
from app.schemas.agent import TextTurnRequest


class StructuredHandoffTest(unittest.TestCase):
    def test_current_turn_resolution_is_reflected_in_handoff(self):
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0984726714", on=date(2026, 10, 15),
            text="Vấn đề giao cuối tuần đã giải quyết. Tôi muốn gặp nhân viên.",
            input_mode="clean")
        state = {"request": request, "safe_text": request.text,
            "identity_status": "known", "customer_id": "C17",
            "customer_phone": "0984726714", "profile": {}, "scoped_facts": {},
            "tool_calls": [], "current_episode": {"topics": [{"scope_type": "unknown",
                "scope_id": "", "items": [{"item_id": "issue-1", "kind": "question",
                    "text": "giao cuối tuần", "status": "open"}]}]}, "episodes": []}
        proposal = {"escalation_reason": "khach_yeu_cau_gap_nguoi",
            "episode_delta": {"topic_updates": [{"scope_type": "unknown", "scope_id": "",
                "resolve_items": [{"item_id": "issue-1",
                    "evidence_quote": "giao cuối tuần đã giải quyết"}]}]}}
        brief = build_handoff_brief(state, proposal,
            lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertNotIn("giao cuối tuần", " ".join(brief.open_questions))
        self.assertNotIn("handoff_episode_delta", state)

    def test_carries_only_open_question(self):
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel="hotline", channel_identity="0984726714", on=date(2026, 10, 15),
            text="Tôi muốn gặp nhân viên", input_mode="clean")
        state = {"request": request, "safe_text": request.text,
            "identity_status": "known", "customer_id": "C17",
            "customer_phone": "0984726714", "profile": {}, "scoped_facts": {},
            "tool_calls": [], "current_episode": {"topics": [{"scope_type": "unknown",
                "scope_id": "", "items": [
                    {"kind": "question", "text": "Lịch giao cuối tuần?", "status": "open"},
                    {"kind": "question", "text": "Có bảo hành?", "status": "resolved"}]}]},
            "episodes": []}
        brief = build_handoff_brief(state, {"escalation_reason": "khach_yeu_cau_gap_nguoi"},
            lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        self.assertIn("Lịch giao cuối tuần?", brief.open_questions)
        self.assertNotIn("Có bảo hành?", brief.open_questions)

    def test_k0_human_followup_keeps_the_immediately_unanswered_question(self):
        request = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
            channel='hotline', channel_identity='0984726714', on=date(2026, 10, 15),
            text='Chị muốn gặp nhân viên để hỏi kỹ hơn, em chuyển giúp chị nhé.', input_mode='clean')
        question = 'Chị đang uống kháng sinh, dùng máy thì có cho bé bú được không em?'
        state = {'request': request, 'safe_text': request.text, 'identity_status': 'known',
                 'customer_id': 'C17', 'customer_phone': '0984726714', 'profile': {},
                 'scoped_facts': {}, 'tool_calls': [], 'current_episode': {}, 'episodes': [],
                 'history': [{'customer': question,
                              'agent': 'Em không có thông tin chuyên môn để khẳng định. Chị nên hỏi bác sĩ.'}]}
        proposal = {'escalation_reason': 'khach_yeu_cau_gap_nguoi'}
        brief = build_handoff_brief(state, proposal, lambda: datetime.now(timezone.utc))
        self.assertIn(question, brief.open_questions)
        state['history'][0]['agent'] = ('Em không có chuyên môn y tế để khẳng định sữa có cho bé bú được không. '
                                       'Chị vui lòng tham khảo ý kiến bác sĩ kê đơn.')
        brief = build_handoff_brief(state, proposal, lambda: datetime.now(timezone.utc))
        self.assertIn(question, brief.open_questions)
        state['history'][0]['agent'] = 'Thông tin đã được giải đáp đầy đủ.'
        brief = build_handoff_brief(state, proposal, lambda: datetime.now(timezone.utc))
        self.assertNotIn(question, brief.open_questions)
