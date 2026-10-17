"""Operational logs for a chat turn; callers pass only non-sensitive metadata."""

import logging
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from app.agent.harness.state import TurnState
from app.mcp_servers.mcp_shared.observability import (
    render_payload, safe_tool_input, safe_tool_output,
)
from app.schemas.agent import TextTurnRequest


logger = logging.getLogger("app.agent")

STEP_LABELS = {
    "chat": "Lượt chat", "accept": "Nhận yêu cầu",
    "session_identity": "Khởi tạo danh tính phiên", "retrieve_context": "Đọc ngữ cảnh",
    "call_tool": "Gọi công cụ", "run_agent": "Agent xử lý lượt",
    "verify": "Kiểm tra câu trả lời", "persist": "Lưu bộ nhớ",
}
EVENT_LABELS = {
    "started": "bắt đầu", "completed": "hoàn tất", "failed": "lỗi",
    "cache_hit": "trả kết quả đã xử lý", "identity_resolved": "đã xác định",
    "tool_failed": "công cụ gặp lỗi", "tool_result": "kết quả công cụ",
    "context_loaded": "đã tải ngữ cảnh", "memory_unavailable": "không đọc được bộ nhớ",
    "refresh_invoking": "kiểm tra lại bằng công cụ", "refresh_result": "kết quả kiểm tra lại",
    "model_failed": "model gặp lỗi", "blocked": "chặn lời gọi",
    "answer_checked": "đã kiểm tra câu trả lời",
    "grounding_checked": "đã kiểm tra bằng chứng",
    "answer_check_disabled": "bỏ qua kiểm tra câu trả lời",
    "memory_recorded": "đã lưu lượt chat",
    "tool_input": "gửi vào công cụ", "tool_output": "công cụ trả về",
}
FIELD_LABELS = {
    "duration_ms": "thời gian", "channel": "kênh", "input_mode": "kiểu đầu vào",
    "on": "ngày nghiệp vụ", "tool": "công cụ", "tool_count": "số lần gọi công cụ",
    "tool_calls": "số công cụ đã gọi", "success": "kết quả",
    "status": "trạng thái", "lookup": "tra cứu", "owned_orders": "số đơn thuộc khách",
    "history_turns": "lượt trước trong phiên", "turn_no": "số lượt trong phiên",
    "profile_facts": "số thông tin đã nhớ",
    "episodes": "phiên trước", "call_brief": "tóm tắt khách quay lại",
    "operation": "thao tác", "reason": "lý do", "accepted": "câu trả lời",
    "accepted_facts": "thông tin đã lưu", "needs_handoff": "chuyển người thật",
    "memory_writes": "số fact đã lưu", "error_type": "loại lỗi",
}
VALUE_LABELS = {
    "known": "đã nhận diện", "unknown": "chưa xác định",
    "ambiguous": "có nhiều khách trùng thông tin", "skipped": "bỏ qua",
    "tool_limit": "đã đạt giới hạn công cụ", "tool_failed": "công cụ lỗi",
    "precondition_or_arguments": "thiếu điều kiện hoặc tham số không hợp lệ",
    "empty_answer": "câu trả lời rỗng",
    "unsupported_policy_or_internal_claim": "chính sách hoặc dữ liệu nội bộ chưa có nguồn",
    "unsupported_comparison": "so sánh mức phù hợp chưa có nguồn",
    "unsupported_product_spec": "thông số sản phẩm chưa có trong catalog",
    "quote_missing_or_ambiguous": "chưa có báo giá duy nhất",
    "quote_sku_mismatch": "SKU báo giá không khớp",
    "quote_amount_mismatch": "số tiền không khớp báo giá",
    "price_without_quote": "số tiền chưa được báo giá xác minh",
    "competitor_price_unverified": "giá đối thủ không khớp lời khách",
    "stock_sku_mismatch": "SKU tồn kho không khớp",
    "stock_result_mismatch": "trạng thái tồn kho không khớp",
    "stock_quantity_mismatch": "số lượng tồn kho không khớp",
    "order_creation_unverified": "chưa có kết quả tạo đơn",
    "promotion_quote_missing": "chưa có báo giá khuyến mãi",
    "promotion_unverified": "khuyến mãi chưa được xác minh",
    "promotion_code_mismatch": "mã khuyến mãi không khớp",
    "promotion_detail_unverified": "chi tiết khuyến mãi chưa được xác minh",
    "delivery_unverified": "ngày giao chưa được xác minh",
    "order_status_unverified": "trạng thái đơn chưa được xác minh",
    "order_status_mismatch": "trạng thái đơn không khớp",
    "order_id_mismatch": "mã đơn không khớp",
    "repair_requested_tool": "lần viết lại yêu cầu gọi công cụ",
    "chot_don": "chốt đơn", "chuyen_may": "chuyển người thật",
    "hen_goi_lai": "hẹn gọi lại", "khac": "khác",
}


def _display_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        if key == "success":
            return "thành công" if value else "thất bại"
        if key == "accepted":
            return "đạt" if value else "không đạt"
        return "có" if value else "không"
    return VALUE_LABELS.get(value, str(value)) if isinstance(value, str) else str(value)


def configure_agent_logging(level: str) -> None:
    """Make agent events visible for both ASGI and direct Python entrypoints."""
    if not any(getattr(handler, "_agent_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler._agent_handler = True
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def log_event(_turn: TextTurnRequest | TurnState, step: str, event: str,
              *, level: int = logging.INFO, **metadata: Any) -> None:
    """Log readable workflow events; the turn is deliberately not rendered."""
    if not logger.isEnabledFor(level):
        return
    title = f"{STEP_LABELS.get(step, step)}: {EVENT_LABELS.get(event, event)}"
    details = ", ".join(
        f"{FIELD_LABELS.get(key, key)}: "
        f"{value} ms" if key == "duration_ms" else
        f"{FIELD_LABELS.get(key, key)}: {_display_value(key, value)}"
        for key, value in metadata.items()
    )
    logger.log(level, "%s%s", title, f" | {details}" if details else "")


def _write_payload(step: str, event: str, payload: dict[str, Any],
                   level: int = logging.INFO) -> None:
    if not logger.isEnabledFor(level):
        return
    logger.log(level, "%s: %s | %s", STEP_LABELS[step], EVENT_LABELS[event],
               render_payload(payload))


def log_tool_input(step: str, name: str, args: dict[str, Any]) -> None:
    _write_payload(step, "tool_input", {"tool": name, "args": safe_tool_input(name, args)})


def log_tool_output(state: TurnState, step: str, name: str,
                    result: dict[str, Any]) -> None:
    """Show business fields from a tool result, never CRM profile or identifiers."""
    _write_payload(step, "tool_output", {"tool": name, "result": safe_tool_output(name, result)})


def trace_node(name: str) -> Callable:
    """Log node boundaries without placing customer content in the trace."""
    def decorate(fn: Callable[..., Awaitable[dict[str, Any]]]) -> Callable:
        @wraps(fn)
        async def wrapped(self: Any, state: TurnState) -> dict[str, Any]:
            started = time.perf_counter()
            log_event(state, name, "started")
            try:
                update = await fn(self, state)
            except Exception as exc:
                log_event(state, name, "failed", level=logging.ERROR,
                          duration_ms=round((time.perf_counter() - started) * 1000),
                          error_type=type(exc).__name__)
                raise
            log_event(state, name, "completed",
                      duration_ms=round((time.perf_counter() - started) * 1000))
            return update
        return wrapped
    return decorate
