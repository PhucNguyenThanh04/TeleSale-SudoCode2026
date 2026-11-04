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
    ("order_id", re.compile(r"mã đơn|đơn hàng nào", re.I)),
    ("address", re.compile(r"địa chỉ|giao (?:tới|đến) đâu", re.I)),
    ("payment", re.compile(r"thanh toán|chuyển khoản|COD", re.I)),
    ("promo_code", re.compile(r"mã (?:khuyến mãi|ưu đãi)", re.I)),
    ("customer_name", re.compile(r"(tên là gì|xin phép gọi anh/chị là|tên của anh/chị)", re.IGNORECASE)),
]

# Claims extraction patterns
HUMAN_CLAIM_PATTERNS = [
    re.compile(r"(em là người thật|tôi là người thật|không phải ai|không phải bot|người thật nói chuyện)", re.IGNORECASE),
]


_DIGITS = {"không":0,"một":1,"mốt":1,"hai":2,"ba":3,"bốn":4,"tư":4,
           "năm":5,"lăm":5,"sáu":6,"bảy":7,"tám":8,"chín":9}
_NUMBER_WORDS = "|".join((*_DIGITS,"mười","mươi","trăm","nghìn","ngàn","triệu","linh","lẻ"))
_SPOKEN_NUMBER = re.compile(r"(?<!\w)(?:" + _NUMBER_WORDS + r")(?:\s+(?:" + _NUMBER_WORDS + r"))*(?!\w)",re.I)


def numeric_text(text):
    def replace(match):
        words=match.group().lower().split()
        if not any(w in {"nghìn","ngàn","triệu"} for w in words) and not re.match(r"\s*(?:đồng|ngày|tháng)\b",text[match.end():],re.I):
            return match.group()
        total=group=0
        for w in words:
            if w in _DIGITS:
                group+=_DIGITS[w]
            elif w=="trăm":
                group*=100
            elif w in {"mười","mươi"}:
                group=(group or 1)*10
            elif w in {"nghìn","ngàn","triệu"}:
                total+=group*({"nghìn":1000,"ngàn":1000,"triệu":1000000}[w])
                group=0
        return str(total+group)
    return _SPOKEN_NUMBER.sub(replace,text)


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
                r"bao nhiêu|\bgì\b|phải không|đúng không|nào (?:ạ|không)|chưa (?:ạ|chị|anh)|xong chưa|cho em (?:xin|biết)|xin (?:chị|anh) (?:cho|cung cấp)",
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
            if not matches:
                matches = [(0, "other")]
            for _, slot in sorted(set(matches)):
                questions.append({"slot": slot, "type": "confirm" if is_confirm else "open",
                                  "text": target.strip()})

    return questions


def extract_claims(agent_text: str, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract verifiable factual claims from agent text and tool calls."""
    claims = []
    if not agent_text:
        agent_text = ""

    # A self-assertion is different from questions, quotations or reported speech.
    for clause in re.split(r"[.!?;\n]", agent_text):
        if not clause.strip() or any(c in clause for c in ('“', '”', '"', '«')):
            continue
        if re.search(r"phải không|đúng không|khách (?:hỏi|nói)|nếu|không (?:phải )?(?:là )?người thật", clause, re.I):
            continue
        # The question mark belongs to the complete sentence, not the split clause.
        if clause.strip() + "?" in agent_text or re.search(re.escape(clause.strip()) + r"\s*\?", agent_text):
            continue
        if re.search(r"(?:em|tôi|mình)\s+(?:là người thật|không phải (?:là )?(?:ai|bot)\b)", clause, re.I):
            claims.append({"field": "is_human", "value": True, "text": clause.strip()})
            break

    # Only speech supplies claims. Tools never repair or invent their truth.
    for clause in re.split(r"\.(?!\d)|[!;\n]|\bnhưng\b|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b|phải không|đúng không", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        if re.search(r"giá|\bchỉ\b|\bcòn\b", clause, re.IGNORECASE):
            priced = re.sub(r"không phải.+?\bmà(?: là)?\s*", "", clause, flags=re.I)
            priced = re.split(r"\bchứ không(?: phải)?\b", priced, flags=re.I)[0]
            if re.search(r"không (?:phải|có)\s+(?:là\s+)?(?:giá|\d)", priced, re.I):
                priced = ""
            for amount, kind, _ in _money_claims(numeric_text(priced)):
                if kind == "price" and amount >= 0:
                    field = "list_price_vnd" if re.search(r"niêm yết|giá gốc", clause, re.I) else "price_vnd"
                    if historical:
                        field = "historical_" + field
                    claims.append({"field": field, "value": amount, "source": "text", "text": clause.strip()})
        codes = re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", clause)
        codes = [code for code in codes if not code.startswith(("SKU-", "OD-"))]
        if codes or re.search(r"khuyến mãi|giảm giá|ưu đãi|tặng|biếu", clause, re.IGNORECASE):
            inactive = bool(re.search(
                r"(?:đã\s+)?hết\s+(?:hạn|hiệu lực|khuyến mãi|chương trình)|"
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
            stock_field = "new_size_in_stock" if re.search(r"size mới|size đổi|cỡ mới", clause, re.I) else "in_stock"
            claims.append({"field": "historical_" + stock_field if historical else stock_field,
                           "value": not negative, "source": "text", "text": clause.strip()})
    lower_text = agent_text.lower()
    if "ngừng bán" in lower_text:
        claims.append({"field": "product_status", "value": "discontinued", "source": "text"})

    # Policy facts use BTC field names. Only explicit, unconditional speech counts.
    for clause in re.split(r"\.(?!\d)|[!;\n]|,\s*(?!\d)", agent_text):
        if "?" in clause or re.search(r"\bnếu\b|phải không|đúng không", clause, re.I):
            continue
        historical = bool(re.search(r"lần trước|trước đây", clause, re.I)) and not re.search(r"hiện|hôm nay|đang", clause, re.I)
        historical = historical or bool(re.search(r"chính sách cũ|bản cũ", clause, re.I))
        prefix = "historical_" if historical else ""
        patterns = [
            ("delivery_days", r"giao\s*(?:trong vòng|trong|khoảng|mất)?\s*(\d+)\s*ngày", int),
            ("return_days", r"đổi\s*(?:trả)?\s*(?:trong|trong vòng|tối đa)?\s*(\d+)\s*ngày", int),
            ("warranty_months", r"bảo hành\s*(?:trong|tới|đến)?\s*(\d+)\s*tháng", int),
            ("policy_version", r"(?:chính sách|phiên bản)\s*(?:bản|v)?\s*(20\d{2}-\d{2})", str),
            ("restock_date", r"(?:hàng về|về hàng|nhập hàng)\s*(?:ngày)?\s*(20\d{2}-\d{2}-\d{2})", str),
        ]
        for field, pattern, cast in patterns:
            match = re.search(pattern, numeric_text(clause), re.I)
            if match:
                claims.append({"field": prefix + field, "value": cast(match.group(1)), "text": clause.strip()})
        if re.search(r"phí đổi|phí (?:đổi trả|đổi size)", clause, re.I):
            money = _money_claims("Giá " + numeric_text(clause))
            if money:
                claims.append({"field": prefix + "exchange_fee_vnd", "value": money[0][0], "text": clause.strip()})
            elif re.search(r"miễn phí|không (?:mất|thu|tính) phí", clause, re.I):
                claims.append({"field": prefix + "exchange_fee_vnd", "value": 0, "text": clause.strip()})
        if re.search(r"freeship|miễn phí (?:ship|vận chuyển|giao hàng)|không (?:được )?miễn phí (?:ship|vận chuyển|giao hàng)", clause, re.I):
            negative = bool(re.search(r"không|chưa|hết hiệu lực", clause, re.I))
            claims.append({"field": prefix + "freeship", "value": not negative, "text": clause.strip()})
        if re.search(r"chính sách cũ.*(?:hết hiệu lực|thay thế)", clause, re.I):
            claims.append({"field": "old_policy_superseded", "value": True, "text": clause.strip()})

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
