"""Stateless LangMem proposal extraction; canonical writes happen elsewhere."""

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
    "Return no memory when evidence is insufficient."
)


async def extract_candidates(
    model: BaseChatModel, turns: list[dict], existing: list[dict]
) -> tuple[list[ProfileFactCandidate], CustomerCallEpisodeCandidate | None]:
    """Use LangMem to propose typed records without persistence side effects."""
    manager = create_memory_manager(
        model, schemas=[ProfileFactCandidate, CustomerCallEpisodeCandidate],
        instructions=_INSTRUCTIONS, enable_deletes=False)
    safe_turns = [{**turn, "content": mask_pii(str(turn.get("content", "")))}
                  for turn in turns]
    result = await manager.ainvoke({"messages": safe_turns, "existing": existing})
    facts = []
    episode = None
    for item in result:
        content: Any = getattr(item, "content", None)
        if isinstance(content, ProfileFactCandidate):
            facts.append(content)
        elif isinstance(content, CustomerCallEpisodeCandidate):
            episode = content
    return facts, episode
