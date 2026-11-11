"""Evidence-checked customer facts shared by immediate reads and background extraction.

No model invocation or LangMem import is required for these deterministic proposals.
"""
import json
import re
from datetime import date
from typing import Any
from app.agent.guardrails.checks import (
    _AREA_UNIT, _EXPENSIVE_PHRASE, _SPOKEN_AREA, _spoken_integer,
    customer_budget_amounts, fact_evidence,
)
from app.constants import Slot
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.schemas.langmem import ProfileFactCandidate


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

