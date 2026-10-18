"""Validate model-proposed facts against the current customer turn and tool results."""

import json
import re
import unicodedata
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.guardrails.checks import fact_evidence, mask_pii
from app.agent.memory.decision_makers import (
    BlockerResolutionReason, PERSON_PATTERN, person_mentions, roles_mentioned,
)
from app.constants import PROFILE_SLOT_KEYS, SLOT_REGISTRY, TOOL_ONLY_SLOT_KEYS, Slot


_CUSTOMER_KEYS = sorted(PROFILE_SLOT_KEYS - TOOL_ONLY_SLOT_KEYS - {"product_advised"})
_CLOSED_CUSTOMER_DOMAINS = "; ".join(
    f"{spec.key}=" + ("|".join(spec.allowed_values) if spec.allowed_values
                       else spec.value_type.__name__)
    for spec in SLOT_REGISTRY if spec.key in _CUSTOMER_KEYS
    and spec.value_domain == "closed"
)


def _fold(value: str) -> str:
    value = value.casefold().replace("đ", "d")
    return "".join(char for char in unicodedata.normalize("NFD", value)
                   if unicodedata.category(char) != "Mn")


_SLOT_CUES = {
    Slot.ROOM_AREA_M2: r"\bphong\b|\b(?:m2|met vuong)\b",
    Slot.BUDGET_VND: r"ngan sach|muon chi|dinh chi|co the chi|chi tam|chi khoang|"
                     r"khong (?:qua|hon|vuot)|toi da|\bduoi\b|"
                     r"\b\d[\d.,]*\s*(?:den|-)\s*\d[\d.,]*\s*(?:trieu|tr|cu|k)\b",
    Slot.HAS_CHILDREN: r"\bcon\b|\bbe\b|tre nho|em be",
    Slot.SIZE: r"\bsize\b|\bco giay\b",
    Slot.COLOR: r"\bmau\b",
    Slot.PAYMENT: r"\bcod\b|thanh toan|chuyen khoan|momo|zalopay",
    Slot.BLOCKER: rf"hoi {PERSON_PATTERN}|can nhac|chua quyet|"
                  r"(?:doi|cho)\s+[^.!?;,]{0,40}(?:luong|bao gia|duyet)|"
                  r"(?:ban|trao doi)\s+(?:bac\s+)?voi|"
                  rf"{PERSON_PATTERN}\s+(?:toi\s+)?(?:chua|khong)\s+dong y|"
                  rf"(?:doi|cho)\s+{PERSON_PATTERN}\s+ve|"
                  r"(?:xem|kiem tra)\s+lai\s+roi\s+bao",
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
    "Miền đóng: " + _CLOSED_CUSTOMER_DOMAINS + ". "
    "objection: dùng dat_qua cho lời chê giá đắt/mắc/cao/chát; các phản đối "
    "khác dùng khac và giữ evidence_quote nguyên văn. Không gọi do dự trung tính "
    "là phản đối. "
    "Với blocker, chỉ đề xuất trở ngại thực sự đang ngăn hoặc trì hoãn quyết định mua; "
    "không dùng blocker cho sở thích sản phẩm hay thời gian giao/nhận hàng. "
    "Giá trị blocker là cụm ngắn như 'hỏi chồng', 'đợi lương'; "
    "evidence_quote giữ nguyên cụm lời khách làm căn cứ. "
    "Trả đúng JSON dạng {\"fact_candidates\":[{\"key\":\"...\",\"value\":...,"
    "\"source\":\"customer\",\"evidence_quote\":\"...\"}]}; "
    "trả mảng rỗng nếu không có fact. Không thêm lời giải thích."
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
                quote = item.get("evidence_quote")
                candidate = {"key": item.get("key"), "value": value,
                             "source": item.get("source"), "origin": "model"}
                if isinstance(quote, str) and 0 < len(quote) <= 200 and mask_pii(quote) == quote:
                    candidate["evidence_quote"] = quote
                candidates.append(candidate)
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
        evidence = fact_evidence(key, value, "set", customer_text, tool_calls,
                                 item.get("evidence_quote"))
        source = evidence.source
        if source and final_answer is not None and source.startswith("tool:"):
            from app.agent.memory.reported_facts import reported_tool_fact
            if not reported_tool_fact(key, value, final_answer, tool_calls):
                source = None
        if source:
            value = evidence.normalized_value
            candidate = {"key": key, "value": value, "op": "set",
                         "source_kind": "customer" if source == "customer" else "tool",
                         **({"source_tool": source[5:]} if source.startswith("tool:") else {})}
            if evidence.evidence_quote:
                candidate["evidence_quote"] = evidence.evidence_quote
            if key in accepted and accepted[key]["value"] != value:
                conflicting.add(key)
            else:
                accepted[key] = candidate
    for key in conflicting:
        accepted.pop(key, None)
    return list(accepted.values())


_APPROVAL_TAIL = re.compile(
    r"(?:\s+(?:toi|anh|chi|em|minh|nha toi))?\s+"
    r"(?:da\s+)?(?:(chua|khong|tam)\s+)?"
    r"(?:dong y|chap nhan|ung ho|ok|gat dau|cho\s+roi)\b"
)
_RESOLUTION_CLAUSE = re.compile(r"[;,]|\b(?:nhung|va|ma)\b")
_RESOLUTION_HYPOTHETICAL = re.compile(r"\b(?:neu|gia su|lo|nho|vi du)\b")
_RESOLUTION_UNCERTAIN = re.compile(r"\b(?:khong biet|chua ro|chua biet)\b")
_RESOLUTION_QUESTION = re.compile(
    r"[?]|\b(?:duoc khong|phai khong|chua|khong a|a|ha|nhi)\s*$"
)


def blocker_resolution(customer_text: str, profile: dict[str, dict[str, Any]]
                       ) -> tuple[bool, BlockerResolutionReason]:
    """Decide whether this turn explicitly resolves the prior active blocker."""
    prior = profile.get(Slot.BLOCKER, {}).get("value")
    if not isinstance(prior, str):
        return False, BlockerResolutionReason.NO_PRIOR_BLOCKER
    old, current = _fold(prior), _fold(customer_text)
    old_roles = roles_mentioned(old)
    mentioned_approval = False
    deferred_reason = None
    for clause in _RESOLUTION_CLAUSE.split(current):
        for role, mention in person_mentions(clause):
            match = _APPROVAL_TAIL.match(clause, mention.end())
            if not match:
                continue
            if role not in old_roles:
                if match.group(1) not in {"chua", "khong"}:
                    mentioned_approval = True
                continue
            if match.group(1) in {"chua", "khong"}:
                return False, BlockerResolutionReason.APPROVAL_NEGATED
            if match.group(1) == "tam":
                deferred_reason = BlockerResolutionReason.TENTATIVE_APPROVAL
                continue
            if _RESOLUTION_HYPOTHETICAL.search(clause):
                deferred_reason = BlockerResolutionReason.HYPOTHETICAL_CONTEXT
                continue
            if _RESOLUTION_UNCERTAIN.search(clause):
                deferred_reason = BlockerResolutionReason.UNCERTAIN_APPROVAL
                continue
            if _RESOLUTION_QUESTION.search(clause.strip()):
                deferred_reason = BlockerResolutionReason.QUESTION_CONTEXT
                continue
            return True, BlockerResolutionReason.DECISION_MAKER_APPROVED
    if deferred_reason:
        return False, deferred_reason
    if mentioned_approval and old_roles:
        return False, BlockerResolutionReason.DIFFERENT_DECISION_MAKER
    price_ok = ("gia" in old or "dat" in old) and bool(re.search(
        r"\bthoi duoc\b|\bchap nhan gia\b|\bdong y gia\b", current))
    if price_ok:
        return True, BlockerResolutionReason.PRICE_ACCEPTED
    return False, BlockerResolutionReason.NO_RESOLUTION_EVIDENCE


def resolved_blockers(customer_text: str, profile: dict[str, dict[str, Any]],
                      accepted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retract a resolved prior blocker before writing any new blocker."""
    resolved, _ = blocker_resolution(customer_text, profile)
    return ([{"key": Slot.BLOCKER, "op": "delete", "source_kind": "customer"}]
            if resolved else [])
