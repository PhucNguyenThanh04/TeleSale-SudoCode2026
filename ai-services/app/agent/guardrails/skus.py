from app.mcp_servers.mcp_shared.commerce_evidence import CATALOG_TOOLS

import re
from typing import Any


def known_skus(tool_calls: list[dict[str, Any]]) -> set[str]:
    skus: set[str] = set()
    for call in tool_calls:
        result = call.get("result", {})
        if not isinstance(result, dict) or "error" in result:
            continue
        name = call.get("name")
        if name in CATALOG_TOOLS:
            items = result.get("items", [])
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("sku"), str) and item["sku"]:
                    skus.add(item["sku"])
                variants = item.get("variants", [])
                for variant in variants if isinstance(variants, list) else []:
                    if isinstance(variant, dict) and isinstance(variant.get("variant_sku"), str) \
                            and variant["variant_sku"]:
                        skus.add(variant["variant_sku"])
        elif name == 'order.preview_update' and result.get('status') == 'preview' and result.get('estimate') is True:
            inventory = result.get('replacement_inventory')
            if (isinstance(inventory, dict) and isinstance(inventory.get('sku'), str)
                    and inventory['sku'] == result.get('new_variant_sku')):
                skus.add(inventory['sku'])
        elif name in {"inventory.check", "pricing.get_quote", "order.create"}:
            sku = call.get("args", {}).get("sku")
            if isinstance(sku, str) and sku and result.get("sku", sku) == sku:
                skus.add(sku)
    return skus


def mentioned_skus(text: str, skus: set[str]) -> set[str]:
    return {sku for sku in skus if re.search(
        rf"(?<![\w-]){re.escape(sku)}(?![\w-])", text, re.IGNORECASE)}
