"""Check OpenAI-compatible requests without contacting a live model."""

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx2 as httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.configs import Settings
from app.infarstructure.llm import build_llm


class BuildLLMTest(unittest.TestCase):
    def test_builds_cloud_chat_model_from_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_API_KEY": "test-key",
                "LLM_MODEL": "gpt-6-luna",
                "LLM_BASE_URL": "https://llm.example/v1",
                "LLM_TIMEOUT_SECONDS": "12",
                "LLM_TEMPERATURE": "0.3",
                "LLM_MAX_TOKENS": "180",
            },
        ):
            llm = build_llm(Settings(_env_file=None))

        self.assertIsInstance(llm, BaseChatModel)
        self.assertIsInstance(llm, ChatOpenAI)
        self.assertEqual(llm.model_name, "gpt-6-luna")
        self.assertEqual(llm.temperature, 0.3)
        self.assertEqual(llm.max_tokens, 180)
        self.assertEqual(llm.request_timeout, 12)
        self.assertNotIn("test-key", repr(llm))

        requests = []

        def send(client, request, **kwargs):
            requests.append(request)
            return httpx.Response(200, request=request, json={
                "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
                "model": "gpt-6-luna", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": None, "tool_calls": [{
                        "id": "call-stock", "type": "function", "function": {
                            "name": "check_stock", "arguments": '{"sku":"AC-01"}'}}]},
                    "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            })

        async def async_send(client, request, **kwargs):
            return send(client, request, **kwargs)

        tool = {"type": "function", "function": {"name": "check_stock",
            "description": "Check product stock", "parameters": {"type": "object",
                "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}}
        with patch.object(httpx.Client, "send", send):
            reply = llm.bind_tools([tool]).invoke("Kiểm tra tồn kho AC-01")

        with patch.object(httpx.AsyncClient, "send", async_send):
            async_reply = asyncio.run(llm.bind_tools([tool]).ainvoke("Kiểm tra tồn kho AC-01"))

        self.assertEqual(reply.tool_calls[0]["name"], "check_stock")
        self.assertEqual(reply.tool_calls[0]["args"], {"sku": "AC-01"})
        self.assertEqual(async_reply.tool_calls, reply.tool_calls)
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(str(request.url), "https://llm.example/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-6-luna")
            self.assertEqual(payload["reasoning_effort"], "none")
            self.assertEqual(payload["max_completion_tokens"], 180)
            self.assertEqual(payload["temperature"], 0.3)
            self.assertEqual(payload["tools"][0]["function"]["name"], "check_stock")

    def test_other_compatible_models_do_not_receive_luna_reasoning_option(self) -> None:
        llm = build_llm(Settings(_env_file=None, llm_api_key="test-key", llm_model="custom-model"))
        self.assertIsInstance(llm, ChatOpenAI)
        self.assertIsNone(llm.reasoning_effort)

    def test_ollama_cloud_gemma_disables_thinking_on_the_wire(self) -> None:
        for model in ("gemma4:12b", "gemma4:31b"):
            with self.subTest(model=model):
                llm = build_llm(Settings(_env_file=None, llm_api_key="ollama-test-key",
                    llm_model=model, llm_base_url="https://ollama.com/v1"))
                requests = []

                def send(client, request, **kwargs):
                    requests.append(request)
                    return httpx.Response(200, request=request, json={
                        "id": "ollama-test", "object": "chat.completion", "created": 0,
                        "model": model, "choices": [{"index": 0,
                            "message": {"role": "assistant", "content": "Xin chào"},
                            "finish_reason": "stop"}]})

                async def async_send(client, request, **kwargs):
                    return send(client, request, **kwargs)

                with patch.object(httpx.Client, "send", send):
                    self.assertEqual(llm.invoke("Chào").content, "Xin chào")
                with patch.object(httpx.AsyncClient, "send", async_send):
                    self.assertEqual(asyncio.run(llm.ainvoke("Chào")).content, "Xin chào")
                self.assertEqual(len(requests), 2)
                for request in requests:
                    self.assertEqual(str(request.url), "https://ollama.com/v1/chat/completions")
                    self.assertEqual(request.headers["Authorization"], "Bearer ollama-test-key")
                    payload = json.loads(request.content)
                    self.assertEqual(payload["model"], model)
                    self.assertEqual(payload["reasoning_effort"], "none")

    def test_ollama_thinking_option_is_scoped_to_cloud_gemma(self) -> None:
        for model, base_url in (("custom-model", "https://ollama.com/v1"),
                                ("gemma4:31b", "https://other.example/v1")):
            llm = build_llm(Settings(_env_file=None, llm_api_key="test-key",
                llm_model=model, llm_base_url=base_url))
            self.assertIsNone(llm.reasoning_effort)


if __name__ == "__main__":
    unittest.main()
