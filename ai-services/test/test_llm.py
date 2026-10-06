"""Check model construction without calling Ollama Cloud."""

import os
import unittest
from unittest.mock import patch

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.configs import Settings
from app.infarstructure.llm import build_llm


class BuildLLMTest(unittest.TestCase):
    def test_builds_cloud_chat_model_from_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_API_KEY": "test-key",
                "LLM_MODEL": "gemma4:31b",
                "OLLAMA_BASE_URL": "https://ollama.com",
                "OLLAMA_TIMEOUT_SECONDS": "12",
                "LLM_TEMPERATURE": "0.3",
                "LLM_MAX_TOKENS": "180",
            },
        ):
            llm = build_llm(Settings())

        self.assertIsInstance(llm, BaseChatModel)
        self.assertIsInstance(llm, ChatOllama)
        self.assertEqual(llm.model, "gemma4:31b")
        self.assertEqual(llm.temperature, 0.3)
        self.assertEqual(llm.num_predict, 180)
        self.assertNotIn("test-key", repr(llm))
        request = httpx.Request("POST", "https://ollama.com/api/chat")
        authenticated = next(llm.client_kwargs["auth"].auth_flow(request))
        self.assertEqual(authenticated.headers["Authorization"], "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
