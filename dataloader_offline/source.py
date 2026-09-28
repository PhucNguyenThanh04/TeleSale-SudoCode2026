"""Read the BTC release without mutating it or confusing dates with wall time."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK_HEADING = re.compile(r"^## \[([A-Z]+(?:-[A-Z]+)*-\d+)\]\s*(.+)$", re.MULTILINE)
REFERENCE_DATE = "2026-10-15"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_digest(value: Any) -> str:
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    document_id: str
    title: str
    body: str
    access_level: str
    effective_from: str | None
    effective_until: str | None
    date_basis: str
    content_hash: str

    @property
    def index_text(self) -> str:
        # Internal text is never embedded, persisted in Qdrant, or sent to a model.
        if self.access_level != "public":
            return f"Tài liệu nội bộ, không cung cấp cho khách: {self.title}."
        return f"{self.title}\n{self.body}"


def policy_metadata(filename: str) -> tuple[str, str | None, str | None, str]:
    if filename == "chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md":
        return "public", None, "2026-09-30", "order_date"
    if filename == "chinh-sach-doi-tra.md":
        return "public", "2026-10-01", None, "order_date"
    if filename == "chinh-sach-bao-hanh.md":
        return "public", "2026-08-01", None, "order_date"
    if filename == "dieu-khoan-khuyen-mai.md":
        return "public", "2026-10-01", None, "call_date"
    if filename == "chinh-sach-van-chuyen-thanh-toan.md":
        return "public", "2026-09-15", None, "call_date"
    if filename in {"ghi-chu-nhap-hang-NOI-BO.md", "noi-quy-nhan-vien.md", "playbook-telesale.md"}:
        return "restricted", None, None, "call_date"
    public_documents = {
        "changelog.md", "faq.md", "quy-trinh-cod-hoan-hang.md",
        "spec-gia-dung.md", "spec-thoi-trang-me-be.md", "thong-bao-lich-nghi.md",
    }
    return ("public" if filename in public_documents else "restricted"), None, None, "call_date"


def read_policy(directory: Path) -> list[PolicyChunk]:
    chunks: list[PolicyChunk] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        headings = list(CHUNK_HEADING.finditer(text))
        if not headings:
            raise ValueError(f"Policy file has no BTC chunk IDs: {path.name}")
        access, valid_from, valid_until, date_basis = policy_metadata(path.name)
        for index, heading in enumerate(headings):
            body = text[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)].strip()
            chunk_id, title = heading.groups()
            if not body:
                raise ValueError(f"Empty policy chunk: {chunk_id}")
            # Do not store raw restricted material in either database.
            stored_body = body if access == "public" else "[Nội dung nội bộ đã loại khỏi chỉ mục]"
            if chunk_id == "KM-06":
                # The published paragraph includes numeric internal price floors.
                title = "Thẩm quyền giảm giá"
                stored_body = (
                    "Nhân viên/agent không được tự giảm giá ngoài chương trình đã công bố. "
                    "Yêu cầu giảm thêm cho đơn số lượng lớn cần chuyển quản lý duyệt; "
                    "agent không hứa mức giảm."
                )
            elif chunk_id == "KM-04":
                stored_body = (
                    "Nếu nhiều chương trình không cộng dồn cùng đủ điều kiện, "
                    "chọn chương trình cho giá cuối có lợi nhất. "
                    "Giá hiện hành phải lấy từ pricing.get_quote theo ngày tạo đơn."
                )
            elif chunk_id == "FAQ-04":
                stored_body = (
                    "AirPure Y có thêm than hoạt tính, điều khiển qua ứng dụng "
                    "và khóa trẻ em. Cả AirPure X và Y cùng dùng màng lọc "
                    "SKU-AP-FLT-X. So sánh giá hiện hành qua pricing.get_quote."
                )
            chunks.append(PolicyChunk(
                chunk_id=chunk_id, document_id=path.name, title=title.strip(),
                body=stored_body, access_level=access,
                effective_from=valid_from, effective_until=valid_until,
                date_basis=date_basis, content_hash=digest(body),
            ))
    ids = [chunk.chunk_id for chunk in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate BTC policy chunk ID")
    return chunks


def product_index_text(product: dict[str, Any]) -> str:
    """Public search text; prices, stock and internal attributes stay in SQL."""
    allowed = (
        "room_area_m2", "features", "warranty_months", "child_safe_lock",
        "stages", "material", "max_weight_kg", "volume_ml", "return_days",
    )
    parts = [product["name"], product["brand"], product["category"]]
    parts.extend(f"{key}: {product['attributes'][key]}" for key in allowed if key in product["attributes"])
    return "\n".join(parts)


def read_release(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(f"BTC data directory does not exist: {root}")
    names = {
        "products": "catalog/products.json",
        "promotions": "catalog/promotions.json",
        "inventory": "catalog/inventory_timeline.json",
        "crm": "catalog/crm_seed.json",
    }
    release = {key: json.loads((root / relative).read_text(encoding="utf-8")) for key, relative in names.items()}
    for key in ("products", "promotions", "inventory"):
        if release[key].get("reference_date") != REFERENCE_DATE:
            raise ValueError(f"Unexpected reference_date in {names[key]}")
    release["chunks"] = read_policy(root / "policy")
    if not release["chunks"]:
        raise ValueError("No BTC policy chunks found")
    for key, member in (("products", "products"), ("promotions", "promotions"), ("inventory", "events"), ("crm", "customers")):
        if not isinstance(release[key].get(member), list):
            raise ValueError(f"Missing {member} in {names[key]}")
    products = release["products"]["products"]
    skus = [item["sku"] for item in products]
    variant_skus = [variant["variant_sku"] for item in products for variant in item.get("variants", [])]
    if len(set(skus)) != len(skus) or len(set(variant_skus)) != len(variant_skus):
        raise ValueError("Duplicate product or variant SKU")
    if set(skus) & set(variant_skus):
        raise ValueError("A variant SKU collides with a parent SKU")
    event_keys = [(event["sku"], event["date"]) for event in release["inventory"]["events"]]
    if len(set(event_keys)) != len(event_keys):
        raise ValueError("Duplicate inventory event for one SKU/date")
    unknown = {sku for sku, _ in event_keys} - set(skus) - set(variant_skus)
    if unknown:
        raise ValueError(f"Inventory events reference unknown SKUs: {sorted(unknown)}")
    customers = release["crm"]["customers"]
    ids = [customer["customer_id"] for customer in customers]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate customer_id")
    # Phone numbers are deliberately not unique: BTC includes a shared phone.
    return release
