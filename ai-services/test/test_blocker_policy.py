"""Blocker evidence and resolution remain available to LangMem episodes."""

import unittest

from app.agent.guardrails.checks import FactRejectReason, fact_evidence
from app.agent.memory.decision_makers import BlockerResolutionReason, roles_mentioned
from app.agent.memory.episode_candidates import blocker_resolution
from app.constants import Slot


class BlockerPolicyTests(unittest.TestCase):
    def test_preferences_and_delivery_constraints_are_rejected(self):
        self.assertEqual(fact_evidence(Slot.BLOCKER, "màu đỏ", "set",
                                       "Tôi không thích màu đỏ.", []).reason,
                         FactRejectReason.PREFERENCE_NOT_BLOCKER)
        self.assertEqual(fact_evidence(Slot.BLOCKER, "giao buổi sáng", "set",
                                       "Tôi không thích giao buổi sáng.", []).reason,
                         FactRejectReason.DELIVERY_CONSTRAINT_NOT_BLOCKER)

    def test_matching_decision_maker_can_resolve_blocker(self):
        self.assertEqual(blocker_resolution("Vợ anh đồng ý rồi", {
            "blocker": {"value": "cần hỏi vợ"}}),
            (True, BlockerResolutionReason.DECISION_MAKER_APPROVED))
        self.assertEqual(blocker_resolution("Mẹ anh đồng ý rồi", {
            "blocker": {"value": "cần hỏi vợ"}}),
            (False, BlockerResolutionReason.DIFFERENT_DECISION_MAKER))

    def test_role_aliases_remain_distinct(self):
        self.assertEqual(roles_mentioned("can hoi vo va me"), {"wife", "parents"})
