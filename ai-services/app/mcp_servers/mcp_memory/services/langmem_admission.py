"""Admit typed LangMem proposals only when committed evidence supports them."""

from app.agent.guardrails.checks import fact_evidence
from app.mcp_servers.mcp_memory.services.memory import _valid_fact
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
            candidate.evidence_quote)
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
        identity = (candidate.scope_type, scope_id, candidate.key)
        if identity in seen and seen[identity] != value:
            rejected.append({"key": candidate.key, "reason": "conflicting_values"})
            accepted = [item for item in accepted if
                        (item["scope_type"], item["scope_id"], item["key"]) != identity]
            continue
        if not _valid_fact(fact):
            rejected.append({"key": candidate.key, "reason": "invalid_fact"})
            continue
        seen[identity] = value
        accepted.append(fact)
    return accepted, rejected


def admit_episode_candidate(
    customer_id: str, session_id: str, candidate: CustomerCallEpisodeCandidate,
    committed_turns: list[dict], tool_calls: list[dict]
) -> dict | None:
    if candidate.customer_id != customer_id or candidate.session_id != session_id:
        return None
    turns = [_turn_for(committed_turns, customer_id, session_id, turn_id)
             for turn_id in candidate.source_turn_ids]
    if not turns or any(turn is None for turn in turns):
        return None
    source = "\n".join(turn.get("customer_text", "") for turn in turns)
    additions = []
    for blocker in candidate.open_blockers:
        if blocker and blocker.casefold() in source.casefold():
            additions.append({"kind": "blocker", "text": blocker,
                              "evidence_quote": blocker})
    for question in candidate.open_questions:
        if question and question.casefold() in source.casefold():
            additions.append({"kind": "question", "text": question,
                              "evidence_quote": question})
    update = {"scope_type": "unknown", "scope_id": ""}
    if candidate.customer_goal and candidate.customer_goal.casefold() in source.casefold():
        update["customer_goal"] = candidate.customer_goal
        update["narrative_evidence_quote"] = candidate.customer_goal
    if additions:
        update["add_items"] = additions[:8]
    if len(update) == 2:
        return None
    return {"topic_updates": [update]}
