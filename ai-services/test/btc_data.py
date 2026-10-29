"""Locate the BTC release for tests without depending on one checkout layout."""

import os
from pathlib import Path


def btc_data_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    candidates = ([Path(os.environ["BTC_DATA_DIR"])] if os.environ.get("BTC_DATA_DIR")
                  else [root.parent / "BTC-Data-Vong1-TEAMS",
                        root / "BTC-Data-Vong1-TEAMS"])
    for candidate in candidates:
        if (candidate / "catalog" / "products.json").is_file():
            return candidate
    raise FileNotFoundError("BTC data not found; set BTC_DATA_DIR to the release directory")
