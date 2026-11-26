
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
            or 'error' in result or result.get('ok') is False or result.get('success') is False
            or not isinstance(result.get('order_id'), str) or not result['order_id'].strip()):
        return []
    facts = []
    order_id = result.get("order_id")
    if isinstance(order_id, str) and order_id and mask_pii(order_id) == order_id:
        order_fact = {"key": "order_id", "value": order_id, "op": "set",
                      "source_kind": "tool", "source_tool": "order.create",
                      "source_turn_id": source_turn_id,
                      "scope_type": "global", "scope_id": "",
                      "evidence_quote": f"order.create:order_id:{order_id}"}
        if _valid_fact(order_fact):
            facts.append(order_fact)
    sku = args.get("sku")
    if isinstance(variant, dict) and variant.get("variant_sku") == sku:
        parent = variant.get("parent_sku")
        if not isinstance(parent, str) or not parent:
            return facts
        size = variant.get("size")
        if isinstance(size, str) and size.isdecimal():
            size = int(size)
        values = {"product_advised": parent, "variant_sku": sku, "size": size,
                  "color": variant.get("color"), "payment": args.get("payment")}
    elif isinstance(sku, str) and sku:
        parent = sku
        values = {"product_advised": parent, "payment": args.get("payment")}
    else:
        return facts
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
                action_row = {
                    "action": "order.create",
                    "order_id": order_id,
                    "status": "created",
                    "sku": sku if isinstance(sku, str) else "",
                }
                if type(result.get("total_vnd")) is int:
                    action_row["total_vnd"] = result["total_vnd"]
                if isinstance(args.get("payment"), str) and args["payment"]:
                    action_row["payment"] = args["payment"]
                if isinstance(result.get("estimated_delivery"), str) and result["estimated_delivery"]:
                    action_row["estimated_delivery"] = result["estimated_delivery"]
                actions.append(action_row)
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
