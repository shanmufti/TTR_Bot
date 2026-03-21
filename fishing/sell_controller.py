"""Sell controller — replays recorded walk paths to sell fish and return.

Sell paths are JSON files in the sell_paths/ directory, recorded via
record_sell_path.py. Each file contains three phases of timed events:

  to_fisherman  — walk from dock to the fisherman NPC
  sell_actions   — click Sell All, dismiss dialogs
  to_dock        — walk back to the dock and sit down

Events are {t, type, key/x/y} dicts recorded with millisecond timestamps.
The replay engine sleeps between events to reproduce the original timing.
"""

from __future__ import annotations

import json
import os
import time

import pyautogui

from config.settings import PROJECT_ROOT
from core import input_controller as inp
from core.screen_capture import capture_window
from core.window_manager import find_ttr_window, WindowInfo
from vision.template_matcher import find_template
from utils.logger import log

SELL_PATHS_DIR = os.path.join(PROJECT_ROOT, "sell_paths")


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------

def list_sell_paths() -> list[dict]:
    """Return metadata for every recorded sell path.

    Each entry: {"name": "...", "filename": "...", "path": "/abs/..."}.
    """
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
            paths.append({
                "name": data.get("name", fname),
                "filename": fname,
                "path": full,
            })
        except Exception:
            continue
    return paths


def load_sell_path(filepath: str) -> dict | None:
    """Load a sell path JSON file."""
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to load sell path: %s", filepath)
        return None


# ---------------------------------------------------------------------------
# Event replay engine
# ---------------------------------------------------------------------------

def _replay_events(events: list[dict], win: WindowInfo | None = None) -> None:
    """Replay a list of recorded input events with original timing.

    Sleeps between events to match the delta-t from the recording.
    """
    if not events:
        return

    if win is None:
        win = find_ttr_window()

    prev_t = 0.0
    held_keys: set[str] = set()

    for ev in events:
        t = ev.get("t", 0.0)
        delta = t - prev_t
        if delta > 0.01:
            time.sleep(delta)
        prev_t = t

        ev_type = ev.get("type", "")

        if ev_type == "key_down":
            key = ev.get("key", "")
            if key and key not in held_keys:
                pyautogui.keyDown(key)
                held_keys.add(key)

        elif ev_type == "key_up":
            key = ev.get("key", "")
            if key and key in held_keys:
                pyautogui.keyUp(key)
                held_keys.discard(key)

        elif ev_type == "mouse_down":
            x, y = ev.get("x", 0), ev.get("y", 0)
            if win:
                pyautogui.moveTo(win.x + x, win.y + y)
            pyautogui.mouseDown()

        elif ev_type == "mouse_up":
            x, y = ev.get("x", 0), ev.get("y", 0)
            if win:
                pyautogui.moveTo(win.x + x, win.y + y)
            pyautogui.mouseUp()

    # Safety: release any keys still held
    for key in held_keys:
        pyautogui.keyUp(key)


# ---------------------------------------------------------------------------
# Sell-all helper (template-based fallback for the sell phase)
# ---------------------------------------------------------------------------

def _click_sell_all_template() -> None:
    """Find and click the Sell All button using template matching."""
    win = find_ttr_window()
    if win is None:
        return
    for _ in range(20):
        frame = capture_window(win)
        if frame is None:
            time.sleep(0.3)
            continue
        match = find_template(frame, "sell_all_button")
        if match is not None:
            inp.click(match.x, match.y, window=win)
            time.sleep(1.5)
            frame2 = capture_window(win)
            if frame2 is not None:
                ok = find_template(frame2, "ok_button")
                if ok is not None:
                    inp.click(ok.x, ok.y, window=win)
                    time.sleep(0.5)
            return
        time.sleep(0.3)
    log.warning("Sell All button not found via template matching")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def walk_and_sell(location: str, sell_path_file: str | None = None) -> None:
    """Execute a sell trip.

    If *sell_path_file* is given (absolute path to a JSON), that recorded
    path is replayed. Otherwise falls back to auto-discovering a matching
    path from sell_paths/ by location name.
    """
    log.info("Starting sell trip — location='%s'", location)

    # Resolve the sell path JSON
    path_data = None
    if sell_path_file and os.path.isfile(sell_path_file):
        path_data = load_sell_path(sell_path_file)

    if path_data is None:
        path_data = _find_path_by_name(location)

    if path_data is None:
        log.warning("No recorded sell path for '%s' — attempting template-only sell", location)
        _click_sell_all_template()
        return

    win = find_ttr_window()
    if win is None:
        log.warning("TTR window not found for sell trip")
        return

    # Phase 1: walk to fisherman
    log.info("Sell: walking to fisherman (%d events)", len(path_data.get("to_fisherman", [])))
    _replay_events(path_data.get("to_fisherman", []), win)
    time.sleep(0.5)

    # Phase 2: sell fish
    sell_events = path_data.get("sell_actions", [])
    if sell_events:
        log.info("Sell: replaying sell actions (%d events)", len(sell_events))
        _replay_events(sell_events, win)
    else:
        log.info("Sell: no recorded sell actions — using template matching")
        _click_sell_all_template()
    time.sleep(0.5)

    # Phase 3: walk back to dock
    log.info("Sell: walking back to dock (%d events)", len(path_data.get("to_dock", [])))
    _replay_events(path_data.get("to_dock", []), win)
    time.sleep(0.5)

    log.info("Sell trip complete")


def _find_path_by_name(location: str) -> dict | None:
    """Try to find a sell path whose 'name' field matches the location."""
    for entry in list_sell_paths():
        if entry["name"].lower() == location.lower():
            return load_sell_path(entry["path"])
    # Also try matching the filename stem
    safe = location.replace(" ", "_").replace("/", "-")
    candidate = os.path.join(SELL_PATHS_DIR, f"{safe}.json")
    if os.path.isfile(candidate):
        return load_sell_path(candidate)
    return None
