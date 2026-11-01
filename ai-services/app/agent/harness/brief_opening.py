"""Build a restrained returning-customer greeting following PB-01."""

from typing import Any


def build_suggested_opening(
    *,
    honorific: str | None = None,
    customer_name: str | None = None,
    last_session: dict[str, Any] | None = None,
    requested_skus: list[str] | None = None,
    advised_products: list[dict[str, Any]] | None = None,
    open_blockers: list[str] | None = None,
    fallback_blocker: str | None = None,
) -> str:
    """Greet by honorific/name, confirm at most 2 items (product + blocker), never quote old price."""
    greeting = "Dạ"
    if isinstance(honorific, str) and honorific.strip():
        h = honorific.strip()
        if isinstance(customer_name, str) and customer_name.strip():
            short_name = customer_name.strip().split()[-1]
            greeting = f"Dạ em chào {h} {short_name}"
        else:
            greeting = f"Dạ em chào {h}"
    elif isinstance(customer_name, str) and customer_name.strip():
        short_name = customer_name.strip().split()[-1]
        greeting = f"Dạ em chào anh/chị {short_name}"

    outcome = (last_session or {}).get("outcome", "khac") if isinstance(last_session, dict) else "khac"
    req = requested_skus or []
    products = advised_products or []
    blockers = open_blockers or ([] if not fallback_blocker else [fallback_blocker])

    product_item = None
    if len(req) == 1:
        product_item = f"mẫu {req[0]}"
    elif len(products) == 1 and isinstance(products[0].get("sku"), str):
        product_item = f"mẫu {products[0]['sku']}"
    elif len(products) > 1:
        product_item = "các sản phẩm lần trước"

    blocker_item = blockers[0].strip() if blockers and isinstance(blockers[0], str) and blockers[0].strip() else None

    if outcome == "chot_don":
        target = product_item or "đơn hàng lần trước"
        return f"{greeting}, lần trước mình đã đặt {target}. Hôm nay mình cần em hỗ trợ thêm thông tin gì về đơn hàng ạ?"

    if product_item and blocker_item:
        return (f"{greeting}, lần trước mình đang cân nhắc {product_item} ({blocker_item}). "
                f"Mình muốn tiếp tục phần đó không ạ?")
    if product_item:
        return f"{greeting}, lần trước mình đã trao đổi về {product_item}. Mình muốn tiếp tục phần đó ạ?"
    if blocker_item:
        return f"{greeting}, lần trước mình đang tạm dừng ở phần {blocker_item}. Mình muốn tiếp tục trao đổi không ạ?"
    return f"{greeting}, lần trước mình đã trao đổi về nội dung lần trước. Mình muốn tiếp tục phần đó ạ?"
