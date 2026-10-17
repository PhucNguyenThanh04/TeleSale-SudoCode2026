"""Validate model-proposed facts against the current customer turn and tool results."""

import json
import re
import unicodedata
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.guardrails.checks import fact_evidence, mask_pii
from app.constants import PROFILE_SLOT_KEYS, TOOL_ONLY_SLOT_KEYS, Slot


_CUSTOMER_KEYS = sorted(PROFILE_SLOT_KEYS - TOOL_ONLY_SLOT_KEYS - {"product_advised"})


def _fold(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    return "".join(char for char in unicodedata.normalize("NFD", value)
                   if unicodedata.category(char) != "Mn")


_SLOT_CUES = {
    Slot.ROOM_AREA_M2: r"\bphong\b|\b(?:m2|met vuong)\b",
    Slot.BUDGET_VND: r"ngan sach|muon chi|dinh chi|co the chi|chi tam|chi khoang",
    Slot.HAS_CHILDREN: r"\bcon\b|\bbe\b|tre nho|em be",
    Slot.SIZE: r"\bsize\b|\bco giay\b",
    Slot.COLOR: r"\bmau\b",
    Slot.PAYMENT: r"\bcod\b|thanh toan|chuyen khoan|momo|zalopay",
    Slot.BLOCKER: r"hoi (?:vo|chong)|can nhac|chua quyet|de suy nghi",
    Slot.OBJECTION: r"dat qua|gia cao|dat hon|khong ung|khong thich",
    Slot.COMPETITOR_PRICE_VND: r"ben kia|ben khac|shop khac|doi thu",
}


def customer_slot_cues(customer_text: str) -> set[str]:
    """Cheap recall trigger; accepted facts still require independent evidence."""
    folded = _fold(customer_text)
    return {key for key, pattern in _SLOT_CUES.items() if re.search(pattern, folded)}
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
                        proposals: list[dict[str, Any]],
                        final_answer: str | None = None) -> list[dict[str, Any]]:
    """Keep only proposed slots supported by this turn or a successful business tool."""
    accepted: dict[str, dict[str, Any]] = {}
    conflicting: set[str] = set()
    for item in proposals:
        key, value = item.get("key"), item.get("value")
        if not isinstance(key, str):
            continue
        source = fact_evidence(key, value, "set", customer_text, tool_calls)
        if source and final_answer is not None and source.startswith("tool:"):
            from app.agent.memory.reported_facts import reported_tool_fact
            if not reported_tool_fact(key, value, final_answer, tool_calls):
                source = None
        if source:
            candidate = {"key": key, "value": value, "op": "set",
                         "source_kind": "customer" if source == "customer" else "tool",
                         **({"source_tool": source[5:]} if source.startswith("tool:") else {})}
            if key in accepted and accepted[key]["value"] != value:
                conflicting.add(key)
            else:
                accepted[key] = candidate
    for key in conflicting:
        accepted.pop(key, None)
    return list(accepted.values())


def resolved_blockers(customer_text: str, profile: dict[str, dict[str, Any]],
                      accepted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retract an open blocker only when the customer explicitly resolves it."""
    if any(item["key"] == Slot.BLOCKER for item in accepted):
        return []
    prior = profile.get(Slot.BLOCKER, {}).get("value")
    if not isinstance(prior, str):
        return []
    old, current = _fold(prior), _fold(customer_text)
    spouse_ok = ("vo" in old or "chong" in old) and bool(re.search(
        r"(?:vo|chong)(?:\s+\w+){0,3}\s+(?:dong y|ok|ung ho|chap nhan)", current))
    price_ok = ("gia" in old or "dat" in old) and bool(re.search(
        r"\bthoi duoc\b|\bchap nhan gia\b|\bdong y gia\b", current))
    return ([{"key": Slot.BLOCKER, "op": "delete", "source_kind": "customer"}]
            if spouse_ok or price_ok else [])
