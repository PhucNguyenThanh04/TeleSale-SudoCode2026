"""Stateless LangMem proposal extraction; canonical writes happen elsewhere."""

import json
import asyncio
import re
from datetime import date
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langmem import create_memory_manager

from app.agent.guardrails.checks import (
    _AREA_UNIT, _EXPENSIVE_PHRASE, _SPOKEN_AREA, _spoken_integer,
    customer_budget_amounts, fact_evidence,
)
from app.constants import Slot
from app.agent.prompts import MEMORY_PROMPT, text_prompt
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


_INSTRUCTIONS = (
    "Extract only customer-stated durable facts and per-call events from the supplied "
    "Vietnamese telesale turns. Preserve source turn IDs and quote dates. "
    "Do not infer facts from questions, jokes, hypotheticals, or another "
    "person's words. Do not emit tool-derived prices or tool-derived quotes; those are "
    "handled deterministically. However, DO extract customer-stated competitor_price_vnd "
    "(when customer mentions another shop's price, e.g. 'bên kia bán 6,9 triệu' -> 6900000), "
    "objection (e.g. 'dat_qua' when customer complains about high price), and blocker "
    "(e.g. 'cần hỏi chồng', 'cần hỏi vợ', 'cần cân nhắc thêm'). "
    "Use the exact schema slot keys, especially has_children, budget_vnd, "
    "room_area_m2, competitor_price_vnd, objection, blocker, size, color, payment. "
    "Convert Vietnamese amounts (including spoken numbers like 'năm triệu rưỡi' -> 5500000) "
    "into integer VND and areas (like 'ba mươi lăm mét vuông' -> 35) into "
    "integer square meters; quote the supporting customer phrase. Emit separate "
    "facts for separate supported slots. For a customer's goal, per-product advice, "
    "next step, or unresolved question/blocker, propose a CustomerCallEpisodeCandidate "
    "with exact source IDs. For every EvidencedText field (blockers, questions, "
    "customer_goal, advice_given, next_step), provide both a concise normalized "
    "'text' (e.g. 'cần hỏi chồng') and a literal 'evidence_quote' copied verbatim "
    "from the turn text. Use 'topics' with scope_type='product' and scope_id=<SKU> "
    "to record advice_given and next_step per discussed product. If prior_open_items "
    "are present in the turn payload and the customer or agent explicitly confirms "
    "a prior blocker or question is settled (e.g. 'ông xã đồng ý rồi'), propose a "
    "ResolvedItem in the matching topic's resolved_items with that item_id and literal "
    "evidence_quote. If the customer defers a decision pending another person's "
    "approval or information, record the stated dependency as an open blocker; a "
    "callback outcome alone does not preserve it. Return no memory when evidence is "
    "insufficient. Earlier turns are context; propose profile facts only from the "
    "latest turn and cite its turn ID."
)


_OPAQUE_FIELDS = {"turn_id", "source_turn_id", "session_id", "customer_id",
                  "sku", "order_id", "scope_id", "item_id"}


def _mask_payload(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _mask_payload(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_payload(item, field) for item in value]
    if isinstance(value, str):
        return value if field in _OPAQUE_FIELDS else mask_pii(value)
    return value


def _safe_content(value: Any, open_items: list[dict] | None = None) -> str:
    if not isinstance(value, str):
        return mask_pii(str(value))
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return mask_pii(value)
    if isinstance(payload, dict) and open_items:
        payload = {**payload, "prior_open_items": [
            {"item_id": str(item.get("item_id", "")),
             "kind": str(item.get("kind", "blocker")),
             "text": str(item.get("text", "")),
             "scope_type": str(item.get("scope_type", "global")),
             "scope_id": str(item.get("scope_id", ""))}
            for item in open_items if isinstance(item, dict) and item.get("item_id")
        ]}
    return json.dumps(_mask_payload(payload), ensure_ascii=False)


async def extract_candidates(
    model: BaseChatModel, turns: list[dict], existing: list[dict],
    open_items: list[dict] | None = None,
) -> tuple[list[ProfileFactCandidate], CustomerCallEpisodeCandidate | None]:
    """Use LangMem to propose typed records without persistence side effects."""
    instructions = await asyncio.to_thread(text_prompt, MEMORY_PROMPT, _INSTRUCTIONS)
    manager = create_memory_manager(
        model, schemas=[ProfileFactCandidate, CustomerCallEpisodeCandidate],
        instructions=instructions, enable_deletes=False)
    safe_turns = []
    for idx, turn in enumerate(turns):
        is_last = idx == len(turns) - 1
        safe_turns.append({
            **turn,
            "content": _safe_content(turn.get("content", ""),
                                     open_items if is_last else None),
        })
    typed_existing = []
    for row in existing[:50]:
        if not isinstance(row, dict):
            continue
        try:
            memory = ProfileFactCandidate.model_validate({
                "key": row["key"], "value": row["value"], "op": "set",
                "scope_type": row.get("scope_type", "global"),
                "scope_id": row.get("scope_id", ""),
                "source_kind": row["source_kind"],
                "source_turn_id": row["source_turn_id"],
                "source_tool": row.get("source_tool"),
                "evidence_quote": row["evidence_quote"],
                "observed_on": row["on"],
            })
        except (KeyError, ValueError):
            continue
        identifier = json.dumps([memory.scope_type, memory.scope_id, memory.key],
                                ensure_ascii=False, separators=(",", ":"))
        typed_existing.append((identifier, memory))
    result = await manager.ainvoke({"messages": safe_turns,
                                   "existing": typed_existing})
    facts = []
    episode = None
    for item in result:
        content: Any = getattr(item, "content", None)
        if isinstance(content, ProfileFactCandidate):
            facts.append(content)
        elif isinstance(content, CustomerCallEpisodeCandidate):
            episode = content
    if turns:
        facts.extend(_supplement_customer_facts(turns[-1], facts))
    return facts, episode


def _supplement_customer_facts(last_turn: dict,
                               existing_facts: list[ProfileFactCandidate]
                               ) -> list[ProfileFactCandidate]:
    """Deterministically propose high-confidence customer facts omitted by the LLM."""
    try:
        payload = json.loads(last_turn.get("content", ""))
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    turn_id = payload.get("turn_id")
    raw_on = payload.get("on")
    customer_text = payload.get("customer_text")
    if (not isinstance(turn_id, str) or not turn_id
            or not isinstance(raw_on, str) or not raw_on
            or not isinstance(customer_text, str) or not customer_text.strip()):
        return []
    try:
        observed_on = date.fromisoformat(raw_on)
    except ValueError:
        return []
    safe_text = mask_pii(customer_text)
    from app.mcp_servers.mcp_memory.services.memory import _valid_fact
    present_keys = {
        f.key for f in existing_facts
        if f.source_turn_id == turn_id and f.source_kind == "customer"
        and f.op in {"set", "supersede"}
        and _valid_fact(f.model_dump(mode="json"))
        and fact_evidence(f.key, f.value, "set", safe_text, [], f.evidence_quote).source == "customer"
    }
    candidates: list[tuple[str, Any, str]] = []
    comp_match = re.search(
        r"(?i)\b(?:bên kia|bên khác|shop khác|đối thủ)\b[^.!?]{0,80}?\b"
        r"(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn|ngàn|k)\b", safe_text)
    if comp_match:
        digits, unit = comp_match.group(1), comp_match.group(2)
        val = int(float(digits.replace(",", ".")) *
                  (1_000_000 if unit.lower() in {"triệu", "tr"} else 1_000))
        candidates.append((Slot.COMPETITOR_PRICE_VND, val, comp_match.group(0).strip()))
    exp_match = _EXPENSIVE_PHRASE.search(safe_text)
    if exp_match:
        candidates.append((Slot.OBJECTION, "dat_qua", exp_match.group(0).strip()))
    budgets = customer_budget_amounts(safe_text)
    if len(budgets) == 1:
        candidates.append((Slot.BUDGET_VND, next(iter(budgets)), safe_text[:200]))
    area_match = re.search(rf"(?i)\b(\d+)\s*{_AREA_UNIT}(?!\w)", safe_text)
    if area_match:
        candidates.append((Slot.ROOM_AREA_M2, int(area_match.group(1)), area_match.group(0).strip()))
    else:
        for sp_match in _SPOKEN_AREA.finditer(safe_text):
            parsed = _spoken_integer(sp_match.group(1))
            if parsed is not None:
                candidates.append((Slot.ROOM_AREA_M2, parsed, sp_match.group(0).strip()))
                break
    child_match = re.search(r"(?i)\b(?:bé nhỏ|con nhỏ|có con|có em bé)\b", safe_text)
    if child_match:
        candidates.append((Slot.HAS_CHILDREN, True, child_match.group(0).strip()))
    for pattern, norm_blocker in (
        (r"(?i)\b(?:để\s+)?(?:anh|chị|tôi|mình|em)?\s*hỏi\s+(?:ông xã|chồng)\b[^.!?;,]*", "cần hỏi chồng"),
        (r"(?i)\b(?:để\s+)?(?:anh|chị|tôi|mình|em)?\s*hỏi\s+(?:bà xã|vợ)\b[^.!?;,]*", "cần hỏi vợ"),
        (r"(?i)\b(?:chị|anh|tôi|mình|em)?\s*cân nhắc thêm\b[^.!?;,]*", "cần cân nhắc thêm"),
    ):
        b_match = re.search(pattern, safe_text)
        if b_match:
            candidates.append((Slot.BLOCKER, norm_blocker, b_match.group(0).strip()))
            break
    added: list[ProfileFactCandidate] = []
    for key, value, quote in candidates:
        if key in present_keys:
            continue
        ev = fact_evidence(key, value, "set", safe_text, [], quote)
        if ev.source == "customer":
            try:
                added.append(ProfileFactCandidate(
                    key=key,
                    value=ev.normalized_value if ev.normalized_value is not None else value,
                    source_kind="customer",
                    source_turn_id=turn_id,
                    evidence_quote=ev.evidence_quote or quote,
                    observed_on=observed_on,
                ))
                present_keys.add(key)
            except ValueError:
                continue
    return added
