"""Apply evidence-backed updates to a bounded, structured session episode."""

from copy import deepcopy
from uuid import UUID, uuid5

from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_shared.episode_evidence import evidence_supports


_SCOPES = {"unknown", "global", "product", "room"}
_KINDS = {"question", "blocker"}


class EpisodeCapacityError(ValueError):
    """The bounded episode is full; the verified turn can still be committed."""


def _safe_text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("invalid episode text")
    if mask_pii(value) != value:
        raise ValueError("episode text contains PII")
    return value.strip()


def _evidence(quote: object, customer_text: str, agent_text: str) -> str:
    value = _safe_text(quote, 200)
    if value.casefold() not in customer_text.casefold() and value.casefold() not in agent_text.casefold():
        raise ValueError("episode evidence is not in current turn")
    return value


def apply_episode_delta(previous: dict, delta: dict, *, source_turn_id: str,
                        customer_text: str, agent_text: str,
                        prior_open_items: dict[str, tuple[str, str]] | None = None) -> dict:
    """Return an updated state; never mutate the source on invalid input."""
    try:
        UUID(source_turn_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid source turn") from exc
    if not isinstance(previous, dict) or not isinstance(delta, dict):
        raise ValueError("invalid episode state")
    updates = delta.get("topic_updates", [])
    if not isinstance(updates, list) or len(updates) > 8:
        raise ValueError("too many episode topic updates")
    state = deepcopy(previous) if previous else {"topics": []}
    state.setdefault("resolved_prior_items", [])
    topics = state.get("topics")
    if not isinstance(topics, list) or len(topics) > 24:
        raise ValueError("invalid episode topics")
    for update_no, update in enumerate(updates):
        if not isinstance(update, dict):
            raise ValueError("invalid topic update")
        scope_type, scope_id = update.get("scope_type"), update.get("scope_id", "")
        if (scope_type not in _SCOPES or not isinstance(scope_id, str)
                or (scope_type in {"unknown", "global"} and scope_id)
                or (scope_type in {"product", "room"} and
                    (not scope_id or len(scope_id) > 80 or mask_pii(scope_id) != scope_id))):
            raise ValueError("invalid episode scope")
        topic = next((item for item in topics if item.get("scope_type") == scope_type
                      and item.get("scope_id") == scope_id), None)
        if topic is None:
            if len(topics) >= 24:
                raise EpisodeCapacityError("too many episode topics")
            topic = {"scope_type": scope_type, "scope_id": scope_id,
                     "customer_goal": "", "advice_given": "", "next_step": "", "items": []}
            topics.append(topic)
        for field in ("customer_goal", "advice_given", "next_step"):
            if field in update:
                quote = _evidence(update.get("narrative_evidence_quote"),
                                  customer_text, agent_text)
                value = _safe_text(update[field], 300)
                if not evidence_supports(value, quote):
                    raise ValueError("episode narrative lacks supporting evidence")
                topic[field] = value
                topic["narrative_source_turn_id"] = source_turn_id
                topic["narrative_evidence_quote"] = quote
        additions, resolutions = update.get("add_items", []), update.get("resolve_items", [])
        if (not isinstance(additions, list) or len(additions) > 8
                or not isinstance(resolutions, list) or len(resolutions) > 8):
            raise ValueError("invalid episode items")
        items = topic["items"]
        if not isinstance(items, list) or len(items) + len(additions) > 40:
            raise EpisodeCapacityError("too many episode items")
        for item_no, addition in enumerate(additions):
            if not isinstance(addition, dict) or addition.get("kind") not in _KINDS:
                raise ValueError("invalid episode item")
            quote = _evidence(addition.get("evidence_quote"), customer_text, "")
            value = _safe_text(addition.get("text"), 300)
            if not evidence_supports(value, quote):
                raise ValueError("episode item lacks supporting evidence")
            item_id = str(uuid5(UUID(source_turn_id), f"{update_no}:{item_no}"))
            if any(item.get("item_id") == item_id for item in items):
                continue
            items.append({"item_id": item_id, "kind": addition["kind"],
                          "text": value,
                          "status": "open", "source_turn_id": source_turn_id,
                          "evidence_quote": quote})
        for resolution in resolutions:
            if not isinstance(resolution, dict):
                raise ValueError("invalid resolution")
            target = next((item for item in items if item.get("item_id") == resolution.get("item_id")), None)
            if target is None:
                item_id = resolution.get("item_id")
                if (not isinstance(item_id, str)
                        or (prior_open_items or {}).get(item_id) != (scope_type, scope_id)):
                    raise ValueError("resolution target missing from topic")
                quote = _evidence(resolution.get("evidence_quote"), customer_text, agent_text)
                if not any(item.get("item_id") == item_id for item in state["resolved_prior_items"]):
                    if len(state["resolved_prior_items"]) >= 100:
                        raise EpisodeCapacityError("too many prior resolutions")
                    state["resolved_prior_items"].append({"item_id": item_id,
                        "source_turn_id": source_turn_id, "evidence_quote": quote})
                continue
            quote = _evidence(resolution.get("evidence_quote"), customer_text, agent_text)
            if not evidence_supports(target.get("text", ""), quote):
                raise ValueError("episode resolution lacks supporting evidence")
            target["status"] = "resolved"
            target["resolved_turn_id"] = source_turn_id
            target["resolution_evidence_quote"] = quote
    return state
