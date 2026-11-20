
import json
import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langmem import create_memory_manager

from app.agent.prompts import MEMORY_PROMPT, text_prompt
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


_INSTRUCTIONS = (
    "Extract customer-stated facts and call narratives using only the supplied typed schemas. "
    "The current committed source turn is the only new evidence; history is interpretation "
    "context and must not create new source turns. Cite its exact IDs and literal masked "
    "evidence quotes. Convert explicitly stated amounts and units into the schema's numeric "
    "units. Record uncertain or conditional statements as such; do not turn questions, "
    "hypotheticals, negations or third-party statements into customer facts. "
    "Tool observations supply commercial facts and completed actions separately; do not "
    "invent prices, inventory, orders, customer selections or permission from advice. "
    "Customer goals come from customer speech; advice comes from assistant speech. "
    "Use scoped topics for the products/rooms actually discussed. Open items retain the "
    "customer's stated dependencies or unanswered questions. Resolve a prior item only when "
    "the current turn supports resolution, copying its supplied item ID and evidence quote. "
    "Next steps are historical plans, never authorization to execute a tool. "
    "Return no proposal when the evidence does not support one."
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
    return facts, episode
