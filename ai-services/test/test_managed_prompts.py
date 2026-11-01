"""Prompt management preserves shipped behavior and uses labeled releases."""

import unittest
from unittest.mock import patch

from app.agent.prompts import SALES_PROMPT, text_prompt


class ManagedPromptTests(unittest.TestCase):
    @patch("app.agent.prompts.get_settings")
    def test_disabled_returns_local_prompt(self, settings):
        settings.return_value.langfuse_prompts_enabled = False
        self.assertEqual(text_prompt(SALES_PROMPT, "local"), "local")

    @patch("app.agent.prompts._client")
    @patch("app.agent.prompts.get_settings")
    def test_fetches_production_text(self, settings, client):
        settings.return_value.langfuse_prompts_enabled = True
        client.return_value.get_prompt.return_value.compile.return_value = "managed"
        self.assertEqual(text_prompt(SALES_PROMPT, "local"), "managed")
        client.return_value.get_prompt.assert_called_once_with(
            SALES_PROMPT, type="text", label="production", fallback="local",
            fetch_timeout_seconds=2, max_retries=0)

    @patch("app.agent.prompts._client")
    @patch("app.agent.prompts.get_settings")
    def test_fetch_failure_uses_local_prompt(self, settings, client):
        settings.return_value.langfuse_prompts_enabled = True
        client.return_value.get_prompt.side_effect = OSError("offline")
        self.assertEqual(text_prompt(SALES_PROMPT, "local"), "local")
