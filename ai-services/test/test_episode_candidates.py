"""Model episode updates are proposals, not trusted memory writes."""

import unittest

from app.agent.memory.episode_candidates import accepted_episode_delta, outcome_from_tool_calls


class EpisodeCandidateTest(unittest.TestCase):
    def test_rejects_unrelated_quote_for_invented_blocker(self):
        proposal = {"topic_updates": [{"scope_type": "unknown", "scope_id": "",
            "add_items": [{"kind": "blocker", "text": "Customer cannot afford it",
                           "evidence_quote": "Yes"}]}]}
        self.assertEqual(accepted_episode_delta("Yes, I want to purchase it.", "Okay",
                                                proposal, {}, []), {})

    def test_outcome_uses_successful_business_tool_only(self):
        self.assertEqual(outcome_from_tool_calls([
            {"name": "order.create", "result": {"error": "out_of_stock"}}]), "khac")
        self.assertEqual(outcome_from_tool_calls([
            {"name": "schedule.callback", "result": {"callback_id": "CB42"}}]),
                         "hen_goi_lai")
        self.assertEqual(outcome_from_tool_calls([
            {"name": "order.create", "result": {"status": "created", "order_id": "O42"}}]),
                         "chot_don")

    def test_accepts_evidenced_product_question(self):
        proposal = {"topic_updates": [{"scope_type": "product", "scope_id": "SKU-GAMMA",
            "add_items": [{"kind": "question", "text": "Bảo hành bao lâu?",
                           "evidence_quote": "SKU-GAMMA bảo hành bao lâu?"}]}]}
        result = accepted_episode_delta("SKU-GAMMA bảo hành bao lâu?", "Để em tra cứu.",
                                        proposal, {}, [])
        self.assertEqual(result["topic_updates"][0]["add_items"][0]["kind"], "question")

    def test_rejects_wrong_product_and_fabricated_evidence(self):
        proposal = {"topic_updates": [{"scope_type": "product", "scope_id": "SKU-BETA",
            "add_items": [{"kind": "blocker", "text": "Cần hỏi người thân",
                           "evidence_quote": "Cần hỏi người thân"}]}]}
        self.assertEqual(accepted_episode_delta("Tôi mua SKU-GAMMA", "Dạ", proposal, {}, []),
                         {})

    def test_can_resolve_known_question_with_evidence(self):
        current = {"topics": [{"scope_type": "unknown", "scope_id": "", "items": [
            {"item_id": "issue-1", "kind": "question", "text": "Có giao cuối tuần?",
             "status": "open"}]}]}
        proposal = {"topic_updates": [{"scope_type": "unknown", "scope_id": "",
            "resolve_items": [{"item_id": "issue-1", "evidence_quote": "Có giao cuối tuần"}]}]}
        result = accepted_episode_delta("Vậy có giao cuối tuần không?",
                                        "Có giao cuối tuần ạ.", proposal, current, [])
        self.assertEqual(result["topic_updates"][0]["resolve_items"][0]["item_id"],
                         "issue-1")

    def test_can_resolve_prior_session_question_with_evidence(self):
        prior = [{"topics": [{"scope_type": "unknown", "scope_id": "", "items": [
            {"item_id": "prior-1", "kind": "question", "text": "Có giao cuối tuần?",
             "status": "open"}]}]}]
        proposal = {"topic_updates": [{"scope_type": "unknown", "scope_id": "",
            "resolve_items": [{"item_id": "prior-1", "evidence_quote": "Có giao cuối tuần"}]}]}
        accepted = accepted_episode_delta("Vậy có giao cuối tuần không?",
            "Có giao cuối tuần ạ.", proposal, {}, [], prior_episodes=prior)
        self.assertEqual(accepted["topic_updates"][0]["resolve_items"][0]["item_id"],
                         "prior-1")
