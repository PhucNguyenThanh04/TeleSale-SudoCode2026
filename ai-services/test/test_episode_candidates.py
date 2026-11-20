
import unittest

from app.agent.memory.episode_candidates import outcome_from_tool_calls


class EpisodeCandidateTest(unittest.TestCase):

    def test_outcome_uses_successful_business_tool_only(self):
        self.assertEqual(outcome_from_tool_calls([
            {"name": "order.create", "result": {"error": "out_of_stock"}}]), "khac")
        self.assertEqual(outcome_from_tool_calls([
            {"name": "schedule.callback", "result": {"callback_id": "CB42"}}]),
                         "hen_goi_lai")
        self.assertEqual(outcome_from_tool_calls([
            {"name": "order.create", "result": {"status": "created", "order_id": "O42"}}]),
                         "chot_don")
