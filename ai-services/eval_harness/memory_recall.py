
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any

from app.mcp_servers.mcp_shared.episode_evidence import evidence_supports


_FREE_TEXT_SLOTS = {"blocker", "objection"}


def _slot_value_matches(slot: str, expected: Any, actual: Any,
                        budget_tolerance_pct: float = 0.15) -> bool:
    if expected == actual:
        return True
    if (slot == "budget_vnd" and isinstance(expected, (int, float)) and isinstance(actual, (int, float))
            and expected > 0 and abs(actual - expected) / float(expected) <= budget_tolerance_pct):
        return True
    if isinstance(expected, str) and isinstance(actual, str):
        if expected.casefold().strip() == actual.casefold().strip():
            return True
        if slot in _FREE_TEXT_SLOTS:
            def normalize(text):
                text = "".join(c for c in unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
                               if unicodedata.category(c) != "Mn")
                text = re.sub(r"\b(?:ong xa|anh nha)\b", "chong", text)
                return re.sub(r"\b(?:ba xa)\b", "vo", text)
            left, right = normalize(expected), normalize(actual)
            for signal in (r"\bkhong\b", r"\bda\s+(?:hoi|quyet|dong y)"):
                if bool(re.search(signal, left)) != bool(re.search(signal, right)):
                    return False
            actors = [{w for w in ("vo", "chong") if re.search(r"\b" + w + r"\b", text)}
                      for text in (left, right)]
            if actors[0] != actors[1]:
                return False
            return (left == right or evidence_supports(left, right)
                    or evidence_supports(right, left)
                    or left in right or right in left)
    return False


def evaluate_memory_recall(
    scenarios: dict[str, Any],
    trace_full: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    per_slot_expected: dict[str, int] = defaultdict(int)
    per_slot_matched: dict[str, int] = defaultdict(int)
    per_slot_written: dict[str, int] = defaultdict(int)
    per_scenario: dict[str, dict[str, Any]] = {}

    total_expected = 0
    total_matched = 0
    total_written = 0

    for sid, sc in scenarios.items():
        sc_expected = 0
        sc_matched = 0
        sc_written = 0
        missing_examples: list[dict[str, Any]] = []
        for call_name, call_spec in sc.get("calls", {}).items():
            established = call_spec.get("facts_established") or {}
            if not isinstance(established, dict):
                continue
            rows = trace_full.get((sid, call_name), [])
            writes_by_key: dict[str, list[Any]] = defaultdict(list)
            for row in rows:
                for write in row.get("memory_writes", []) or []:
                    if not isinstance(write, dict) or write.get("op") == "delete":
                        continue
                    key = write.get("key")
                    if isinstance(key, str) and key:
                        writes_by_key[key].append(write.get("value"))

            for key, vals in writes_by_key.items():
                if vals:
                    per_slot_written[key] += 1
                    sc_written += 1
                    total_written += 1

            for slot, exp_val in established.items():
                if slot == "phone_provided":
                    continue
                per_slot_expected[slot] += 1
                sc_expected += 1
                total_expected += 1
                actual_vals = writes_by_key.get(slot, [])
                if any(_slot_value_matches(slot, exp_val, act) for act in actual_vals):
                    per_slot_matched[slot] += 1
                    sc_matched += 1
                    total_matched += 1
                else:
                    missing_examples.append({
                        "call": call_name,
                        "slot": slot,
                        "expected": exp_val,
                        "actual_values": actual_vals,
                    })

        if sc_expected or sc_written:
            per_scenario[sid] = {
                "recall_pct": round(100.0 * sc_matched / sc_expected, 1) if sc_expected else None,
                "precision_pct": round(100.0 * sc_matched / sc_written, 1) if sc_written else None,
                "matched": sc_matched,
                "expected": sc_expected,
                "written": sc_written,
                "missing": missing_examples,
            }

    all_slots = sorted(set(per_slot_expected) | set(per_slot_written))
    slot_breakdown = {}
    for slot in all_slots:
        exp = per_slot_expected[slot]
        mat = per_slot_matched[slot]
        wrt = per_slot_written[slot]
        slot_breakdown[slot] = {
            "recall_pct": round(100.0 * mat / exp, 1) if exp else None,
            "precision_pct": round(100.0 * mat / wrt, 1) if wrt else None,
            "matched": mat,
            "expected": exp,
            "written": wrt,
        }

    return {
        "overall_recall_pct": round(100.0 * total_matched / total_expected, 1) if total_expected else None,
        "overall_precision_pct": round(100.0 * total_matched / total_written, 1) if total_written else None,
        "matched": total_matched,
        "expected": total_expected,
        "written": total_written,
        "by_slot": slot_breakdown,
        "by_scenario": per_scenario,
        "notes": [
            "Diagnostic matches expected slots per call; written is not a physical record count or a count of garbage facts.",
            "Expected facts are not exhaustive; valid extra writes and unmatched dynamic order IDs remain discrepancies.",
            "budget_vnd uses ±15% tolerance (e.g. SAMPLE-01 ground truth 5700000 vs spoken 'tầm 5 triệu').",
            "phone_provided is excluded per PB-08 (handled via identity linking, never stored raw).",
        ],
    }
