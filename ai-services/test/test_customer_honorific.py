
import json
import unittest

from app.agent.harness.context import prompt_context, prompt_messages
from test_deep_memory import turn


class CustomerHonorificTest(unittest.TestCase):
    def test_known_customer_honorific_reaches_prompt_without_call_brief(self):
        request = turn("Báo giá giúp chị")
        state = {"request": request, "safe_text": request.text, "identity_status": "known",
                 "customer_id": "C027", "customer_name": "Chi", "honorific": "chị",
                 "customer_phone": "0901234567", "call_brief": None}
        context = prompt_context(state, 6)
        metadata = json.loads(prompt_messages(context)[0].content)
        self.assertEqual(metadata.get("honorific"), "chị")
        self.assertNotIn("customer_phone", metadata)
        self.assertNotIn("customer_name", metadata)

    def test_unknown_or_ambiguous_identity_does_not_use_candidate_honorific(self):
        request = turn("Báo giá giúp tôi")
        for identity in ("unknown", "ambiguous"):
            state = {"request": request, "safe_text": request.text,
                     "identity_status": identity, "honorific": "chị"}
            self.assertIsNone(prompt_context(state, 6).get("honorific"))
