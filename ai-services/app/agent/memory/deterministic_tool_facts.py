
from datetime import date

from app.agent.guardrails.checks import fact_evidence
from app.agent.memory.reported_facts import reported_tool_candidates
from app.mcp_servers.mcp_shared.pii import mask_pii
from app.mcp_servers.mcp_memory.services.memory import _valid_fact
from app.schemas.langmem import ProfileFactCandidate


def verified_tool_candidates(agent_text: str, calls: list[dict],
                             source_turn_id: str, on: str) -> list[ProfileFactCandidate]:
    proposals = []
    seen = set()
    for item in reported_tool_candidates(agent_text, calls):
        key, value = item["key"], item["value"]
        if isinstance(value, str) and mask_pii(value) != value:
            continue
        evidence = fact_evidence(key, value, "set", "", calls)
        if not isinstance(evidence.source, str) or not evidence.source.startswith("tool:"):
            continue
        scope_type = item.get("scope_type", "global")
        scope_id = item.get("scope_id", "")
        identity = (scope_type, scope_id, key, value)
        if identity in seen:
            continue
        seen.add(identity)
        source_tool = evidence.source.removeprefix("tool:")
        valid_until = None
        if key == "promo_expiry" and isinstance(value, str):
            try:
                valid_until = date.fromisoformat(value)
            except ValueError:
                valid_until = None
        try:
            proposals.append(ProfileFactCandidate(
                key=key, value=value, source_kind="tool", source_tool=source_tool,
                source_turn_id=source_turn_id, observed_on=date.fromisoformat(on),
                scope_type=scope_type, scope_id=scope_id,
                evidence_quote=f"{source_tool}:{value}",
                valid_until=valid_until))
        except ValueError:
            continue
    return proposals


def verified_order_details(call: dict, variant: dict | None,
                           source_turn_id: str) -> list[dict]:
    result = call.get("result", {})
    args = call.get("args", {})
    if (call.get("name") != "order.create" or not isinstance(result, dict)
            or result.get("status") != "created" or not isinstance(args, dict)
            or not isinstance(variant, dict)
            or variant.get("variant_sku") != args.get("sku")):
        return []
    parent = variant.get("parent_sku")
    if not isinstance(parent, str) or not parent:
        return []
    size = variant.get("size")
    if isinstance(size, str) and size.isdecimal():
        size = int(size)
    values = {"product_advised": parent, "variant_sku": args.get("sku"), "size": size,
              "color": variant.get("color"), "payment": args.get("payment")}
    facts = []
    for key, value in values.items():
        if type(value) not in {str, int} or (isinstance(value, str)
                                             and mask_pii(value) != value):
            continue
        fact = {"key": key, "value": value, "op": "set",
                "source_kind": "tool", "source_tool": "order.create",
                "source_turn_id": source_turn_id,
                "scope_type": "product", "scope_id": parent,
                "evidence_quote": f"order.create:{key}:{value}"}
        if _valid_fact(fact):
            facts.append(fact)
    return facts


def verified_variant_details(call: dict, variant: dict | None,
                             source_turn_id: str) -> list[dict]:
    result = call.get("result", {})
    args = call.get("args", {})
    sku = (result.get("sku") if isinstance(result, dict) else None) or (
        args.get("sku") if isinstance(args, dict) else None)
    if (call.get("name") not in {"inventory.check", "pricing.get_quote"}
            or not isinstance(result, dict) or "error" in result
            or not isinstance(variant, dict)
            or variant.get("variant_sku") != sku):
        return []
    parent = variant.get("parent_sku")
    if not isinstance(parent, str) or not parent:
        return []
    size = variant.get("size")
    if isinstance(size, str) and size.isdecimal():
        size = int(size)
    values = {"product_advised": parent, "variant_sku": sku,
              "size": size, "color": variant.get("color")}
    facts = []
    for key, value in values.items():
        if type(value) not in {str, int} or (isinstance(value, str)
                                             and mask_pii(value) != value):
            continue
        fact = {"key": key, "value": value, "op": "set",
                "source_kind": "tool", "source_tool": call["name"],
                "source_turn_id": source_turn_id,
                "scope_type": "product", "scope_id": parent,
                "evidence_quote": f"{call['name']}:{key}:{value}"}
        if _valid_fact(fact):
            facts.append(fact)
    return facts


def deterministic_episode_tools(calls: list[dict], on: str) -> tuple[list[dict], list[dict]]:
    actions: list[dict] = []
    quotes: list[dict] = []
    seen_quotes: set[tuple[str, int, str]] = set()
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        result = call.get("result") if isinstance(call.get("result"), dict) else {}
        if not result or "error" in result:
            continue
        if name == "order.create" and result.get("status") == "created":
            order_id = result.get("order_id")
            sku = args.get("sku")
            if isinstance(order_id, str) and order_id:
                actions.append({"action": "order.create", "order_id": order_id,
                                "sku": sku if isinstance(sku, str) else ""})
        elif (name == "schedule.callback" and isinstance(result.get('callback_id'), str)
              and result['callback_id'] and result.get("status") in {None, "scheduled", "ok", "created"}):
            actions.append({"action": "schedule.callback",
                            "callback_id": str(result.get("callback_id", "")),
                            **({'callback_at': result['callback_at']} if result.get('callback_at') else {})})
        elif name == "handoff.transfer" and result.get("status") in {"queued", "transferred", "ok"}:
            actions.append({"action": "handoff.transfer",
                            "ticket_id": str(result.get("ticket_id", ""))})
        elif name == "pricing.get_quote":
            sku = result.get("sku") or args.get("sku")
            price = result.get("final_price_vnd")
            quoted_on = str(args.get("on") or on)
            if isinstance(sku, str) and sku and type(price) is int and price >= 0:
                ident = (sku, price, quoted_on)
                if ident not in seen_quotes:
                    seen_quotes.add(ident)
                    quotes.append({
                        "sku": sku,
                        "price_vnd": price,
                        "quoted_on": quoted_on,
                        "source_tool": "pricing.get_quote",
                    })
    return actions, quotes
