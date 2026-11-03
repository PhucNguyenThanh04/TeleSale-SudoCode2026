"""Trace Extractor Engine for AI TeleSale SudoCode 2026.

Extracts questions, claims, and facts used from agent outputs and turn state
to construct standardized evaluation traces adhering to BTC schema.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.guardrails.checks import _money_claims

# Question detection patterns
CONFIRM_PATTERNS = [
    re.compile(r"(đúng không|phải không|có phải|chuẩn chưa|đúng chưa|xác nhận lại)\b", re.IGNORECASE),
    re.compile(r"^dạ anh/chị chọn .*, đúng không ạ", re.IGNORECASE),
]

SLOT_QUESTION_PATTERNS = [
    ("room_area_m2", re.compile(r"(bao nhiêu mét|diện tích|m2|m²|rộng bao nhiêu)", re.IGNORECASE)),
    ("has_children", re.compile(r"(có trẻ nhỏ|trẻ em|bé nhỏ|bé sơ sinh|con nhỏ)", re.IGNORECASE)),
    ("budget_vnd", re.compile(r"(ngân sách|tầm tiền|tầm giá|khoảng bao nhiêu tiền)", re.IGNORECASE)),
    ("preferred_color", re.compile(r"(màu gì|thích màu|chọn màu|màu sắc|màu nào)", re.IGNORECASE)),
    ("size", re.compile(r"(cỡ|size|kích cỡ)", re.IGNORECASE)),
    ("product_advised", re.compile(r"(máy nào|sản phẩm nào|quan tâm mẫu nào|chọn loại nào|mẫu (?:giày |máy )?nào)", re.IGNORECASE)),
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

    # Commas often separate remembered context from the requested new information.
    sentences = re.split(r"(?<=[.?!;\n])\s+", agent_text)
    for sentence in sentences:
        clauses = re.split(r",\s*", sentence.strip())
        for index, clause in enumerate(clauses):
            is_confirm = any(p.search(clause) for p in CONFIRM_PATTERNS)
            is_question = "?" in clause or bool(re.search(
                r"bao nhiêu|gì không|phải không|đúng không|nào (?:ạ|không)|chưa (?:ạ|chị|anh)|xong chưa",
                clause, re.IGNORECASE))
            if not is_question:
                continue
            target = clause
            if is_confirm and index and not any(p.search(target) for _, p in SLOT_QUESTION_PATTERNS):
                target = clauses[index - 1] + ", " + clause
            blocker = re.search(r"trao đổi|bàn với|cân nhắc|hỏi (?:chồng|vợ|người)|quyết định|đồng ý", target, re.I)
            matches = [(m.start(), slot) for slot, pat in SLOT_QUESTION_PATTERNS
                       if (m := pat.search(target))]
            if blocker:
                matches = [(blocker.start(), "blocker")]
            for _, slot in sorted(matches):
                questions.append({"slot": slot, "type": "confirm" if is_confirm else "open",
                                  "text": target.strip()})

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

    # Only speech supplies claims. Tools never repair or invent their truth.
    for clause in re.split(r"\.(?!\d)|[!;\n]|\bnhưng\b|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b|phải không|đúng không", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        if re.search(r"giá|\bchỉ\b|\bcòn\b", clause, re.IGNORECASE):
            for amount, kind, _ in _money_claims(clause):
                if kind == "price" and amount >= 100_000:
                    field = "list_price_vnd" if re.search(r"niêm yết|giá gốc", clause, re.I) else "price_vnd"
                    if historical:
                        field = "historical_" + field
                    claims.append({"field": field, "value": amount, "source": "text", "text": clause.strip()})
        codes = re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", clause)
        codes = [code for code in codes if not code.startswith(("SKU-", "OD-"))]
        if codes or re.search(r"khuyến mãi|giảm giá|ưu đãi|tặng|biếu", clause, re.IGNORECASE):
            inactive = bool(re.search(
                r"(?:đã\s+)?hết\s+(?:hạn|hiệu lực|khuyến mãi)|"
                r"không\s+còn|chưa\s+có|không\s+có|không\s+(?:được\s+)?tặng", clause, re.I))
            fields = [f"promo_{code}_active" for code in codes] if codes else ["promo_active"]
            if historical:
                fields = [field.removesuffix("_active") + "_historical" for field in fields]
            claims.extend({"field": field, "value": not inactive, "source": "text", "text": clause.strip()}
                          for field in fields)

    # Stock statements have the same polarity/time boundary as offer claims.
    for clause in re.split(r"\.(?!\d)|[!;\n]|\bnhưng\b|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        negative = bool(re.search(r"không\s+còn\s+hàng|hết hàng|tạm hết", clause, re.I))
        positive = bool(re.search(r"còn hàng|sẵn hàng", clause, re.I))
        if negative or positive:
            claims.append({"field": "historical_in_stock" if historical else "in_stock",
                           "value": not negative, "source": "text", "text": clause.strip()})
    lower_text = agent_text.lower()
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
