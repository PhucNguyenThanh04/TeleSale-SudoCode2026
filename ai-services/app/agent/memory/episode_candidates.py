"""Validate model proposals for unresolved session issues."""

from app.agent.guardrails.checks import mask_pii
from app.agent.memory.fact_candidates import blocker_resolution
from app.mcp_servers.mcp_shared.episode_evidence import evidence_supports


def outcome_from_tool_calls(tool_calls: list[dict]) -> str:
    for call in reversed(tool_calls):
        if not isinstance(call, dict) or not isinstance(call.get("result"), dict):
            continue
        result = call["result"]
        if "error" in result:
            continue
        if (call.get("name") == "order.create" and result.get("status") == "created"
                and isinstance(result.get("order_id"), str) and result["order_id"]):
            return "chot_don"
        if (call.get("name") == "handoff.transfer" and result.get("status") == "queued"
                and isinstance(result.get("ticket_id"), str) and result["ticket_id"]):
            return "chuyen_may"
        if (call.get("name") == "schedule.callback"
                and isinstance(result.get("callback_id"), str) and result["callback_id"]):
            return "hen_goi_lai"
    return "khac"


def blocker_episode_delta(customer_text: str, facts: list[dict],
                          current_episode: dict, proposed_delta: dict) -> dict:
    """Carry a verified decision delay into the session record once."""
    existing = {str(item.get("text", "")).casefold().strip()
                for topic in current_episode.get("topics", [])
                if isinstance(topic, dict) for item in topic.get("items", [])
                if isinstance(item, dict) and item.get("kind") == "blocker"
                and item.get("status") == "open"}
    for update in proposed_delta.get("topic_updates", []):
        for item in update.get("add_items", []):
            if isinstance(item, dict) and item.get("kind") == "blocker":
                existing.add(str(item.get("text", "")).casefold().strip())
    additions = []
    for fact in facts:
        value = fact.get("value")
        if (fact.get("key") != "blocker" or fact.get("op") != "set"
                or fact.get("source_kind") != "customer" or not isinstance(value, str)
                or value.casefold().strip() in existing):
            continue
        quote = fact.get("evidence_quote")
        if not (_safe(quote, 200, customer_text) and evidence_supports(value, quote)):
            quote = customer_text if _safe(customer_text, 200) else None
        if quote and evidence_supports(value, quote):
            additions.append({"kind": "blocker", "text": value,
                              "evidence_quote": quote})
            existing.add(value.casefold().strip())
    return {"topic_updates": [{"scope_type": "unknown", "scope_id": "",
                                "add_items": additions[:8]}]} if additions else {}


def resolved_blocker_episode_delta(customer_text: str, current_episode: dict,
                                   prior_episodes: list[dict], proposed_delta: dict) -> dict:
    """Close only a specific decision delay supported by the customer's reply."""
    if not _safe(customer_text, 200):
        return {}
    already = {resolution.get("item_id")
               for update in proposed_delta.get("topic_updates", [])
               for resolution in update.get("resolve_items", [])
               if isinstance(resolution, dict)}
    updates = []
    for episode in [current_episode, *prior_episodes]:
        for topic in episode.get("topics", []) if isinstance(episode, dict) else []:
            if not isinstance(topic, dict):
                continue
            resolutions = []
            for item in topic.get("items", []):
                if (not isinstance(item, dict) or item.get("kind") != "blocker"
                        or item.get("status") != "open" or not item.get("item_id")
                        or item["item_id"] in already):
                    continue
                resolved, _ = blocker_resolution(customer_text, {
                    "blocker": {"value": item.get("text", "")}})
                if resolved:
                    resolutions.append({"item_id": item["item_id"],
                                        "evidence_quote": customer_text})
                    already.add(item["item_id"])
            if resolutions:
                updates.append({"scope_type": topic.get("scope_type", "unknown"),
                                "scope_id": topic.get("scope_id", ""),
                                "resolve_items": resolutions[:8]})
    return {"topic_updates": updates[:8]} if updates else {}


def _safe(value: object, limit: int, turn: str | None = None) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and mask_pii(value) == value
            and (turn is None or value.casefold() in turn.casefold()))


def accepted_episode_delta(customer_text: str, agent_text: str, proposal: object,
                           current_episode: dict, tool_calls: list[dict],
                           *, prior_episodes: list[dict] | None = None) -> dict:
    if not isinstance(proposal, dict) or not isinstance(proposal.get("topic_updates"), list):
        return {}
    source = f"{customer_text}\n{agent_text}"
    known = {(topic.get("scope_type"), topic.get("scope_id"))
             for topic in current_episode.get("topics", []) if isinstance(topic, dict)}
    prior_episodes = prior_episodes or []
    known.update((topic.get("scope_type"), topic.get("scope_id"))
                 for episode in prior_episodes if isinstance(episode, dict)
                 for topic in episode.get("topics", []) if isinstance(topic, dict))
    resolved_prior = {item.get("item_id") for episode in prior_episodes
                      if isinstance(episode, dict)
                      for item in episode.get("resolved_prior_items", [])
                      if isinstance(item, dict)}
    known_products = {str(call.get("args", {}).get("sku")) for call in tool_calls
                      if isinstance(call, dict) and isinstance(call.get("args"), dict)
                      and call["args"].get("sku")}
    result = []
    for update in proposal["topic_updates"][:8]:
        if not isinstance(update, dict):
            continue
        scope, scope_id = update.get("scope_type", "unknown"), update.get("scope_id", "")
        if scope not in {"unknown", "global", "product", "room"} or not isinstance(scope_id, str):
            continue
        if scope in {"unknown", "global"} and scope_id:
            continue
        if scope in {"product", "room"}:
            if not _safe(scope_id, 80):
                continue
            referenced = (scope, scope_id) in known or scope_id.casefold() in source.casefold()
            if scope == "product":
                referenced = referenced or scope_id in known_products
            else:
                referenced = referenced or scope_id.replace("_", " ").casefold() in source.casefold()
            if not referenced:
                continue
        accepted = {"scope_type": scope, "scope_id": scope_id}
        for field in ("customer_goal", "advice_given", "next_step"):
            if field in update and _safe(update[field], 300):
                quote = update.get("narrative_evidence_quote")
                if _safe(quote, 200, source) and evidence_supports(update[field], quote):
                    accepted[field] = update[field]
                    accepted["narrative_evidence_quote"] = quote
        additions = []
        for item in update.get("add_items", [])[:8] if isinstance(update.get("add_items", []), list) else []:
            if (isinstance(item, dict) and item.get("kind") in {"question", "blocker"}
                    and _safe(item.get("text"), 300)
                    and _safe(item.get("evidence_quote"), 200, customer_text)
                    and evidence_supports(item["text"], item["evidence_quote"])):
                additions.append({"kind": item["kind"], "text": item["text"],
                                  "evidence_quote": item["evidence_quote"]})
        resolutions = []
        for item in update.get("resolve_items", [])[:8] if isinstance(update.get("resolve_items", []), list) else []:
            if not isinstance(item, dict) or not _safe(item.get("evidence_quote"), 200, source):
                continue
            if (item.get("item_id") not in resolved_prior and any(
                   old.get("item_id") == item.get("item_id") and old.get("status") == "open"
                   and evidence_supports(old.get("text", ""), item["evidence_quote"])
                   for episode in [current_episode, *prior_episodes] if isinstance(episode, dict)
                   for topic in episode.get("topics", [])
                   if isinstance(topic, dict) and topic.get("scope_type") == scope
                   and topic.get("scope_id") == scope_id
                   for old in topic.get("items", []) if isinstance(old, dict))):
                resolutions.append({"item_id": item["item_id"],
                                    "evidence_quote": item["evidence_quote"]})
        if additions:
            accepted["add_items"] = additions
        if resolutions:
            accepted["resolve_items"] = resolutions
        if len(accepted) > 2:
            result.append(accepted)
    return {"topic_updates": result} if result else {}
