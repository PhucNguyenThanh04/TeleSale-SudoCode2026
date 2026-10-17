"""Redacted, per-turn evidence for rejected verifier drafts.

This module explains an existing decision; it does not decide whether to accept it.
"""

import re
from typing import Any

from app.agent.guardrails import checks


def _amount_spans(draft: str) -> list[tuple[int, int, int]]:
    spans: list[tuple[int, int, int]] = []
    for pattern in (checks._MILLION_SHORTHAND, checks._AMOUNT,
                    checks._PRICE_NUMBER, checks._BARE_MONEY):
        for match in pattern.finditer(draft):
            start, end = match.span(1) if pattern is checks._PRICE_NUMBER else match.span()
            if any(start < prior_end and prior_start < end
                   for prior_start, prior_end, _ in spans):
                continue
            raw = draft[start:end]
            amount = (int(raw.replace(".", "").replace(",", ""))
                      if pattern is checks._BARE_MONEY or pattern is checks._PRICE_NUMBER
                      else checks._money_amount(raw))
            if amount is not None:
                spans.append((start, end, amount))
    return sorted(spans)


def _source_evidence(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = {name: {"available": False, "amounts_vnd": []}
               for name in ("quote", "customer", "memory", "policy.search",
                            "catalog.search", "inventory.check")}
    customer = state.get("safe_text", "")
    if customer:
        sources["customer"]["available"] = True
        sources["customer"]["amounts_vnd"] = sorted(
            {amount for amount, _, _ in checks._money_claims(customer)}
            | checks.customer_budget_amounts(customer))
    profile = state.get("profile", {})
    if isinstance(profile, dict):
        facts = [{"key": key, "value_vnd": fact["value"],
                  "source_kind": (fact.get("source_kind")
                                  if fact.get("source_kind") in {"customer", "tool", "agent"}
                                  else "unknown")}
                 for key, fact in profile.items()
                 if isinstance(fact, dict) and key.endswith("_vnd")
                 and type(fact.get("value")) is int]
        sources["memory"]["available"] = bool(profile)
        sources["memory"]["amounts_vnd"] = sorted({fact["value_vnd"] for fact in facts})
        sources["memory"]["facts"] = facts
    quote_amounts: set[int] = set()
    policy_amounts: set[int] = set()
    promo_codes: set[str] = set()
    quotes: list[dict[str, Any]] = []
    chunk_ids: list[str] = []
    for call in state.get("tool_calls", []):
        result = call.get("result", {})
        if not isinstance(result, dict) or "error" in result:
            continue
        if call.get("name") == "pricing.get_quote":
            sources["quote"]["available"] = True
            quote_amounts.update(checks._quote_money_values(result))
            codes = [promo["promo_code"] for promo in result.get("applied_promos", [])
                     if isinstance(promo, dict)
                     and isinstance(promo.get("promo_code"), str)]
            promo_codes.update(codes)
            sku = call.get("args", {}).get("sku")
            quotes.append({"sku": checks.mask_pii(sku) if isinstance(sku, str) else None,
                           "on": call.get("args", {}).get("on"),
                           "final_price_vnd": result.get("final_price_vnd"),
                           "list_price_vnd": result.get("list_price_vnd"),
                           "promo_codes": codes})
        elif call.get("name") == "policy.search":
            sources["policy.search"]["available"] = True
            for chunk in result.get("chunks", []):
                if isinstance(chunk, dict) and isinstance(chunk.get("body"), str):
                    if isinstance(chunk.get("chunk_id"), str):
                        chunk_ids.append(checks.mask_pii(chunk["chunk_id"]))
                    policy_amounts.update(amount for amount, _, _
                                          in checks._money_claims(chunk["body"]))
        elif call.get("name") == "catalog.search":
            sources["catalog.search"]["available"] = True
            items = [
                {"sku": checks.mask_pii(item["sku"]),
                 "list_price_vnd": item.get("list_price_vnd"),
                 "features": {key: checks.attribute_feature_status(item, key)
                              for key in checks._BOOLEAN_FEATURE_ALIASES}}
                for item in result.get("items", []) if isinstance(item, dict)
                and isinstance(item.get("sku"), str)]
            sources["catalog.search"]["items"] = items
            sources["catalog.search"]["amounts_vnd"] = sorted(
                {item["list_price_vnd"] for item in items
                 if type(item["list_price_vnd"]) is int})
        elif call.get("name") == "inventory.check":
            sources["inventory.check"]["available"] = True
            sku = call.get("args", {}).get("sku")
            sources["inventory.check"].setdefault("checks", []).append({
                "sku": checks.mask_pii(sku) if isinstance(sku, str) else None,
                "in_stock": result.get("in_stock"), "qty": result.get("qty")})
    sources["quote"]["amounts_vnd"] = sorted(quote_amounts)
    sources["quote"]["promo_codes"] = sorted(promo_codes)
    sources["quote"]["quotes"] = quotes
    sources["policy.search"]["amounts_vnd"] = sorted(policy_amounts)
    sources["policy.search"]["chunk_ids"] = chunk_ids
    return sources


def rejected_draft(state: dict[str, Any], reason: str,
                   draft: str | None = None) -> dict[str, Any]:
    """Describe candidate spans; source matches are diagnostic, not acceptance proof."""
    draft = checks.mask_pii(draft if draft is not None else state.get("agent_draft", ""))
    customer_name = state.get("customer_name")
    if isinstance(customer_name, str) and customer_name.strip():
        name = re.escape(customer_name.strip())
        draft = re.sub(rf"(?<!\w){name}(?!\w)", "[TÊN ĐÃ ẨN]", draft,
                       flags=re.IGNORECASE)
    kind = ("price" if reason in {"price_without_quote", "quote_amount_mismatch",
                                  "quote_missing_or_ambiguous", "quote_sku_mismatch",
                                  "competitor_price_unverified"}
            else "promotion" if reason.startswith("promotion_")
            else "comparison" if reason == "unsupported_comparison"
            else "spec" if reason == "unsupported_product_spec"
            else "policy" if reason == "unsupported_policy_or_internal_claim"
            else "stock" if reason.startswith("stock_")
            else "order" if reason.startswith("order_")
            else "delivery" if reason.startswith("delivery_")
            else "other")
    spans: list[tuple[int, int, Any]] = []
    if kind == "price":
        spans = _amount_spans(draft)
    else:
        pattern = {"promotion": checks._PROMOTION,
                   "comparison": checks._SUPERLATIVE,
                   "spec": checks._PRODUCT_FEATURE,
                   "policy": checks._POLICY,
                   "stock": checks._STOCK,
                   "order": checks._ORDER,
                   "delivery": checks._DELIVERY}.get(kind)
        if pattern:
            spans = [(m.start(), m.end(), m.group()) for m in pattern.finditer(draft)]
        if kind == "promotion":
            spans += [(m.start(), m.end(), m.group())
                      for m in checks._PROMO_CODE.finditer(draft)]
    if not spans and draft:
        spans = [(0, len(draft), draft)]
    evidence = _source_evidence(state)
    claims = [{"type": kind, "value": value, "span": [start, end],
               "matched_sources": [source for source, details in evidence.items()
                                   if type(value) is int and value in details["amounts_vnd"]
                                   or isinstance(value, str) and value in details.get("promo_codes", [])]}
              for start, end, value in spans]
    return {"reason": reason, "agent_draft": draft, "claim_type": kind,
            "claims": claims, "source_evidence": evidence}
