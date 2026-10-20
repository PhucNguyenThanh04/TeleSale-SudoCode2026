"""Small, fixture-only oracle for multi-session memory snapshots."""

import json
from pathlib import Path
from typing import Any


def load_cases(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
        raise ValueError("memory contract must be a list of cases")
    return cases


def check_snapshot(expected: dict, actual: dict) -> list[str]:
    """Compare declared fields only; never copy customer values into errors."""
    errors: list[str] = []

    def contains_text(value: Any, needle: str) -> bool:
        if isinstance(value, str):
            return needle in value
        if isinstance(value, dict):
            return any(contains_text(item, needle) for item in value.values())
        if isinstance(value, list):
            return any(contains_text(item, needle) for item in value)
        return False

    def visit(want: Any, got: Any, path: str) -> None:
        if isinstance(want, dict) and set(want) == {"not_equals"}:
            if type(want["not_equals"]) is type(got) and want["not_equals"] == got:
                errors.append(f"{path}: forbidden value")
        elif isinstance(want, dict) and set(want) == {"not_contains"}:
            needle = want["not_contains"]
            if (not isinstance(needle, str) or not isinstance(got, (str, dict, list))
                    or contains_text(got, needle)):
                errors.append(f"{path}: forbidden content or wrong type")
        elif isinstance(want, dict) and set(want) == {"contains"}:
            if not isinstance(got, list) or not any(
                not check_snapshot({"item": want["contains"]}, {"item": item}) for item in got
            ):
                errors.append(f"{path}: required item missing")
        elif isinstance(want, dict):
            if not isinstance(got, dict):
                errors.append(f"{path}: expected object")
                return
            for key, value in want.items():
                child = f"{path}.{key}" if path else str(key)
                if key not in got:
                    errors.append(f"{child}: missing")
                else:
                    visit(value, got[key], child)
        elif isinstance(want, list):
            if not isinstance(got, list) or len(want) > len(got):
                errors.append(f"{path}: expected list prefix")
                return
            for index, item in enumerate(want):
                visit(item, got[index], f"{path}[{index}]")
        elif type(want) is not type(got) or want != got:
            errors.append(f"{path}: mismatch")

    visit(expected, actual, "")
    return errors
