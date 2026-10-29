"""Stateless LangMem proposal extraction; canonical writes happen elsewhere."""

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langmem import create_memory_manager

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


_INSTRUCTIONS = (
    "Extract only customer-stated durable facts and per-call events from the supplied "
    "Vietnamese telesale turns. Preserve source turn IDs, quote dates, and successful "
    "tool names. Do not infer facts from questions, jokes, hypotheticals, or another "
    "person's words. Distinguish a historical quoted price from a current price. "
    "Use the exact schema slot keys, especially has_children, budget_vnd and "
    "room_area_m2. Convert Vietnamese amounts into integer VND and areas into "
    "integer square meters; quote the supporting customer phrase. Emit separate "
    "facts for separate supported slots. For a customer's goal or unresolved "
    "question/blocker, propose a CustomerCallEpisodeCandidate with exact source "
    "IDs and text spans. If the customer defers a decision pending another "
    "person's approval or information, record the stated dependency as an "
    "open blocker; a callback outcome alone does not preserve it. Return no "
    "memory when evidence is insufficient."
)


_OPAQUE_FIELDS = {"turn_id", "source_turn_id", "session_id", "customer_id",
                  "sku", "order_id", "scope_id"}


def _mask_payload(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _mask_payload(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_payload(item, field) for item in value]
    if isinstance(value, str):
        return value if field in _OPAQUE_FIELDS else mask_pii(value)
    return value


def _safe_content(value: Any) -> str:
    if not isinstance(value, str):
        return mask_pii(str(value))
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return mask_pii(value)
    return json.dumps(_mask_payload(payload), ensure_ascii=False)


async def extract_candidates(
    model: BaseChatModel, turns: list[dict], existing: list[dict]
) -> tuple[list[ProfileFactCandidate], CustomerCallEpisodeCandidate | None]:
    """Use LangMem to propose typed records without persistence side effects."""
    manager = create_memory_manager(
        model, schemas=[ProfileFactCandidate, CustomerCallEpisodeCandidate],
        instructions=_INSTRUCTIONS, enable_deletes=False)
    safe_turns = [{**turn, "content": _safe_content(turn.get("content", ""))}
                  for turn in turns]
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
    return facts, episode
