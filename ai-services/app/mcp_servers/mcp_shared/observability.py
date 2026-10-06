"""Safe, bounded tool I/O logs shared by AI and the three MCP processes."""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.mcp_servers.mcp_shared.pii import mask_pii


_UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_PHONE_WITH_SEPARATORS = re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){9,10}(?!\d)")
_TITLED_NAME = re.compile(r"\b((?i:anh|chị|cô|chú|bác|ông|bà))\s+([A-ZÀ-Ỹ][\wÀ-ỹ]{1,})")
_SAFE_INPUT = {
    "query", "category", "sku", "max_price_vnd", "min_room_area_m2",
    "include_discontinued", "on", "qty", "basket_skus", "price_vnd",
    "payment", "promo_code", "action", "new_variant_sku", "callback_at",
    "max_episodes", "include_prior",
}
_SAFE_OUTPUT = {
    "error", "found", "ambiguous", "sku", "items", "total", "name",
    "brand", "category", "list_price_vnd", "attributes", "variants",
    "variant_sku", "price_delta_vnd", "room_area_m2", "discontinued",
    "successor_sku", "in_stock", "qty", "restock_expected", "final_price_vnd",
    "applied_promos", "expired_promos", "ineligible_promos",
    "not_applied_exclusive", "promo_code", "discount_vnd", "freeship",
    "type", "gift_sku", "status", "total_vnd", "needs_confirmation_call",
    "estimated_delivery", "action", "new_variant_sku", "fee_vnd",
    "price_diff_vnd", "refund_vnd", "extra_payment_vnd", "refund_days",
    "orders", "callback_at", "moved_from", "brief_ok", "missing",
    "expected_price_vnd", "given", "limit_vnd", "color", "size", "price",
    "stock_status", "turn_no", "op", "key",
}
_MAX_LOG_CHARS = 3000


def _count(value: Any) -> int:
    return len(value) if isinstance(value, (list, dict)) else 0


def redact_text(value: str, customer_name: str | None = None) -> str:
    """Mask common PII patterns and identifiers before rendering free text."""
    value = _UUID.sub("[ID ĐÃ ẨN]", mask_pii(value))
    value = _PHONE_WITH_SEPARATORS.sub("[SỐ ĐÃ ẨN]", value)
    if customer_name and len(customer_name.strip()) > 1:
        value = re.sub(re.escape(customer_name.strip()), "[TÊN ĐÃ ẨN]", value,
                       flags=re.IGNORECASE)
    value = _TITLED_NAME.sub(r"\1 [TÊN ĐÃ ẨN]", value)
    return value


def _safe_value(value: Any, allowed: set[str], *, product_name: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: _safe_value(item, allowed, product_name=product_name)
                for key, item in value.items()
                if key in allowed and (key != "name" or product_name)}
    if isinstance(value, list):
        return [_safe_value(item, allowed, product_name=product_name) for item in value[:20]]
    if isinstance(value, str):
        return redact_text(value)[:500]
    return value if isinstance(value, (int, float, bool)) or value is None else "[ĐÃ ẨN]"


def safe_tool_input(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "crm.get_customer":
        return {"lookup": next((key for key in ("phone", "fb_id", "zalo_id")
                                if args.get(key)), "none")}
    if name == "memory.read":
        return {"customer_known": bool(args.get("customer_id")),
                "max_episodes": args.get("max_episodes"),
                "include_prior": args.get("include_prior")}
    if name == "memory.write":
        data = args.get("data") if isinstance(args.get("data"), dict) else {}
        key = data.get("key")
        action = args.get("action")
        op = data.get("op")
        return {"action": action if isinstance(action, str) and
                action in {"turn", "fact", "order", "seed_episode"}
                else "unknown", "customer_known": bool(args.get("customer_id")),
                "fact_key": key if args.get("action") == "fact" and isinstance(key, str)
                and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", key) else None,
                "fact_op": op if action == "fact" and isinstance(op, str) and
                op in {"set", "supersede", "delete"}
                else None,
                "business_day": data.get("on") if args.get("action") == "turn" else None}
    if name == "handoff.transfer":
        brief = args.get("brief") if isinstance(args.get("brief"), dict) else {}
        return {"brief_provided": isinstance(args.get("brief"), dict),
                "brief_fields": sorted(key for key in brief
                                       if key in {"escalation_reason", "conversation_summary",
                                                  "product_advised", "price_quoted_vnd",
                                                  "open_questions", "next_action"})}
    safe = _safe_value(args, _SAFE_INPUT)
    if name == "pricing.get_quote":
        safe["customer_phone_provided"] = bool(args.get("customer_phone"))
        safe["address_provided"] = bool(args.get("address"))
    elif name in {"order.create", "order.update", "order.status", "schedule.callback"}:
        safe["customer_phone_provided"] = bool(args.get("customer_phone"))
        safe["order_id_provided"] = bool(args.get("order_id"))
        if name == "order.create":
            safe["address_provided"] = bool(args.get("address"))
    return safe


def safe_tool_output(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if name == "crm.get_customer":
        return {"found": result.get("found", False), "ambiguous": result.get("ambiguous", False),
                "orders_count": _count(result.get("orders")),
                "sessions_count": _count(result.get("sessions")),
                **({"error": _safe_error(result["error"])} if "error" in result else {})}
    if name == "memory.read":
        profile = result.get("profile") if isinstance(result.get("profile"), dict) else {}
        return {"history_turns": _count(result.get("history")),
                "profile_keys": sorted(key for key in profile
                                       if isinstance(key, str) and
                                       re.fullmatch(r"[a-z][a-z0-9_]{1,63}", key)),
                "episodes": _count(result.get("episodes")),
                "owned_orders": _count(result.get("owned_order_ids")),
                **({"error": _safe_error(result["error"])} if "error" in result else {})}
    if name == "memory.write":
        return _safe_value(result, {"error", "turn_no", "key", "op"})
    safe = _safe_value(result, _SAFE_OUTPUT, product_name=name == "catalog.search")
    if name == "order.create":
        safe["order_id_created"] = bool(result.get("order_id"))
    elif name == "schedule.callback":
        safe["callback_id_created"] = bool(result.get("callback_id"))
    elif name == "handoff.transfer":
        safe["ticket_id_created"] = bool(result.get("ticket_id"))
    if "error" in safe:
        safe["error"] = _safe_error(safe["error"])
    return safe


def _safe_error(value: Any) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value) else "redacted_error"


def render_payload(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return text if len(text) <= _MAX_LOG_CHARS else text[:_MAX_LOG_CHARS] + "… [ĐÃ RÚT GỌN]"


def configure_mcp_logging(level: str) -> None:
    logger = logging.getLogger("app.mcp")
    if not any(getattr(handler, "_mcp_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler._mcp_handler = True
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def log_mcp_exception(server: str, name: str, exc: Exception) -> None:
    logging.getLogger(f"app.mcp.{server}").warning(
        "%s không xử lý được | loại lỗi: %s", name, type(exc).__name__)


def log_mcp_validation(server: str, name: str, exc: Exception) -> None:
    issues = [{"field": ".".join(map(str, item.get("loc", ()))),
               "type": item.get("type")}
              for item in exc.errors(include_input=False, include_context=False)[:5]]
    logging.getLogger(f"app.mcp.{server}").warning(
        "%s tham số không hợp lệ | %s", name, render_payload({"issues": issues}))


async def trace_mcp_call(server: str, name: str, args: dict[str, Any],
                         run: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Log the handler boundary, including validation and service errors."""
    logger = logging.getLogger(f"app.mcp.{server}")
    started = time.perf_counter()
    logger.info("%s nhận vào | %s", name, render_payload(safe_tool_input(name, args)))
    try:
        result = await run()
    except Exception as exc:
        logger.error("%s lỗi | loại lỗi: %s, thời gian: %d ms", name,
                     type(exc).__name__, round((time.perf_counter() - started) * 1000))
        raise
    logger.info("%s trả ra | %s | thời gian: %d ms", name,
                render_payload(safe_tool_output(name, result)),
                round((time.perf_counter() - started) * 1000))
    return result
