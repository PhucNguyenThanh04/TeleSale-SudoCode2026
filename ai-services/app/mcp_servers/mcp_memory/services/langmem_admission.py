"""Admit typed LangMem proposals only when committed evidence supports them."""

from app.agent.guardrails.checks import fact_evidence
from app.mcp_servers.mcp_memory.services.memory import _valid_fact
from app.mcp_servers.mcp_shared.episode_evidence import evidence_supports
from app.schemas.langmem import ProfileFactCandidate, CustomerCallEpisodeCandidate


def _turn_for(turns: list[dict], customer_id: str, session_id: str,
              turn_id: str) -> dict | None:
    return next((turn for turn in turns if str(turn.get("turn_id")) == turn_id
                 and turn.get("customer_id") == customer_id
                 and turn.get("session_id") == session_id), None)


def admit_profile_candidates(
    customer_id: str, session_id: str, candidates: list[ProfileFactCandidate],
    committed_turns: list[dict], tool_calls: list[dict]
) -> tuple[list[dict], list[dict]]:
    accepted = []
    rejected = []
    seen = {}
    conflicted = set()
    for candidate in candidates:
        turn = _turn_for(committed_turns, customer_id, session_id,
                         candidate.source_turn_id)
        if turn is None:
            rejected.append({"key": candidate.key, "reason": "identity_mismatch"})
            continue
        relevant_calls = [call for call in tool_calls
                          if call.get("source_turn_id") == candidate.source_turn_id
                          and isinstance(call.get("result"), dict)
                          and "error" not in call["result"]]
        evidence = fact_evidence(candidate.key, candidate.value,
            "delete" if candidate.op == "delete" else "set",
            turn.get("customer_text", ""), relevant_calls,
            candidate.evidence_quote if candidate.source_kind == "customer" else None)
        source = evidence.source
        if not source or (candidate.source_kind == "customer" and source != "customer") \
                or (candidate.source_kind == "tool" and
                    source != f"tool:{candidate.source_tool}"):
            rejected.append({"key": candidate.key,
                             "reason": str(evidence.reason or "source_mismatch")})
            continue
        value = evidence.normalized_value if candidate.op != "delete" else candidate.value
        scope_id = "" if candidate.scope_type == "global" else candidate.scope_id
        fact = {"key": candidate.key, "value": value, "op": candidate.op,
                "source_kind": candidate.source_kind,
                "evidence_quote": candidate.evidence_quote,
                "source_turn_id": candidate.source_turn_id,
                "scope_type": candidate.scope_type, "scope_id": scope_id}
        if candidate.source_tool:
            fact["source_tool"] = candidate.source_tool
        if candidate.key == "promo_expiry" and isinstance(value, str):
            fact["valid_until"] = value
        elif candidate.valid_until and candidate.source_kind == "tool":
            fact["valid_until"] = candidate.valid_until.isoformat()
        identity = (candidate.scope_type, scope_id, candidate.key)
        if not _valid_fact(fact):
            rejected.append({"key": candidate.key, "reason": "invalid_fact"})
            continue
        if identity in conflicted or identity in seen and seen[identity] != value:
            conflicted.add(identity)
            rejected.append({"key": candidate.key, "reason": "conflicting_values"})
            accepted = [item for item in accepted if
                        (item["scope_type"], item["scope_id"], item["key"]) != identity]
            continue
        if identity in seen:
            continue
        seen[identity] = value
        accepted.append(fact)
    return accepted, rejected


def _known_skus(tool_calls: list[dict]) -> set[str]:
    skus: set[str] = set()
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        args = call.get("args")
        if isinstance(args, dict) and isinstance(args.get("sku"), str) and args["sku"]:
            skus.add(args["sku"].casefold())
        result = call.get("result")
        if not isinstance(result, dict) or "error" in result:
            continue
        if isinstance(result.get("sku"), str) and result["sku"]:
            skus.add(result["sku"].casefold())
        for item in result.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("sku"), str) and item["sku"]:
                skus.add(item["sku"].casefold())
                for variant in item.get("variants") or []:
                    if isinstance(variant, dict) and isinstance(variant.get("variant_sku"), str):
                        skus.add(variant["variant_sku"].casefold())
    return skus


def _product_allowed(scope_id: str, customer_source: str, agent_source: str,
                     known_skus: set[str]) -> bool:
    if not scope_id:
        return False
    lowered = scope_id.casefold()
    if lowered in known_skus or any(sku.startswith(lowered + "-") for sku in known_skus):
        return True
    return lowered in customer_source.casefold() or lowered in agent_source.casefold()


def _valid_customer_item(text: str, quote: str, customer_source: str) -> bool:
    if not text or not quote:
        return False
    if quote.casefold() not in customer_source.casefold():
        return False
    if quote.casefold() == text.casefold():
        return True
    return evidence_supports(text, quote)


def _valid_narrative(text: str, quote: str, customer_source: str,
                     agent_source: str) -> bool:
    if not text or not quote:
        return False
    in_turn = (quote.casefold() in customer_source.casefold()
               or quote.casefold() in agent_source.casefold())
    if not in_turn:
        return False
    if quote.casefold() == text.casefold():
        return True
    return evidence_supports(text, quote)


def admit_episode_candidate(
    customer_id: str, session_id: str, candidate: CustomerCallEpisodeCandidate,
    committed_turns: list[dict], tool_calls: list[dict],
    prior_open_items: dict[str, tuple[str, str]] | None = None,
) -> dict | None:
    if candidate.customer_id != customer_id or candidate.session_id != session_id:
        return None
    turns = [_turn_for(committed_turns, customer_id, session_id, turn_id)
             for turn_id in candidate.source_turn_ids]
    if not turns or any(turn is None for turn in turns):
        return None
    customer_source = "\n".join(turn.get("customer_text", "") for turn in turns)
    agent_source = "\n".join(turn.get("agent_text", "") for turn in turns)
    known_skus = _known_skus(tool_calls)
    prior_map = prior_open_items or {}
    updates_by_scope: dict[tuple[str, str], dict] = {}

    def get_update(scope_type: str, scope_id: str) -> dict:
        key = (scope_type, scope_id)
        if key not in updates_by_scope:
            updates_by_scope[key] = {"scope_type": scope_type, "scope_id": scope_id}
        return updates_by_scope[key]

    for topic in candidate.topics:
        scope_type = topic.scope_type
        scope_id = topic.scope_id
        if scope_type == "product" and not _product_allowed(
                scope_id, customer_source, agent_source, known_skus):
            scope_type, scope_id = "global", ""
        elif scope_type == "global":
            scope_id = ""
        upd = get_update(scope_type, scope_id)
        if topic.consultation is not None and scope_type == 'global':
            from app.mcp_servers.mcp_shared.consultation import admit_consultation
            snapshot=admit_consultation(topic.consultation.model_dump(mode='json',exclude_unset=True),
                customer_id=customer_id,session_id=session_id,committed_turns=turns,tool_calls=tool_calls)
            if snapshot:
                upd['consultation']=snapshot
        for field in ("customer_goal", "advice_given", "next_step"):
            ev = getattr(topic, field, None)
            if ev is not None and _valid_narrative(
                    ev.text, ev.evidence_quote, customer_source, agent_source):
                upd[field] = ev.text
                upd.setdefault("narrative_evidence_quotes", {})[field] = ev.evidence_quote
        for item in topic.open_items:
            if _valid_customer_item(item.text, item.evidence_quote, customer_source):
                upd.setdefault("add_items", [])
                if len(upd["add_items"]) < 8:
                    upd["add_items"].append({
                        "kind": item.kind,
                        "text": item.text,
                        "evidence_quote": item.evidence_quote,
                    })
        for res in topic.resolved_items:
            if res.item_id not in prior_map:
                continue
            in_turn = (res.evidence_quote.casefold() in customer_source.casefold()
                       or res.evidence_quote.casefold() in agent_source.casefold())
            if not in_turn:
                continue
            target_scope, target_id = prior_map[res.item_id]
            target_upd = get_update(target_scope, target_id)
            target_upd.setdefault("resolve_items", [])
            if len(target_upd["resolve_items"]) < 8 and not any(
                    r["item_id"] == res.item_id for r in target_upd["resolve_items"]):
                target_upd["resolve_items"].append({
                    "item_id": res.item_id,
                    "evidence_quote": res.evidence_quote,
                })

    additions = []
    for blocker in candidate.open_blockers:
        text = blocker.text if hasattr(blocker, "text") else str(blocker)
        quote = blocker.evidence_quote if hasattr(blocker, "evidence_quote") else text
        if _valid_customer_item(text, quote, customer_source):
            additions.append({"kind": "blocker", "text": text,
                              "evidence_quote": quote})
    for question in candidate.open_questions:
        text = question.text if hasattr(question, "text") else str(question)
        quote = question.evidence_quote if hasattr(question, "evidence_quote") else text
        if _valid_customer_item(text, quote, customer_source):
            additions.append({"kind": "question", "text": text,
                              "evidence_quote": quote})
    if candidate.customer_goal or additions:
        upd = get_update("unknown", "")
        if candidate.customer_goal:
            goal_text = (candidate.customer_goal.text
                         if hasattr(candidate.customer_goal, "text")
                         else str(candidate.customer_goal))
            goal_quote = (candidate.customer_goal.evidence_quote
                          if hasattr(candidate.customer_goal, "evidence_quote")
                          else goal_text)
            if _valid_narrative(goal_text, goal_quote, customer_source, agent_source):
                upd["customer_goal"] = goal_text
                upd.setdefault("narrative_evidence_quotes", {})["customer_goal"] = goal_quote
        if additions:
            upd.setdefault("add_items", [])
            for item in additions:
                if len(upd["add_items"]) < 8:
                    upd["add_items"].append(item)

    valid_updates = [upd for upd in updates_by_scope.values() if len(upd) > 2]
    if not valid_updates:
        return None
    return {"topic_updates": valid_updates[:8]}
