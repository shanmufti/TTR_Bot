"""Sell controller — stub kept for data-path compatibility.

The sell/walk navigation has been removed.  Only the path-listing
helpers remain so the data/sell_paths/ directory is still loadable.
"""

import json
import os

from ttr_bot.config.settings import SELL_PATHS_DIR
from ttr_bot.utils.logger import log


def list_sell_paths() -> list[dict]:
    """Return metadata for recorded sell-path JSON files."""
    if not os.path.isdir(SELL_PATHS_DIR):
        return []
    paths: list[dict] = []
    for fname in sorted(os.listdir(SELL_PATHS_DIR)):
        if not fname.endswith(".json"):
            continue
        full = os.path.join(SELL_PATHS_DIR, fname)
        try:
            with open(full) as f:
                data = json.load(f)
            paths.append({"name": data.get("name", fname), "filename": fname, "path": full})
        except Exception:
            log.debug("Skipping unreadable sell path: %s", fname)
            continue
    return paths


def load_sell_path(filepath: str) -> dict | None:
    """Load a single sell-path JSON file."""
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception:
        return None
