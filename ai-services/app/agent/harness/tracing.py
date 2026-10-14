"""Optional Langfuse tracing with an export-time customer-data boundary."""

import json
import re
from contextlib import contextmanager
from typing import Iterator

from app.configs import Settings
from app.schemas.agent import TextTurnRequest


# Only low-risk operational attributes may leave this service. The LangChain
# callback captures prompts and tool arguments before this export hook runs.
_EXPORTED_ATTRIBUTES = frozenset({
    "langfuse.trace.name", "langfuse.trace.tags", "langfuse.observation.type",
    "langfuse.observation.level", "langfuse.observation.model.name",
    "langfuse.observation.usage_details", "langfuse.observation.cost_details",
    "langfuse.observation.completion_start_time", "langfuse.environment",
    "langfuse.internal.as_root", "langfuse.internal.is_app_root", "session.id",
})


def safe_to_export(span) -> bool:
    """Span events and status descriptions cannot be edited by the mask hook."""
    return not span.events and not getattr(span.status, "description", None)


def mask_trace_spans(*, params):
    """Remove all payload/metadata attributes, including unknown future SDK keys."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        removed = tuple(key for key in span.attributes if key not in _EXPORTED_ATTRIBUTES)
        safe = {}
        if span.name == "chat-turn":
            for field, permitted in (
                ("langfuse.observation.input", {"channel": {
                    "hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"},
                    "input_mode": {"clean", "asr_transcript", "chat_teencode"}}),
                ("langfuse.observation.output", {"needs_handoff": {True, False},
                    "tool_count": set(range(21)), "memory_writes": set(range(21))}),
            ):
                try:
                    payload = json.loads(span.attributes.get(field, ""))
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    summary = {key: value for key, values in permitted.items()
                               if type(value := payload.get(key)) in (str, int, bool)
                               and value in values}
                    if summary:
                        safe[field] = json.dumps(summary)
        if removed or safe:
            patches[identifier] = OtelSpanPatch(delete_attributes=removed,
                                                set_attributes=safe)
    return MaskOtelSpansResult(span_patches=patches)


_CREDENTIAL_ATTRIBUTE = re.compile(
    r"authorization|api[_-]?key|password|secret|credential|database[_-]?url|dsn|bearer",
    re.IGNORECASE,
)


def debug_mask(settings: Settings):
    """Keep debug payloads while stripping known credentials from exported spans."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    secrets = tuple(value for item in (
        settings.llm_api_key, settings.langfuse_secret_key,
        settings.ai_internal_token, settings.mcp_internal_token,
        settings.database_url,
    ) if item is not None and (value := item.get_secret_value()))

    def redact(value: str) -> str:
        for secret in secrets:
            value = value.replace(secret, "[REDACTED CREDENTIAL]")
        return value

    def mask(*, params):
        patches = {}
        for identifier, span in params.spans.items():
            removed, replaced = [], {}
            for key, value in span.attributes.items():
                if _CREDENTIAL_ATTRIBUTE.search(key):
                    removed.append(key)
                elif isinstance(value, str):
                    cleaned = redact(value)
                    if cleaned != value:
                        replaced[key] = cleaned
                elif isinstance(value, (tuple, list)) and all(
                    isinstance(item, str) for item in value
                ):
                    cleaned = tuple(redact(item) for item in value)
                    if cleaned != tuple(value):
                        replaced[key] = cleaned
            if removed or replaced:
                patches[identifier] = OtelSpanPatch(
                    delete_attributes=tuple(removed), set_attributes=replaced,
                )
        return MaskOtelSpansResult(span_patches=patches)

    return mask


class LangfuseTracing:
    def __init__(self, settings: Settings) -> None:
        from langfuse import Langfuse

        self.capture_content = settings.langfuse_capture_content
        self.client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=str(settings.langfuse_base_url).rstrip("/"),
            environment=settings.app_env,
            mask_otel_spans=(debug_mask(settings) if self.capture_content
                             else mask_trace_spans),
            should_export_span=safe_to_export,
        )
        self.public_key = settings.langfuse_public_key

    @contextmanager
    def turn(self, request: TextTurnRequest) -> Iterator[object]:
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler

        with self.client.start_as_current_observation(
            as_type="span", name="chat-turn",
            input=(request.model_dump(mode="json") if self.capture_content else
                   {"channel": request.channel, "input_mode": request.input_mode}),
        ) as span:
            with propagate_attributes(
                trace_name="chat-turn", session_id=str(request.session_id),
                tags=["chat", request.channel],
            ):
                yield CallbackHandler(public_key=self.public_key), span

    def flush(self) -> None:
        self.client.flush()

    def shutdown(self) -> None:
        self.client.shutdown()
