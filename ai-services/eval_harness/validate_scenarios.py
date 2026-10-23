"""Validate benchmark scenario files against BTC specification and catalog data."""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BTC_DIR = Path(os.getenv("BTC_DATA_DIR", ROOT.parent / "BTC-Data-Vong1-TEAMS"))

PRODUCTS_PATH = BTC_DIR / "catalog" / "products.json"
PROMOTIONS_PATH = BTC_DIR / "catalog" / "promotions.json"
TOOLS_SCHEMA_PATH = BTC_DIR / "schemas" / "tools.schema.json"
PERSONAS_PATH = BTC_DIR / "simulator" / "personas.json"

PHONE_REGEX = re.compile(r"^0[0-9]{9}$")
DATE_REGEX = re.compile(r"^202[6-9]-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$")


def load_btc_catalogs():
    """Load valid SKUs, promotions, tools, and personas from BTC data."""
    valid_skus = set()
    product_prices = {}
    if PRODUCTS_PATH.exists():
        products_data = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
        for p in products_data.get("products", []):
            sku = p.get("sku")
            if sku:
                valid_skus.add(sku)
                product_prices[sku] = p.get("list_price_vnd")
            for v in p.get("variants", []):
                v_sku = v.get("variant_sku")
                if v_sku:
                    valid_skus.add(v_sku)
                    price_delta = v.get("price_delta_vnd", 0)
                    product_prices[v_sku] = (p.get("list_price_vnd", 0) + price_delta)

    valid_promos = set()
    if PROMOTIONS_PATH.exists():
        promo_data = json.loads(PROMOTIONS_PATH.read_text(encoding="utf-8"))
        for pr in promo_data.get("promotions", []):
            code = pr.get("promo_code")
            if code:
                valid_promos.add(code)

    valid_tools = set()
    if TOOLS_SCHEMA_PATH.exists():
        tools_data = json.loads(TOOLS_SCHEMA_PATH.read_text(encoding="utf-8"))
        for t in tools_data.get("tools", []):
            name = t.get("name")
            if name:
                valid_tools.add(name)

    valid_personas = set()
    if PERSONAS_PATH.exists():
        persona_data = json.loads(PERSONAS_PATH.read_text(encoding="utf-8"))
        for per in persona_data.get("personas", []):
            pid = per.get("persona_id")
            if pid:
                valid_personas.add(pid)

    return valid_skus, product_prices, valid_promos, valid_tools, valid_personas


def validate_scenario(data: dict, valid_skus: set, valid_promos: set,
                      valid_tools: set, valid_personas: set) -> list[str]:
    """Validate a single scenario dict; return list of error strings."""
    errors = []

    # Required top-level fields
    for field in ("scenario_id", "persona", "calls"):
        if field not in data:
            errors.append(f"Missing top-level required field: '{field}'")

    scenario_id = data.get("scenario_id", "")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        errors.append("Invalid or empty 'scenario_id'")

    persona = data.get("persona")
    if persona and valid_personas and persona not in valid_personas:
        # Warning/informational or relaxed check if persona is a custom descriptive string
        pass

    phone = data.get("customer_phone")
    if phone and not PHONE_REGEX.fullmatch(phone):
        errors.append(f"Invalid 'customer_phone': '{phone}' (must be 10 digits starting with 0)")

    level = data.get("level", "M1")
    if level not in ("M1", "M2"):
        errors.append(f"Invalid level '{level}' (expected M1 or M2)")

    calls = data.get("calls")
    if not isinstance(calls, dict) or not calls:
        errors.append("'calls' must be a non-empty dictionary of call_1, call_2...")
        return errors

    call_keys = sorted(calls.keys())
    for call_no, call_name in enumerate(call_keys, 1):
        call = calls[call_name]
        if not isinstance(call, dict):
            errors.append(f"{call_name} must be a dictionary")
            continue

        # Turns validation
        turns = call.get("customer_turns") or call.get("customer_turns_asr")
        if not isinstance(turns, list) or not turns:
            errors.append(f"{call_name}: missing or empty 'customer_turns'")
        else:
            for idx, turn in enumerate(turns):
                if not isinstance(turn, str) or not turn.strip():
                    errors.append(f"{call_name}: turn {idx+1} is empty or not string")

        # Date validation
        call_date = call.get("call_date")
        if call_date:
            if not isinstance(call_date, str) or not DATE_REGEX.fullmatch(call_date):
                errors.append(f"{call_name}: invalid 'call_date': '{call_date}'")
            else:
                try:
                    date.fromisoformat(call_date)
                except ValueError:
                    errors.append(f"{call_name}: call_date '{call_date}' is out of bounds")

        days_later = call.get("days_later")
        if days_later is not None and (type(days_later) is not int or days_later < 0):
            errors.append(f"{call_name}: 'days_later' must be non-negative integer")

        # Channel validation
        channel = call.get("channel", "hotline")
        if channel not in ("hotline", "chat_fanpage", "zalo_oa", "web_chat", "other"):
            errors.append(f"{call_name}: invalid channel '{channel}'")

        # SKU check in facts_established
        facts_est = call.get("facts_established", {})
        if isinstance(facts_est, dict):
            sku = facts_est.get("product_advised")
            if sku and valid_skus and sku not in valid_skus:
                errors.append(f"{call_name}: 'product_advised' SKU '{sku}' not found in catalog")
            var_sku = facts_est.get("variant_sku")
            if var_sku and valid_skus and var_sku not in valid_skus:
                errors.append(f"{call_name}: 'variant_sku' '{var_sku}' not found in catalog")
            promo = facts_est.get("promo_code")
            if promo and valid_promos and promo not in valid_promos:
                errors.append(f"{call_name}: 'promo_code' '{promo}' not found in promotions catalog")

        # success_if validation
        success_if = call.get("success_if")
        if success_if and isinstance(success_if, dict):
            tool_called = success_if.get("tool_called")
            if tool_called and valid_tools and tool_called not in valid_tools:
                errors.append(f"{call_name}: success_if 'tool_called' '{tool_called}' is not a valid BTC tool")
            args_match = success_if.get("args_match")
            if args_match and isinstance(args_match, dict):
                match_sku = args_match.get("sku") or args_match.get("new_variant_sku")
                if match_sku and valid_skus and match_sku not in valid_skus:
                    errors.append(f"{call_name}: success_if args_match SKU '{match_sku}' not in catalog")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate scenario JSON files")
    parser.add_argument("paths", nargs="*", type=Path, help="Paths to scenario JSON files")
    parser.add_argument("--all", action="store_true", help="Validate all scenarios in eval_harness/scenarios")
    parser.add_argument("--btc-samples", action="store_true", help="Validate BTC public samples")
    args = parser.parse_args()

    valid_skus, product_prices, valid_promos, valid_tools, valid_personas = load_btc_catalogs()
    print(f"Loaded from BTC: {len(valid_skus)} SKUs, {len(valid_promos)} Promos, "
          f"{len(valid_tools)} Tools, {len(valid_personas)} Personas\n")

    targets = list(args.paths)
    if args.all:
        scenarios_dir = Path(__file__).parent / "scenarios"
        if scenarios_dir.exists():
            targets.extend(sorted(scenarios_dir.glob("*.json")))

    if args.btc_samples:
        btc_samples_dir = BTC_DIR / "test_set" / "public_sample"
        if btc_samples_dir.exists():
            targets.extend(sorted(btc_samples_dir.glob("*.json")))

    if not targets:
        print("No files to validate. Use --all, --btc-samples or pass file paths.")
        return 0

    total_files = len(targets)
    passed_files = 0
    total_turns = 0

    for path in targets:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[FAIL] {path.name}: JSON parse error: {exc}")
            continue

        errs = validate_scenario(data, valid_skus, valid_promos, valid_tools, valid_personas)
        scenario_turns = sum(len(c.get("customer_turns") or c.get("customer_turns_asr") or [])
                             for c in data.get("calls", {}).values() if isinstance(c, dict))
        total_turns += scenario_turns

        if errs:
            print(f"[FAIL] {path.name} ({data.get('scenario_id')}) - {len(errs)} errors:")
            for err in errs:
                print(f"       - {err}")
        else:
            calls_count = len(data.get("calls", {}))
            print(f"[PASS] {path.name:<32} ID: {data.get('scenario_id'):<12} "
                  f"Calls: {calls_count:<2} Turns: {scenario_turns:<2}")
            passed_files += 1

    print(f"\n==========================================")
    print(f"Validation summary: {passed_files}/{total_files} scenarios passed")
    print(f"Total turns: {total_turns}")
    print(f"==========================================")

    return 0 if passed_files == total_files else 1


if __name__ == "__main__":
    sys.exit(main())
