"""Trace Extractor Engine for AI TeleSale SudoCode 2026.

Extracts questions, claims, and facts used from agent outputs and turn state
to construct standardized evaluation traces adhering to BTC schema.
"""

from __future__ import annotations

import re
from typing import Any

# Question detection patterns
CONFIRM_PATTERNS = [
    re.compile(r"(đúng không|phải không|có phải|chuẩn chưa|đúng chưa|xác nhận lại)\b", re.IGNORECASE),
    re.compile(r"^dạ anh/chị chọn .*, đúng không ạ", re.IGNORECASE),
]

SLOT_QUESTION_PATTERNS = [
    ("room_area_m2", re.compile(r"(bao nhiêu mét|diện tích|m2|rộng bao nhiêu)", re.IGNORECASE)),
    ("has_children", re.compile(r"(có trẻ nhỏ|trẻ em|bé nhỏ|bé sơ sinh|con nhỏ)", re.IGNORECASE)),
    ("budget_vnd", re.compile(r"(ngân sách|tầm tiền|tầm giá|khoảng bao nhiêu tiền)", re.IGNORECASE)),
    ("preferred_color", re.compile(r"(màu gì|thích màu|chọn màu|màu sắc)", re.IGNORECASE)),
    ("size", re.compile(r"(cỡ|size|kích cỡ)", re.IGNORECASE)),
    ("product_advised", re.compile(r"(máy nào|sản phẩm nào|quan tâm mẫu nào|chọn loại nào)", re.IGNORECASE)),
    ("customer_name", re.compile(r"(tên là gì|xin phép gọi anh/chị là|tên của anh/chị)", re.IGNORECASE)),
]

# Claims extraction patterns
PRICE_PATTERN = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)\s*(?:đ|đồng|vnd|nghìn|triệu)", re.IGNORECASE)
HUMAN_CLAIM_PATTERNS = [
    re.compile(r"(em là người thật|tôi là người thật|không phải ai|không phải bot|người thật nói chuyện)", re.IGNORECASE),
]


def extract_questions(agent_text: str) -> list[dict[str, Any]]:
    """Detect and classify questions from agent response."""
    questions = []
    if not agent_text:
        return questions

    # Split into sentences keeping punctuation context
    sentences = re.split(r"(?<=[.?!;\n])\s+", agent_text)
    for s in sentences:
        s = s.strip()
        if not s:
            continue

        is_question = "?" in s or any(kw in s.lower() for kw in ("bao nhiêu", "gì không", "phải không", "đúng không", "nào ạ", "nào không"))
        if not is_question:
            continue

        # Check confirm vs open
        is_confirm = any(p.search(s) for p in CONFIRM_PATTERNS)
        q_type = "confirm" if is_confirm else "open"

        # Match slots
        for slot_name, pat in SLOT_QUESTION_PATTERNS:
            if pat.search(s):
                questions.append({
                    "slot": slot_name,
                    "type": q_type,
                    "text": s,
                })
                break

    return questions


def extract_claims(agent_text: str, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract verifiable factual claims from agent text and tool calls."""
    claims = []
    if not agent_text:
        agent_text = ""

    # Check for human claim violation
    for p in HUMAN_CLAIM_PATTERNS:
        if p.search(agent_text):
            claims.append({"field": "is_human", "value": True, "text": agent_text})
            break

    # Extract price claims from tool calls (most accurate source)
    for tc in tool_calls:
        args = tc.get("args", {})
        if tc.get("name") in ("pricing.get_quote", "order.create"):
            price = args.get("price_vnd")
            if price is not None:
                claims.append({"field": "price_vnd", "value": price, "source": "tool_call"})
            sku = args.get("sku")
            if sku:
                claims.append({"field": "sku", "value": sku, "source": "tool_call"})
            promo = args.get("promo_code")
            if promo:
                claims.append({"field": "promo_code", "value": promo, "source": "tool_call"})

    # Extract delivery / stock claims from text
    lower_text = agent_text.lower()
    if "còn hàng" in lower_text or "sẵn hàng" in lower_text:
        claims.append({"field": "in_stock", "value": True, "source": "text"})
    elif "hết hàng" in lower_text or "tạm hết" in lower_text:
        claims.append({"field": "in_stock", "value": False, "source": "text"})

    if "ngừng bán" in lower_text:
        claims.append({"field": "product_status", "value": "discontinued", "source": "text"})

    # Check delivery days
    m_del = re.search(r"giao (?:trong vòng|khoảng|mất)?\s*(\d+)\s*ngày", lower_text)
    if m_del:
        try:
            claims.append({"field": "delivery_days", "value": int(m_del.group(1)), "source": "text"})
        except ValueError:
            pass

    return claims


def build_trace_row(
    scenario_id: str,
    call_name: str,
    turn_idx: int,
    user_text: str,
    agent_text: str,
    tool_calls: list[dict[str, Any]],
    memory_writes: list[dict[str, Any]],
    facts_used: list[str],
    latency_ms: float,
    call_brief_latency_ms: float | None = None,
) -> dict[str, Any]:
    """Construct one trace row matching BTC reference_eval structure."""
    questions = extract_questions(agent_text)
    claims = extract_claims(agent_text, tool_calls)

    return {
        "scenario_id": scenario_id,
        "call": call_name,
        "turn": turn_idx,
        "user_text": user_text,
        "agent_text": agent_text,
        "tool_calls": tool_calls,
        "memory_writes": memory_writes,
        "facts_used": facts_used,
        "questions": questions,
        "claims": claims,
        "latency": {
            "total_ms": round(latency_ms, 1),
            "ttft_ms": round(latency_ms, 1),  # non-streaming total
        },
        "call_brief_latency_ms": round(call_brief_latency_ms, 1) if call_brief_latency_ms else None,
    }
