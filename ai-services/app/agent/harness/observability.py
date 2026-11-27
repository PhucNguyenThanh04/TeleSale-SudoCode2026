
import logging
import math
from contextlib import contextmanager
from contextvars import ContextVar
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from app.agent.harness.state import TurnState
from app.agent.harness.execution_diagnostics import ERROR_TYPES
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
    "order_update_unverified": "chưa có kết quả gửi yêu cầu cập nhật đơn",
    "unanswered_request": "chưa hoàn tất yêu cầu hiện tại",
    "unnecessary_clarification": "hỏi lại dữ kiện đã rõ",
    "customer_constraint_violated": "không giữ đúng điều kiện khách yêu cầu",
    "grounding_review_unavailable": "không có kết luận kiểm duyệt ngữ nghĩa",
    "callback_unverified": "chưa có kết quả đặt lịch gọi lại",
    "policy_question_unanswered": "chưa trả lời câu hỏi chính sách",
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


_DIAGNOSTIC_EVENTS = ContextVar("turn_diagnostic_events", default=None)
DIAGNOSTIC_REASONS = frozenset(VALUE_LABELS) | {
    "order_selection_mismatch", "customer_erasure_unverified", "handoff_not_queued", "unknown_reason"}
DIAGNOSTIC_ERRORS = frozenset({"TimeoutError", "RuntimeError", "ValueError", "TypeError", "KeyError",
    "OSError", "ConnectionError", "APIError", "APIConnectionError", "APITimeoutError",
    "RateLimitError", "HTTPStatusError", "ConnectError", "ReadTimeout", "GraphRecursionError", "other_error"}) | ERROR_TYPES
_DIAGNOSTIC_PAIRS = frozenset({("run_agent", "model_failed"), ("verify", "grounding_checked"),
    ("verify", "answer_checked"), ("verify", "recovery_attempted"), ("verify", "recovery_unavailable"),
    ("verify", "recovery_rejected"), ("verify", "recovery_succeeded"), ("verify", "recovery_exhausted"),
    ("verify", "recovery_fallback")})


def safe_diagnostic_event(step, event, metadata):
    if not isinstance(step, str) or not isinstance(event, str):
        return None
    node_timing = step in {'accept', 'retrieve_context', 'run_agent', 'verify', 'persist'} and event in {'completed', 'failed'}
    if node_timing or (step, event) in {('run_agent', 'model_timing'), ('call_tool', 'tool_timing')}:
        duration = metadata.get('duration_ms')
        if (type(duration) not in (int, float) or duration < 0
                or type(duration) is float and not math.isfinite(duration)):
            return None
        item = {'step': step, 'event': event, 'duration_ms': duration}
        if event == 'tool_timing':
            from app.agent.implementations.tool_names import MODEL_TOOL_NAMES
            if not isinstance(metadata.get('tool'), str) or metadata['tool'] not in MODEL_TOOL_NAMES:
                return None
            item['tool'] = metadata['tool']
        if event == 'failed':
            kind = metadata.get('error_type')
            item['error_type'] = kind if isinstance(kind, str) and kind in DIAGNOSTIC_ERRORS else 'other_error'
        return item
    if (step, event) == ('execution', 'phase_result'):
        from app.agent.harness.execution_diagnostics import normalize_execution_event
        return {'step': step, 'event': event, **normalize_execution_event(metadata)}
    if not isinstance(step,str) or not isinstance(event,str) or (step, event) not in _DIAGNOSTIC_PAIRS:
        return None
    item = {"step": step, "event": event}
    if 'accepted' in metadata and type(metadata['accepted']) is bool:
        item['accepted'] = metadata['accepted']
    if 'reason' in metadata:
        item['reason'] = metadata['reason'] if isinstance(metadata['reason'],str) and metadata['reason'] in DIAGNOSTIC_REASONS else 'unknown_reason'
    if 'error_type' in metadata:
        item['error_type'] = metadata['error_type'] if isinstance(metadata['error_type'],str) and metadata['error_type'] in DIAGNOSTIC_ERRORS else 'other_error'
    return item


@contextmanager
def capture_diagnostic_events():
    events = []
    token = _DIAGNOSTIC_EVENTS.set(events)
    try:
        yield events
    finally:
        _DIAGNOSTIC_EVENTS.reset(token)


def _display_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        if key == "success":
            return "thành công" if value else "thất bại"
        if key == "accepted":
            return "đạt" if value else "không đạt"
        return "có" if value else "không"
    return VALUE_LABELS.get(value, str(value)) if isinstance(value, str) else str(value)


def configure_agent_logging(level: str) -> None:
    if not any(getattr(handler, "_agent_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler._agent_handler = True
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def log_event(_turn: TextTurnRequest | TurnState, step: str, event: str,
              *, level: int = logging.INFO, **metadata: Any) -> None:
    events = _DIAGNOSTIC_EVENTS.get()
    if events is not None:
        item = safe_diagnostic_event(step, event, metadata)
        if item is not None:
            events.append(item)
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
    _write_payload(step, "tool_output", {"tool": name, "result": safe_tool_output(name, result)})


def trace_node(name: str) -> Callable:
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
