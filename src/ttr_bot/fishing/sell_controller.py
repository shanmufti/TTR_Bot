"""Sell controller — vision-based navigation to sell fish and return.

Uses screen detection to:
  1. Turn the toon until the fisherman NPC is in view
  2. Walk toward the fisherman until the sell dialog auto-opens
  3. Click to sell
  4. Turn until the pond is in view
  5. Walk back to the dock until the fishing UI (cast button) appears
"""

from __future__ import annotations

import json
import os
import time

import cv2
import numpy as np
import pyautogui

from ttr_bot.config.settings import SELL_PATHS_DIR
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window, focus_window, WindowInfo
from ttr_bot.vision.template_matcher import find_template
from ttr_bot.vision.pond_detector import detect_pond
from ttr_bot.utils.logger import log

_TURN_STEP_S = 0.35
_WALK_POLL_S = 0.5
_MAX_TURN_STEPS = 20
_MAX_WALK_S = 15


# ---------------------------------------------------------------------------
# Path discovery (kept for backward compat with GUI)
# ---------------------------------------------------------------------------

def list_sell_paths() -> list[dict]:
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
            continue
    return paths


def load_sell_path(filepath: str) -> dict | None:
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception:
        log.exception("Failed to load sell path: %s", filepath)
        return None


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------

def _detect_npc_label(frame: np.ndarray) -> tuple[int, int] | None:
    """Detect an NPC name tag (orange text) in the frame.

    Returns (cx, cy) of the best orange text cluster that looks like
    an NPC label, or None if not found. Filters aggressively:
    - Only looks in the middle third of the screen (vertically)
    - Requires multiple small orange blobs clustered together (text chars)
    - Rejects large solid orange regions (fences, hats, etc.)
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([8, 150, 180]), np.array([22, 255, 255]))

    y_start = h // 4
    y_end = 3 * h // 4
    roi = mask[y_start:y_end, :]

    contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    text_clusters: list[tuple[int, int, int, int, int]] = []
    for c in contours:
        area = cv2.contourArea(c)
        x, y, cw, ch = cv2.boundingRect(c)
        aspect = cw / max(1, ch)
        if 20 < area < 2000 and 0.2 < aspect < 8.0 and ch < 60:
            text_clusters.append((x, y, cw, ch, area))

    if len(text_clusters) < 3:
        return None

    text_clusters.sort(key=lambda t: t[0])
    best_group: list[tuple[int, int, int, int, int]] = []
    for i, blob in enumerate(text_clusters):
        group = [blob]
        bx, by = blob[0], blob[1]
        for other in text_clusters[i + 1:]:
            if abs(other[1] - by) < 30 and abs(other[0] - bx) < 300:
                group.append(other)
                bx = other[0]
        if len(group) > len(best_group):
            best_group = group

    if len(best_group) < 3:
        return None

    xs = [b[0] + b[2] // 2 for b in best_group]
    ys = [b[1] + b[3] // 2 for b in best_group]
    cx = sum(xs) // len(xs)
    cy = y_start + sum(ys) // len(ys)
    return cx, cy


def _detect_pond_center(frame: np.ndarray) -> tuple[int, int] | None:
    """Detect the pond (blue water) and return its center position."""
    pond = detect_pond(frame)
    if pond.empty:
        return None
    return pond.x + pond.width // 2, pond.y + pond.height // 2


def _has_sell_dialog(frame: np.ndarray) -> bool:
    """Check if the fisherman sell dialog is on screen.

    Only uses template matching for known dialog buttons.
    """
    if find_template(frame, "fish_popup_close") is not None:
        return True
    if find_template(frame, "jellybean_exit") is not None:
        return True
    return False


def _has_cast_button(frame: np.ndarray) -> bool:
    """Check if the red fishing cast button is visible (means we're on the dock)."""
    return find_template(frame, "red_fishing_button") is not None


# ---------------------------------------------------------------------------
# Navigation primitives
# ---------------------------------------------------------------------------

def _turn_toward(win: WindowInfo, detector, direction: str = "right") -> bool:
    """Turn the toon until detector(frame) returns a truthy value.

    Returns True if the target was found, False after a full rotation.
    """
    null_frames = 0
    for step in range(_MAX_TURN_STEPS):
        frame = capture_window(win)
        if frame is None:
            null_frames += 1
            if null_frames > 5:
                log.warning("Game window lost during turn")
                return False
            time.sleep(0.3)
            continue
        null_frames = 0

        result = detector(frame)
        if result:
            log.info("Target found after %d turn steps", step)
            return True

        pyautogui.keyDown(direction)
        time.sleep(_TURN_STEP_S)
        pyautogui.keyUp(direction)
        time.sleep(0.15)

    log.warning("Target not found after %d turn steps", _MAX_TURN_STEPS)
    return False


def _walk_forward_until(win: WindowInfo, condition, max_seconds: float = _MAX_WALK_S) -> bool:
    """Walk forward (Up key) until condition(frame) returns True."""
    null_frames = 0
    pyautogui.keyDown("up")
    start = time.monotonic()
    try:
        while time.monotonic() - start < max_seconds:
            time.sleep(_WALK_POLL_S)
            frame = capture_window(win)
            if frame is None:
                null_frames += 1
                if null_frames > 5:
                    log.warning("Game window lost during walk")
                    return False
                continue
            null_frames = 0
            if condition(frame):
                log.info("Walk condition met after %.1fs", time.monotonic() - start)
                return True
    finally:
        pyautogui.keyUp("up")
    log.warning("Walk condition not met after %.1fs", max_seconds)
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def walk_and_sell(location: str, sell_path_file: str | None = None) -> None:  # noqa: ARG001
    """Execute a sell trip using vision-based navigation.

    1. Turn until fisherman NPC label is visible
    2. Walk toward fisherman until sell dialog auto-opens
    3. Click to sell
    4. Turn until pond is visible
    5. Walk back to dock until cast button appears
    """
    log.info("Starting sell trip — location='%s'", location)

    win = find_ttr_window()
    if win is None:
        log.warning("TTR window not found for sell trip")
        return

    focus_window()
    time.sleep(0.3)

    # Phase 1: find and walk to fisherman
    log.info("Sell: turning to find fisherman…")
    found = _turn_toward(win, _detect_npc_label)
    if not found:
        log.warning("Could not find fisherman NPC — trying to walk anyway")

    log.info("Sell: walking to fisherman…")
    dialog_opened = _walk_forward_until(win, _has_sell_dialog, max_seconds=10)

    if not dialog_opened:
        log.warning("Sell dialog did not open — retrying with wider search")
        for retry_dir in ["left", "right", "left"]:
            _turn_toward(win, _detect_npc_label, direction=retry_dir)
            dialog_opened = _walk_forward_until(win, _has_sell_dialog, max_seconds=8)
            if dialog_opened:
                break

    if not dialog_opened:
        log.warning("Sell dialog never appeared — aborting sell trip")
        return

    # Phase 2: sell fish
    log.info("Sell: dialog detected, clicking to sell…")
    time.sleep(0.5)
    _click_sell_dialog(win)
    time.sleep(1.0)

    # Phase 3: find and walk back to dock
    log.info("Sell: turning to find pond/dock…")
    focus_window()
    found = _turn_toward(win, _detect_pond_center)
    if not found:
        log.warning("Could not find pond — walking blindly")

    log.info("Sell: walking to dock…")
    on_dock = _walk_forward_until(win, _has_cast_button, max_seconds=12)

    if not on_dock:
        log.info("Cast button not found — trying alternate directions")
        for retry_dir in ["left", "right"]:
            _turn_toward(win, _detect_pond_center, direction=retry_dir)
            on_dock = _walk_forward_until(win, _has_cast_button, max_seconds=8)
            if on_dock:
                break

    log.info("Sell trip complete (on_dock=%s)", on_dock)


def _click_sell_dialog(win: WindowInfo) -> None:
    """Click the sell button in the fisherman's dialog."""
    for _ in range(10):
        frame = capture_window(win)
        if frame is None:
            time.sleep(0.3)
            continue

        close = find_template(frame, "fish_popup_close")
        if close is not None:
            inp.ensure_focused()
            time.sleep(0.1)
            inp.click(close.x, close.y, window=win)
            time.sleep(0.5)
            continue

        if not _has_sell_dialog(frame):
            return

        time.sleep(0.3)
    log.warning("Could not dismiss sell dialog")
