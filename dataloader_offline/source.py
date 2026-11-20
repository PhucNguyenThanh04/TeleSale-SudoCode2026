
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


def source_fingerprint(root: Path, metadata_path: Path | None = None) -> str:
    paths = [root/'catalog'/name for name in
             ['products.json','promotions.json','inventory_timeline.json','crm_seed.json']]
    paths += sorted((root/'policy').glob('*.md'))
    registry = metadata_path or Path(__file__).resolve().parents[1]/'ai-services/app/knowledge/policy/metadata.json'
    return json_digest([hashlib.sha256(p.read_bytes()).hexdigest() for p in paths+[registry]])


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



def read_policy(directory: Path, metadata_path: Path | None = None) -> list[PolicyChunk]:
    from .knowledge import policy_sources

    serving = {chunk.chunk_id: chunk for chunk in policy_sources(directory, metadata_path)}
    chunks: list[PolicyChunk] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        headings = list(CHUNK_HEADING.finditer(text))
        if not headings:
            raise ValueError(f"Policy file has no BTC chunk IDs: {path.name}")
        for index, heading in enumerate(headings):
            body = text[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)].strip()
            chunk_id, title = heading.groups()
            if not body:
                raise ValueError(f"Empty policy chunk: {chunk_id}")
            safe = serving.get(chunk_id)
            stored_body = safe.content if safe else "[Nội dung nội bộ đã loại khỏi chỉ mục]"
            if safe and safe.transformation != 'identity':
                title = safe.content.splitlines()[0]
            chunks.append(PolicyChunk(
                chunk_id=chunk_id, document_id=path.name, title=title.strip(),
                body=stored_body, access_level="public" if safe else "restricted",
                effective_from=safe.effective_from.isoformat() if safe and safe.effective_from else None,
                effective_until=safe.effective_until.isoformat() if safe and safe.effective_until else None,
                date_basis="order_date" if safe and safe.date_basis == "order_date" else "call_date",
                content_hash=digest(body),
            ))
    ids = [chunk.chunk_id for chunk in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate BTC policy chunk ID")
    return chunks


def read_release(root: Path, metadata_path: Path | None = None) -> dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(f"BTC data directory does not exist: {root}")
    fingerprint = source_fingerprint(root, metadata_path)
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
    release["chunks"] = read_policy(root / "policy", metadata_path)
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
    for group,key in [('orders','order_id'),('sessions','session_id')]:
        nested=[item[key] for customer in customers for item in customer.get(group,[])]
        if len(set(nested))!=len(nested):
            raise ValueError('Duplicate CRM '+key)
    if fingerprint != source_fingerprint(root, metadata_path):
        raise ValueError('BTC source changed during parsing')
    release['source_fingerprint'] = fingerprint
    return release


def release_counts(release: dict[str, Any]) -> dict[str, int]:
    products = release["products"]["products"]
    customers = release["crm"]["customers"]
    chunks = release["chunks"]
    return {
        "products": len(products),
        "variants": sum(len(p.get("variants", [])) for p in products),
        "promotions": len(release["promotions"]["promotions"]),
        "inventory_events": len(release["inventory"]["events"]),
        "customers": len(customers),
        "crm_orders": sum(len(c.get("orders", [])) for c in customers),
        "crm_sessions": sum(len(c.get("sessions", [])) for c in customers),
        "policy_documents": len({c.document_id for c in chunks}),
        "policy_chunks": len(chunks),
        "public_chunks": sum(c.access_level == "public" for c in chunks),
        "restricted_chunks": sum(c.access_level != "public" for c in chunks),
    }
