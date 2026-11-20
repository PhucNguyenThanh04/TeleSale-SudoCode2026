from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

from .entities import REFERENCE_DATE, Product, build_catalog

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR_NAME = "BTC-Data-Vong1-TEAMS"


def find_data_dir(cli_value: str | Path | None = None, required: bool = True) -> Path | None:
    candidates = [cli_value, os.environ.get("BTC_DATA_DIR"), REPO_ROOT.parent / DATA_DIR_NAME]
    for candidate in candidates:
        if candidate and (Path(candidate) / "catalog" / "products.json").is_file():
            return Path(candidate)
    if required:
        raise FileNotFoundError(
            f"Không tìm thấy {DATA_DIR_NAME}. Truyền --data-dir hoặc đặt biến môi trường BTC_DATA_DIR.")
    return None


def read_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_json_object(path: Path) -> dict:
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def text_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_catalog(data_dir: Path | None) -> tuple[Product, ...]:
    if data_dir is None:
        return ()
    payload = read_json(data_dir / "catalog" / "products.json")
    products = payload["products"] if isinstance(payload, dict) else payload
    return build_catalog(products)


def reference_date(ground_truth: dict) -> date:
    raw = ground_truth.get("reference_date")
    return date.fromisoformat(raw) if raw else REFERENCE_DATE


def _load_btc_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Không nạp được {path}")
    module = importlib.util.module_from_spec(spec)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def load_reference_eval(data_dir: Path) -> ModuleType:
    return _load_btc_module(data_dir / "eval" / "reference_eval.py", "btc_reference_eval")


def load_mock_tools(data_dir: Path) -> ModuleType:
    return _load_btc_module(data_dir / "eval" / "mock_tools.py", "btc_mock_tools")
