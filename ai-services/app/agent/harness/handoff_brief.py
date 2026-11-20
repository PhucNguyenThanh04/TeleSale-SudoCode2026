
import re
from datetime import datetime
from typing import Callable

from pydantic import ValidationError

from app.agent.guardrails.checks import mask_pii, safe_tool_result
from app.agent.harness.state import TurnState
from app.schemas.brief import HandoffBrief
from app.mcp_servers.mcp_shared.commerce_evidence import build_commerce_evidence
from app.agent.guardrails.skus import known_skus


_PHONE = re.compile(r"^0[0-9]{9}$")
def _trusted_phone(state: TurnState) -> str | None:
    phone = state.get("customer_phone")
    if state.get("identity_status") == "known" and isinstance(phone, str) and _PHONE.fullmatch(phone):
        return phone
    request = state["request"]
    if request.channel == "hotline" and isinstance(request.channel_identity, str):
        phone = request.channel_identity
        if _PHONE.fullmatch(phone):
            return phone
    return None


def build_handoff_brief(state: TurnState, proposal: dict,
                        clock: Callable[[], datetime]) -> HandoffBrief | None:
    phone = _trusted_phone(state)
    if not phone:
        return None
    payload = safe_tool_result(proposal)
    scoped = state.get("scoped_facts") or {}
    products = scoped.get("product", {}) if isinstance(scoped, dict) else {}
    products = products if isinstance(products, dict) else {}
    calls = build_commerce_evidence(state)
    selected = payload.get("product_advised")
    if selected is not None and not isinstance(selected, str):
        return None
    profile = state.get("profile") or {}
    advised = profile.get("product_advised", {}).get("value")
    if selected is not None and selected not in {*products, *known_skus(calls), advised}:
        return None
    price = payload.get("price_quoted_vnd")
    if price is not None and type(price) is not int:
        return None
    if price is not None:
        prices = {call["result"].get("final_price_vnd") for call in calls
                  if call.get("name") == "pricing.get_quote"
                  and call.get("args", {}).get("sku") == selected}
        remembered = products.get(selected, {}).get("price_quoted_vnd", {}).get("value")
        if selected == advised:
            remembered = profile.get("price_quoted_vnd", {}).get("value", remembered)
        if not selected or price not in {*prices, remembered}:
            return None
    profile = state.get("profile") or {}
    confirmed = {key: fact["value"] for key, fact in profile.items()
                 if isinstance(fact, dict) and "value" in fact
                 and isinstance(fact["value"], (str, int, float, bool))
                 and mask_pii(str(fact["value"])) == str(fact["value"])}
    confirmed = dict(list(confirmed.items())[:10])
    rooms = scoped.get("room", {}) if isinstance(scoped, dict) else {}
    if isinstance(rooms, dict):
        safe_rooms = {room: {key: fact["value"] for key, fact in facts.items()
            if isinstance(fact, dict) and type(fact.get("value")) in {str, int, float, bool}
            and mask_pii(str(fact["value"])) == str(fact["value"])}
            for room, facts in list(rooms.items())[:4]
            if isinstance(room, str) and mask_pii(room) == room and isinstance(facts, dict)}
        if safe_rooms:
            confirmed["rooms"] = safe_rooms
    safe_products = {sku: {key: {field: fact[field] for field in ("value", "on", "source_kind")
            if field in fact and fact[field] is not None}
            for key, fact in facts.items() if isinstance(fact, dict)
            and type(fact.get("value")) in {str, int, float, bool}
            and mask_pii(str(fact["value"])) == str(fact["value"])}
            for sku, facts in list(products.items())[:4]
            if isinstance(sku, str) and mask_pii(sku) == sku and isinstance(facts, dict)}
    if safe_products:
        confirmed["products"] = safe_products
    try:
        return HandoffBrief.model_validate({**payload,
            "customer_phone": phone,
            "customer_name": state.get("customer_name") if state.get("identity_status") == "known" else None,
            "customer_id": state.get("customer_id") if state.get("identity_status") == "known" else None,
            "channel": state["request"].channel,
            "product_advised": selected,
            "price_quoted_vnd": price,
            "generated_at": clock(),
            "facts_confirmed": confirmed,
            "history_refs": [str(item["session_id"]) for item in state.get("episodes", [])[:5]
                             if isinstance(item, dict) and item.get("session_id")],
        })
    except ValidationError:
        return None
