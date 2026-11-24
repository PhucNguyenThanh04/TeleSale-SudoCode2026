
import hashlib
import json
from typing import Any

from app.agent.harness.observability import log_event, log_tool_input, log_tool_output
from app.agent.mcp.gateway import ToolGateway
from app.schemas.agent import TextTurnRequest


def identity_fingerprint(turn: TextTurnRequest) -> str:
    value = f"{turn.channel}\0{turn.channel_identity or ''}"
    return hashlib.sha256(value.encode()).hexdigest()


def turn_fingerprint(turn, include_prior):
    return hashlib.sha256(json.dumps({'request': turn.model_dump(mode='json'),
        'include_prior': include_prior}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _empty_identity(status: str = "unknown") -> dict[str, Any]:
    return {"identity_status": status, "customer_id": None,
            "customer_phone": None, "customer_name": None, "honorific": None,
            "crm_sessions": [], "crm_orders": [], "owned_order_ids": []}


async def initialize_identity(turn: TextTurnRequest, tools: ToolGateway
                              ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if turn.verified_customer_id and turn.verified_phone:
        args = {'phone': turn.verified_phone}
        if hasattr(tools, 'invoke_trusted'):
            result = await tools.invoke_trusted('crm.get_customer', args, turn.verified_customer_id,
                                                turn.channel, turn.channel_identity)
        else:
            result = await tools.invoke('crm.get_customer', args)
        if "error" in result:
            raise RuntimeError("CRM identity lookup failed")
        candidates = (result.get("candidates", []) if result.get("ambiguous")
                      else [result] if result.get("found") else [])
        customer = next((item for item in candidates
                         if item.get("customer_id") == turn.verified_customer_id), None)
        if customer is None:
            raise ValueError("Verified customer does not match CRM")
        raw_orders = [order for order in customer.get("orders", []) if isinstance(order, dict)]
        identity = {"identity_status": "known", "customer_id": turn.verified_customer_id,
                    "customer_phone": turn.verified_phone,
                    "customer_name": customer.get("name"),
                    "honorific": customer.get("honorific"),
                    "crm_sessions": customer.get("sessions", []),
                    "crm_orders": raw_orders,
                    "owned_order_ids": [order["order_id"] for order in raw_orders
                                        if order.get("order_id")]}
        return identity, [{"name": "crm.get_customer",
                           "args": {"phone": turn.verified_phone}, "result": result}]
    key = {"hotline": "phone", "chat_fanpage": "fb_id",
           "zalo_oa": "zalo_id"}.get(turn.channel)
    if not key or not turn.channel_identity:
        log_event(turn, "session_identity", "identity_resolved", status="unknown",
                  lookup="skipped")
        return _empty_identity(), []
    args = {key: turn.channel_identity}
    log_tool_input("session_identity", "crm.get_customer", args)
    result = await tools.invoke("crm.get_customer", args)
    log_event(turn, "session_identity", "tool_result", tool="crm.get_customer",
              success="error" not in result)
    log_tool_output({}, "session_identity", "crm.get_customer", result)
    if "error" in result:
        raise RuntimeError("CRM identity lookup failed")
    calls = [{"name": "crm.get_customer", "args": args, "result": result}]
    if result.get("ambiguous"):
        log_event(turn, "session_identity", "identity_resolved", status="ambiguous")
        return _empty_identity("ambiguous"), calls
    if result.get("found") and result.get("customer_id"):
        raw_orders = [order for order in result.get("orders", []) if isinstance(order, dict)]
        owned_ids = [order["order_id"] for order in raw_orders
                     if isinstance(order.get("order_id"), str)]
        log_event(turn, "session_identity", "identity_resolved", status="known",
                  owned_orders=len(owned_ids))
        return {"identity_status": "known", "customer_id": result["customer_id"],
                "customer_phone": result.get("phone"),
                "customer_name": result.get("name"), "honorific": result.get("honorific"),
                "crm_sessions": result.get("sessions", []),
                "crm_orders": raw_orders,
                "owned_order_ids": owned_ids}, calls
    log_event(turn, "session_identity", "identity_resolved", status="unknown")
    return _empty_identity(), calls
