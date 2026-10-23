"""Compact, evidence-backed session state for a returning customer's brief."""

from app.mcp_servers.mcp_shared.pii import mask_pii


def build_episode_summary(confirmed_facts: list[dict], recent_turns: list[dict],
                          max_chars: int, *, episode_state: dict | None = None) -> str:
    """Describe what happened between facts; facts and turns remain separate records."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    topics = (episode_state or {}).get("topics", [])
    if not isinstance(topics, list):
        topics = []
    entries = []
    for topic in reversed(topics):
        if not isinstance(topic, dict):
            continue
        for item in reversed(topic.get("items", [])):
            if not isinstance(item, dict) or item.get("status") != "open":
                continue
            label = "Câu hỏi còn mở" if item.get("kind") == "question" else "Rào cản còn mở"
            if isinstance(item.get("text"), str) and item["text"].strip():
                entries.append((label, item["text"].strip()))
        for field, label in (("next_step", "Bước tiếp theo"),
                             ("customer_goal", "Mục tiêu"),
                             ("advice_given", "Đã tư vấn")):
            if isinstance(topic.get(field), str) and topic[field].strip():
                entries.append((label, topic[field].strip()))
    selected = []
    for label, value in entries:
        for entry in (mask_pii(f"{label}: {value}"), mask_pii(value)):
            if entry not in selected and len(" | ".join([*selected, entry])) <= max_chars:
                selected.append(entry)
                break
    return " | ".join(selected) if selected else "Chưa có diễn biến riêng được xác minh."[:max_chars]
