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
    value = value.casefold().replace("đ", "d").replace("²", "2")
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

_ROOM_AREA_MENTION = re.compile(
    r"\bphong\s+([a-z ]{0,35}?)\s*(\d+)\s*(?:m2|met vuong)\b"
)


def _room_scope_for_area(customer_text: str, area: int) -> str | None:
    """Resolve an area only from the local room phrase that contains it."""
    matches = []
    for match in _ROOM_AREA_MENTION.finditer(_fold(customer_text)):
        if int(match.group(2)) != area:
            continue
        label = "_".join(match.group(1).strip().split())
        if label == "thu_hai":
            label = "2"
        elif label == "thu_nhat":
            label = "1"
        matches.append("phong_" + (label or "1"))
    return matches[0] if len(set(matches)) == 1 and matches else None


def _tool_supports_product_scope(key: str, value: Any, sku: str,
                                 calls: list[dict[str, Any]]) -> bool:
    for call in calls:
        name, args, result = call.get("name"), call.get("args", {}), call.get("result", {})
        if not isinstance(args, dict) or not isinstance(result, dict) or "error" in result:
            continue
        item_sku = result.get("sku") or args.get("sku")
        if name == "catalog.search" and key == Slot.PRODUCT_ADVISED:
            if any(item.get("sku") == sku for item in result.get("items", [])
                   if isinstance(item, dict)):
                return value == sku
        if item_sku != sku:
            continue
        if name == "pricing.get_quote":
            if key == Slot.PRODUCT_ADVISED and value == sku:
                return True
            if key == Slot.PRICE_QUOTED_VND and result.get("final_price_vnd") == value:
                return True
            promos = [item for item in result.get("applied_promos", [])
                      if isinstance(item, dict)]
            if key == Slot.PROMO_CODE and any(item.get("promo_code") == value for item in promos):
                return True
            if key == Slot.PROMO_EXPIRY and any(item.get("valid_until") == value for item in promos):
                return True
        if name == "inventory.check" and key == Slot.IN_STOCK and result.get("in_stock") is value:
            return True
        if name == "order.create" and key == Slot.VARIANT_SKU \
                and result.get("status") == "created" and value == sku:
            return True
    return False


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
    "Nếu khách nêu diện tích nhiều phòng, đề xuất một room_area_m2 cho từng phòng; "
    "đừng chỉ giữ phòng cuối. Code sẽ kiểm lại phòng và diện tích từ lời khách. "
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
                if item.get("scope_type") in {"room", "product"} and isinstance(item.get("scope_id"), str):
                    candidate.update(scope_type=item["scope_type"], scope_id=item["scope_id"])
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
    accepted: dict[tuple[str, str, str], dict[str, Any]] = {}
    conflicting: set[tuple[str, str, str]] = set()
    for item in proposals:
        key, value = item.get("key"), item.get("value")
        if not isinstance(key, str):
            continue
        evidence = fact_evidence(key, value, "set", customer_text, tool_calls,
                                 item.get("evidence_quote"))
        source = evidence.source
        if source and final_answer is not None and source.startswith("tool:"):
            from app.agent.memory.reported_facts import reported_tool_fact
            if not reported_tool_fact(key, value, final_answer, tool_calls,
                                      item.get("scope_id") if item.get("scope_type") == "product" else None):
                source = None
        if source:
            value = evidence.normalized_value
            scope_type, scope_id = item.get("scope_type", "global"), item.get("scope_id", "")
            if key == Slot.ROOM_AREA_M2 and source == "customer":
                observed_room = _room_scope_for_area(customer_text, value)
                if scope_type == "room" and observed_room != scope_id:
                    continue
                if scope_type == "global" and observed_room:
                    scope_type, scope_id = "room", observed_room
            elif scope_type == "room":
                continue
            if scope_type == "product" and (source == "customer" or not isinstance(scope_id, str)
                                             or not _tool_supports_product_scope(
                                                 key, value, scope_id, tool_calls)):
                continue
            candidate = {"key": key, "value": value, "op": "set",
                         "source_kind": "customer" if source == "customer" else "tool",
                         **({"source_tool": source[5:]} if source.startswith("tool:") else {})}
            if scope_type != "global":
                candidate.update(scope_type=scope_type, scope_id=scope_id)
            if evidence.evidence_quote:
                candidate["evidence_quote"] = evidence.evidence_quote
            identity = (scope_type, scope_id, key)
            if identity in accepted and accepted[identity]["value"] != value:
                conflicting.add(identity)
            else:
                accepted[identity] = candidate
    for identity in conflicting:
        accepted.pop(identity, None)
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
