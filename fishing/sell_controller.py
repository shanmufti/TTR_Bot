"""Walk-to-fisherman sell sequences for each fishing location.

Each location has a scripted movement pattern:
  1. Walk off the dock
  2. Walk to the fisherman NPC
  3. Click to sell all fish
  4. Walk back to the dock and sit down

These are based on the FishingLocationsWalking/*.cs strategies in the
reference C# bot, adapted for pyautogui on macOS.
"""

from __future__ import annotations

import time

from core import input_controller as inp
from core.screen_capture import capture_window
from core.window_manager import find_ttr_window
from vision.template_matcher import find_template
from utils.logger import log


def walk_and_sell(location: str) -> None:
    """Execute the sell trip for the given fishing location."""
    log.info("Starting sell trip for: %s", location)

    handler = _SELL_HANDLERS.get(location)
    if handler is None:
        log.warning("No sell handler for '%s' – skipping sell", location)
        return

    try:
        handler()
        log.info("Sell trip complete for: %s", location)
    except Exception:
        log.exception("Sell trip failed for: %s", location)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _walk(direction: str, seconds: float) -> None:
    """Walk in a direction by holding an arrow key."""
    key_map = {"up": "up", "down": "down", "left": "left", "right": "right"}
    key = key_map.get(direction)
    if key is None:
        log.warning("Unknown walk direction: %s", direction)
        return
    inp.hold_key(key, seconds)
    time.sleep(0.2)


def _click_sell_all() -> None:
    """Find and click the Sell All button, then dismiss any confirmation."""
    win = find_ttr_window()
    if win is None:
        return
    for _ in range(15):
        frame = capture_window(win)
        if frame is None:
            time.sleep(0.3)
            continue
        match = find_template(frame, "sell_all_button")
        if match is not None:
            inp.click(match.x, match.y, window=win)
            time.sleep(1.5)
            # Try to dismiss any OK confirmation
            frame2 = capture_window(win)
            if frame2 is not None:
                ok = find_template(frame2, "ok_button")
                if ok is not None:
                    inp.click(ok.x, ok.y, window=win)
                    time.sleep(0.5)
            return
        time.sleep(0.3)
    log.warning("Sell All button not found")


# ---------------------------------------------------------------------------
# Location-specific sell sequences
# ---------------------------------------------------------------------------

def _sell_estate() -> None:
    """Estate (Left Dock): walk right to fisherman, sell, walk back left."""
    _walk("right", 3.0)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("left", 3.0)
    time.sleep(0.5)


def _sell_ttc_punchline() -> None:
    """TTC Punchline Place: walk down off dock, right to fisherman, sell, return."""
    _walk("down", 1.5)
    _walk("right", 2.5)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("left", 2.5)
    _walk("up", 1.5)
    time.sleep(0.5)


def _sell_dd_lighthouse() -> None:
    """DD Lighthouse Lane: walk down, left to fisherman, sell, return."""
    _walk("down", 1.5)
    _walk("left", 3.0)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("right", 3.0)
    _walk("up", 1.5)
    time.sleep(0.5)


def _sell_dg_elm() -> None:
    """DG Elm Street: walk up off dock, right to fisherman, sell, return."""
    _walk("up", 1.5)
    _walk("right", 2.5)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("left", 2.5)
    _walk("down", 1.5)
    time.sleep(0.5)


def _sell_mm_tenor() -> None:
    """MM Tenor Terrace: walk down off dock, left to fisherman, sell, return."""
    _walk("down", 2.0)
    _walk("left", 2.0)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("right", 2.0)
    _walk("up", 2.0)
    time.sleep(0.5)


def _sell_brrrgh_polar() -> None:
    """Brrrgh Polar Place: walk down off dock, right to fisherman, sell, return."""
    _walk("down", 2.0)
    _walk("right", 3.0)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("left", 3.0)
    _walk("up", 2.0)
    time.sleep(0.5)


def _sell_brrrgh_walrus() -> None:
    """Brrrgh Walrus Way: walk left off dock, down to fisherman, sell, return."""
    _walk("left", 1.5)
    _walk("down", 2.5)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("up", 2.5)
    _walk("right", 1.5)
    time.sleep(0.5)


def _sell_brrrgh_sleet() -> None:
    """Brrrgh Sleet Street: walk down off dock, left to fisherman, sell, return."""
    _walk("down", 1.5)
    _walk("left", 2.5)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("right", 2.5)
    _walk("up", 1.5)
    time.sleep(0.5)


def _sell_ddl_lullaby() -> None:
    """DDL Lullaby Lane: walk down off dock, right to fisherman, sell, return."""
    _walk("down", 2.0)
    _walk("right", 2.5)
    time.sleep(0.5)
    _click_sell_all()
    time.sleep(0.5)
    _walk("left", 2.5)
    _walk("up", 2.0)
    time.sleep(0.5)


def _sell_fish_anywhere() -> None:
    """Fish Anywhere: no sell trip, just a no-op."""
    pass


_SELL_HANDLERS: dict[str, callable] = {
    "Fish Anywhere": _sell_fish_anywhere,
    "Estate (Left Dock)": _sell_estate,
    "TTC Punchline Place": _sell_ttc_punchline,
    "DD Lighthouse Lane": _sell_dd_lighthouse,
    "DG Elm Street": _sell_dg_elm,
    "MM Tenor Terrace": _sell_mm_tenor,
    "Brrrgh Polar Place": _sell_brrrgh_polar,
    "Brrrgh Walrus Way": _sell_brrrgh_walrus,
    "Brrrgh Sleet Street": _sell_brrrgh_sleet,
    "DDL Lullaby Lane": _sell_ddl_lullaby,
}
