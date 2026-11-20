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
