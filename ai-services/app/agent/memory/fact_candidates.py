"""Validate model-proposed facts against the current customer turn and tool results."""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.guardrails.checks import fact_evidence, mask_pii
from app.constants import PROFILE_SLOT_KEYS, TOOL_ONLY_SLOT_KEYS


_CUSTOMER_KEYS = sorted(PROFILE_SLOT_KEYS - TOOL_ONLY_SLOT_KEYS - {"product_advised"})
_EXTRACTION_PROMPT = (
    "MEMORY_FACT_EXTRACTION. Đọc đúng lời khách trong lượt hiện tại và đề xuất tối đa 10 "
    "thông tin bền vững mà khách trực tiếp cung cấp. Không suy diễn từ câu hỏi, "
    "giá shop báo, kết quả tìm kiếm hay các lượt cũ. Nếu khách sửa thông tin cũ, "
    "chỉ đề xuất giá trị mới nhất. Ngân sách chỉ có khi khách nói giới hạn chi tiêu "
    "của chính họ; hỏi giá sản phẩm không phải ngân sách. "
    "Chỉ dùng key trong danh sách: " + ", ".join(_CUSTOMER_KEYS) + ". "
    "Trả đúng JSON dạng {\"fact_candidates\":[{\"key\":\"...\",\"value\":...,"
    "\"source\":\"customer\"}]}; trả mảng rỗng nếu không có fact. Không thêm lời giải thích."
)


async def extract_customer_candidates(model: Any, customer_text: str) -> list[dict[str, Any]]:
    """Ask a model for proposals without relying on regex or the sales agent's tool plan."""
    reply = await model.ainvoke([
        SystemMessage(content=_EXTRACTION_PROMPT),
        HumanMessage(content=customer_text),
    ])
    return model_candidates([reply])


def model_candidates(messages: list[Any]) -> list[dict[str, Any]]:
    """Read optional fact proposals from a structured final model answer."""
    candidates = []
    for message in messages:
        if getattr(message, "type", None) != "ai" or not isinstance(message.content, str):
            continue
        payload = parse_json_object(message.content)
        if isinstance(payload, dict) and isinstance(payload.get("fact_candidates"), list):
            for item in payload["fact_candidates"][:20]:
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                if isinstance(value, str) and (len(value) > 500 or mask_pii(value) != value):
                    continue
                candidates.append({"key": item.get("key"), "value": value,
                                   "source": item.get("source"), "origin": "model"})
    return candidates


def parse_json_object(content: str) -> dict[str, Any] | None:
    """Accept JSON returned directly or wrapped in one Markdown code fence."""
    body = content.strip()
    if body.startswith("```") and body.endswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
            body = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def accepted_candidates(customer_text: str, tool_calls: list[dict[str, Any]],
                        proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only proposed slots supported by this turn or a successful business tool."""
    accepted: dict[str, dict[str, Any]] = {}
    for item in proposals:
        key, value = item.get("key"), item.get("value")
        if not isinstance(key, str):
            continue
        source = fact_evidence(key, value, "set", customer_text, tool_calls)
        if source:
            accepted[key] = {"key": key, "value": value, "op": "set",
                             "source_kind": "customer" if source == "customer" else "tool",
                             **({"source_tool": source[5:]} if source.startswith("tool:") else {})}
    return list(accepted.values())
