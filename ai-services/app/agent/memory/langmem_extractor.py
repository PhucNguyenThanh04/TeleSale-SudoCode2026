"""Stateless LangMem proposal extraction; canonical writes happen elsewhere."""

import json
import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langmem import create_memory_manager

from app.agent.memory.customer_facts import _supplement_customer_facts
from app.agent.prompts import MEMORY_PROMPT, text_prompt
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


_INSTRUCTIONS = (
    "Only the current source turn is new evidence. reference_context.previous_agent_text "
    "is interpretation context, not a customer fact and never a new source turn. "
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
    "latest turn and cite its turn ID. Leave topic.consultation null; MCP derives it from committed evidence. advice_given records agent speech, not customer facts. Never infer customer selection or consent from advice, a tool quote, a resolved blocker or another person agreeing. presented_offer and accepted_offer are canonical MCP views, not LLM proposals."
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



# Consultation is optional in TopicProposal. MCP reconstructs/adopts it from
# committed evidence; model-generated summaries never authorize a purchase.
