"""Customer data never reaches Langfuse's span exporter."""

import unittest
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.configs import Settings
from app.agent.harness.runtime import DeepHarnessRuntime
from app.agent.harness.tracing import (
    LangfuseTracing, debug_mask, mask_trace_spans, safe_to_export,
)
from app.schemas.agent import TextTurnRequest


class TracingTest(unittest.IsolatedAsyncioTestCase):
    def test_debug_mask_keeps_model_io_but_redacts_credentials(self):
        settings = Settings(_env_file=None, llm_api_key="ollama-private-key",
                            llm_model="model", langfuse_secret_key="langfuse-private-key",
                            langfuse_capture_content=True)
        attrs = {
            "langfuse.observation.input": "Customer asks about 25 m²; ollama-private-key",
            "langfuse.observation.output": "The agent recommends a purifier",
            "http.request.header.authorization": "Bearer langfuse-private-key",
        }
        result = debug_mask(settings)(params=SimpleNamespace(spans={
            "model": SimpleNamespace(name="ChatOllama", attributes=attrs),
        }))
        patch_item = result.span_patches["model"]
        self.assertIn("http.request.header.authorization", patch_item.delete_attributes)
        self.assertIn("25 m²", patch_item.set_attributes["langfuse.observation.input"])
        self.assertNotIn("ollama-private-key", str(patch_item.set_attributes))
        self.assertNotIn("langfuse-private-key", str(patch_item.set_attributes))
        self.assertNotIn("langfuse.observation.output", patch_item.delete_attributes)

    def test_tracing_uses_base_url_without_trailing_slash(self):
        settings = Settings(_env_file=None, llm_api_key="model-key", llm_model="model",
                            langfuse_enabled=True, langfuse_public_key="pk-lf-test",
                            langfuse_secret_key="sk-lf-test",
                            langfuse_base_url="https://cloud.langfuse.com")
        with patch("langfuse.Langfuse") as client:
            LangfuseTracing(settings)
        self.assertEqual(client.call_args.kwargs["base_url"],
                         "https://cloud.langfuse.com")

    def test_event_or_status_description_is_not_exported(self):
        self.assertFalse(safe_to_export(SimpleNamespace(
            events=["private exception"], status=SimpleNamespace(description=None))))
        self.assertFalse(safe_to_export(SimpleNamespace(
            events=[], status=SimpleNamespace(description="private error"))))
        self.assertTrue(safe_to_export(SimpleNamespace(
            events=[], status=SimpleNamespace(description=None))))

    def test_export_mask_drops_payloads_and_unknown_attributes(self):
        attrs = {
            "langfuse.observation.input": "customer phone 0984726714",
            "langfuse.observation.output": "customer address 12 Main Street",
            "langfuse.observation.metadata.tool_args": "secret",
            "gen_ai.prompt.0.content": "private prompt",
            "future.sdk.attribute": "unknown private value",
            "user.id": "C001",
            "langfuse.observation.model.name": "gemma4:31b",
            "langfuse.observation.usage_details": '{"input":10,"output":5}',
            "langfuse.observation.type": "generation",
            "session.id": "opaque-session-id",
        }
        result = mask_trace_spans(params=SimpleNamespace(spans={"span": SimpleNamespace(
            name="model-call", attributes=attrs)}))
        exported = {key: value for key, value in attrs.items()
                    if key not in result.span_patches["span"].delete_attributes}
        self.assertEqual(set(exported), {
            "langfuse.observation.model.name", "langfuse.observation.usage_details",
            "langfuse.observation.type", "session.id",
        })
        self.assertNotIn("0984726714", str(exported))

    def test_root_summary_contains_only_known_operational_fields(self):
        attrs = {
            "langfuse.observation.input":
                '{"channel":"hotline","input_mode":"clean","text":"private"}',
            "langfuse.observation.output":
                '{"needs_handoff":false,"tool_count":2,"agent_text":"private"}',
        }
        result = mask_trace_spans(params=SimpleNamespace(spans={"root": SimpleNamespace(
            name="chat-turn", attributes=attrs)}))
        safe = result.span_patches["root"].set_attributes
        self.assertIn("hotline", safe["langfuse.observation.input"])
        self.assertIn('"tool_count": 2', safe["langfuse.observation.output"])
        self.assertNotIn("private", str(safe))

    async def test_runtime_attaches_callback_to_one_turn_and_skips_cached_turn(self):
        class FakeGraph:
            calls = []

            async def ainvoke(self, state, config):
                self.calls.append(config)
                return {"agent_text": "Done", "memory_writes": []}

        class FakeSpan:
            output = None

            def update(self, *, output):
                self.output = output

        class FakeTracing:
            turns = 0
            span = FakeSpan()

            @contextmanager
            def turn(self, request):
                self.turns += 1
                yield ("callback", self.span)

        class FakeGateway:
            async def invoke(self, name, args):
                return {"found": False}

        runtime = DeepHarnessRuntime(None, FakeGateway(), None)
        runtime.graph = FakeGraph()
        runtime.tracing = FakeTracing()
        turn = TextTurnRequest(client_msg_id=uuid4(), session_id=uuid4(),
                               channel="hotline", channel_identity="opaque",
                               on=date(2026, 10, 15), text="private text", input_mode="clean")
        await runtime.run(turn)
        await runtime.run(turn)
        self.assertEqual(runtime.tracing.turns, 1)
        self.assertEqual(runtime.graph.calls[0]["callbacks"], ["callback"])
        self.assertEqual(runtime.graph.calls[0]["run_name"], "process-chat-turn")
        self.assertEqual(runtime.tracing.span.output["memory_writes"], 0)


if __name__ == "__main__":
    unittest.main()
