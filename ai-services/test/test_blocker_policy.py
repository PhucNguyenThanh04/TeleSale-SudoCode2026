
import unittest

from app.agent.guardrails.checks import FactRejectReason, fact_evidence
from app.agent.memory.decision_makers import roles_mentioned
from app.constants import Slot


class BlockerPolicyTests(unittest.TestCase):


    def test_role_aliases_remain_distinct(self):
        self.assertEqual(roles_mentioned("can hoi vo va me"), {"wife", "parents"})
