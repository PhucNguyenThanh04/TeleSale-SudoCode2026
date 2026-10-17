"""Settings behavior without contacting Ollama Cloud."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.configs import Settings, get_settings
from app.mcp_servers.mcp_shared.config import database_url, mcp_token


class SettingsTest(unittest.TestCase):
    def test_loads_env_file_from_other_working_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True), tempfile.TemporaryDirectory() as cwd:
            previous = Path.cwd()
            try:
                os.chdir(cwd)
                settings = Settings()
            finally:
                os.chdir(previous)

        self.assertEqual(settings.llm_model, "gemma4:31b")
        self.assertEqual(str(settings.ollama_base_url), "https://ollama.com/")

    def test_process_environment_overrides_file(self) -> None:
        with patch.dict(os.environ, {"LLM_MODEL": "another-model", "PORT": "9001",
                                          "AGENT_GUARDRAILS_ENABLED": "false"}):
            settings = Settings()

        self.assertEqual(settings.llm_model, "another-model")
        self.assertEqual(settings.port, 9001)
        self.assertFalse(settings.agent_guardrails_enabled)

    def test_agent_selection_and_fact_extraction_modes_are_validated(self) -> None:
        settings = Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                            agent_kind="react", fact_extraction_mode="off")
        self.assertEqual(settings.agent_kind, "react")
        self.assertEqual(settings.fact_extraction_mode, "off")
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                     agent_kind="unknown")

    def test_invalid_or_missing_required_values_are_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

        for change in (
            {"PORT": "0"},
            {"OLLAMA_TIMEOUT_SECONDS": "0"},
            {"LLM_TEMPERATURE": "1.5"},
            {"LLM_MAX_TOKENS": "0"},
            {"AGENT_MAX_TOOL_CALLS": "2"},
            {"AGENT_PROMPT_HISTORY_TURNS": "0"},
            {"AGENT_PROMPT_HISTORY_TURNS": "13"},
            {"MEMORY_DB_POOL_MIN_SIZE": "6", "MEMORY_DB_POOL_MAX_SIZE": "5"},
            {"TIMEZONE": "not-a-time-zone"},
        ):
            with self.subTest(change=change), patch.dict(os.environ, change):
                with self.assertRaises(ValidationError):
                    Settings()

    def test_key_is_hidden_and_settings_are_cached(self) -> None:
        settings = Settings()
        key = settings.llm_api_key.get_secret_value()
        self.assertNotIn(key, repr(settings))
        self.assertIs(get_settings(), get_settings())

    def test_langfuse_requires_complete_credentials_when_enabled(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                     langfuse_enabled=True, langfuse_public_key="pk-lf-test")
        settings = Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                            langfuse_enabled=True, langfuse_public_key="pk-lf-test",
                            langfuse_secret_key="sk-lf-private",
                            langfuse_base_url="https://cloud.langfuse.com")
        self.assertNotIn("sk-lf-private", repr(settings))

    def test_raw_langfuse_content_is_limited_to_nonproduction(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                     app_env="production", langfuse_capture_content=True)

    def test_mcp_settings_use_role_secret_files_without_leaking_password(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            password_file = Path(temporary) / "password"
            token_file = Path(temporary) / "token"
            password_file.write_text("special@password", encoding="utf-8")
            token_file.write_text("local-token", encoding="utf-8")
            settings = Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                mcp_db_user="catalog", mcp_db_name="shop", mcp_db_host="postgres",
                mcp_db_password_file=password_file, mcp_internal_token_file=token_file,
                eval_catalog_database_url="postgresql+asyncpg://secret@localhost/eval")
            self.assertIn("special%40password", database_url(settings))
            self.assertEqual(mcp_token(settings), "local-token")
            self.assertNotIn("special@password", repr(settings))
            self.assertNotIn("secret@localhost", repr(settings))


if __name__ == "__main__":
    unittest.main()
