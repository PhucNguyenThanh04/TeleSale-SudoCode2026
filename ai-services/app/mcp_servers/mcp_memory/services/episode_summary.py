"""Bounded episode text from verified facts and the customer's own turns."""

from app.mcp_servers.mcp_shared.pii import mask_pii


def build_episode_summary(confirmed_facts: list[dict], recent_turns: list[dict],
                          max_chars: int) -> str:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    products = []
    rooms = []
    for fact in confirmed_facts:
        if fact.get("status", "active") != "active":
            continue
        if fact.get("key") == "product_advised" and fact.get("scope_type") == "product":
            sku = fact.get("scope_id")
            if isinstance(sku, str) and sku and sku not in products:
                products.append(sku)
        elif fact.get("key") == "room_area_m2" and fact.get("scope_type") == "room":
            room, area = fact.get("scope_id"), fact.get("value")
            if isinstance(room, str) and type(area) is int:
                item = f"{room}={area} m²"
                if item not in rooms:
                    rooms.append(item)
    parts = []
    if products:
        parts.append("Sản phẩm đã tư vấn: " + ", ".join(products))
    if rooms:
        parts.append("Diện tích: " + ", ".join(rooms))
    required = mask_pii(" | ".join(parts))
    if len(required) > max_chars:
        # Scoped facts remain in ai_memory.facts and memory.read.scoped_facts.
        # A partial SKU/room list here could be mistaken for a complete one.
        return "Xem fact có cấu trúc"[:max_chars]
    tail = []
    seen = set()
    for row in recent_turns:
        customer = mask_pii(str(row["customer_text"])).strip()
        if customer and customer not in seen:
            tail.append(customer)
            seen.add(customer)
    text = required
    for utterance in tail:
        next_text = (text + " | " if text else "") + utterance
        if len(next_text) > max_chars:
            break
        text = next_text
    return text
