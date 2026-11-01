"""Validate handoff episode proposals and derive committed-turn outcomes."""

import re
import unicodedata

from app.agent.guardrails.checks import mask_pii
from app.agent.memory.decision_makers import (
    BlockerResolutionReason, PERSON_PATTERN, person_mentions, roles_mentioned,
)
from app.mcp_servers.mcp_shared.episode_evidence import evidence_supports


def _fold(value: str) -> str:
    value = value.casefold().replace("đ", "d").replace("²", "2")
    return "".join(char for char in unicodedata.normalize("NFD", value)
                   if unicodedata.category(char) != "Mn")


_APPROVAL_TAIL = re.compile(
    r"(?:\s+(?:toi|anh|chi|em|minh|nha toi))?\s+"
    r"(?:da\s+)?(?:(chua|khong|tam)\s+)?"
    r"(?:dong y|chap nhan|ung ho|ok|gat dau|cho\s+roi)\b"
)
_RESOLUTION_CLAUSE = re.compile(r"[;,]|\b(?:nhung|va|ma)\b")
_RESOLUTION_HYPOTHETICAL = re.compile(r"\b(?:neu|gia su|lo|nho|vi du)\b")
_RESOLUTION_UNCERTAIN = re.compile(r"\b(?:khong biet|chua ro|chua biet)\b")
_RESOLUTION_QUESTION = re.compile(r"[?]|\b(?:duoc khong|phai khong|chua|khong a|a|ha|nhi)\s*$")


def blocker_resolution(customer_text: str, profile: dict[str, dict]
                       ) -> tuple[bool, BlockerResolutionReason]:
    prior = profile.get("blocker", {}).get("value")
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
