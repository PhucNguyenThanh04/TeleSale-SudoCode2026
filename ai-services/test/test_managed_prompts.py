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


def test_prompt_manifest_and_dry_run_are_offline_and_use_both_local_contracts(capsys):
    from app.agent.prompts import MEMORY_PROMPT
    from scripts import publish_langfuse_prompts as publisher
    from app.agent.implementations.business_agent import _SYSTEM_PROMPT
    from app.agent.memory.langmem_extractor import _INSTRUCTIONS
    manifest=publisher.prompt_manifest()
    assert manifest=={SALES_PROMPT:_SYSTEM_PROMPT,MEMORY_PROMPT:_INSTRUCTIONS}
    assert 'presented_offer' in manifest[SALES_PROMPT] and 'accepted_offer' in manifest[SALES_PROMPT]
    assert 'advice_given' in manifest[MEMORY_PROMPT] and 'consent' in manifest[MEMORY_PROMPT]
    with patch.object(publisher,'_client',side_effect=AssertionError('no external API')):
        publisher.main(['--dry-run'])
    output=capsys.readouterr().out
    for name,content in manifest.items():
        import hashlib
        assert name in output and hashlib.sha256(content.encode()).hexdigest() in output
        assert content in output


def test_local_and_equivalent_managed_content_for_sales_and_memory():
    from scripts.publish_langfuse_prompts import prompt_manifest
    for name,content in prompt_manifest().items():
        with patch('app.agent.prompts.get_settings') as settings,patch('app.agent.prompts._client') as client:
            settings.return_value.langfuse_prompts_enabled=False
            assert text_prompt(name,content)==content
            settings.return_value.langfuse_prompts_enabled=True
            client.return_value.get_prompt.return_value.compile.return_value=content
            assert text_prompt(name,content)==content
            client.return_value.get_prompt.side_effect=OSError('offline')
            assert text_prompt(name,content)==content


def test_followup_prompt_contract_reuses_prepared_tools_and_keeps_btc_price_rules():
    from scripts.publish_langfuse_prompts import prompt_manifest
    from app.agent.prompts import SALES_PROMPT
    content = prompt_manifest()[SALES_PROMPT]
    assert 'tool_observations' in content
    assert 'cân nhắc thêm' in content
    assert 'Không so giá' in content and 'giá đối thủ' in content
    assert 'không đủ điều kiện' in content and 'không cộng dồn' in content
    assert 'không thấy mã' in content
