#!/usr/bin/env python3
"""Record a sell-path for the fishing bot.

Walk-through:
  Phase 1 — "To Fisherman": you walk from the dock to the fisherman NPC.
  Phase 2 — "Sell":          you click the Sell All button / OK dialogs.
  Phase 3 — "Back to Dock":  you walk back to the dock and sit down.

Each phase is recorded separately. Press F8 to end the current phase and
move to the next one. The script captures every arrow-key press/release
and mouse click with millisecond timestamps, then saves a JSON file in
the sell_paths/ folder.

Usage:
    python record_sell_path.py
"""

import json
import os
import threading
import time

from pynput import keyboard, mouse

from ttr_bot.config.settings import SELL_PATHS_DIR
from ttr_bot.core.window_manager import find_ttr_window

TRACKED_KEYS = {
    keyboard.Key.up,
    keyboard.Key.down,
    keyboard.Key.left,
    keyboard.Key.right,
}


class _RecordingState:
    """Mutable container for the current recording session."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.start_time: float = 0.0
        self.held_keys: set[str] = set()


_rec = _RecordingState()
_phase_done = threading.Event()


def _ts() -> float:
    return round(time.time() - _rec.start_time, 3)


# ---------------------------------------------------------------------------
# Keyboard listener
# ---------------------------------------------------------------------------


def _on_key_press(key):
    if key == keyboard.Key.f8:
        _phase_done.set()
        return

    if key in TRACKED_KEYS:
        name = key.name  # "up", "down", "left", "right"
        if name not in _rec.held_keys:
            _rec.held_keys.add(name)
            _rec.events.append({"t": _ts(), "type": "key_down", "key": name})


def _on_key_release(key):
    if key in TRACKED_KEYS:
        name = key.name
        if name in _rec.held_keys:
            _rec.held_keys.discard(name)
            _rec.events.append({"t": _ts(), "type": "key_up", "key": name})


# ---------------------------------------------------------------------------
# Mouse listener
# ---------------------------------------------------------------------------


def _on_click(x, y, button, pressed):
    if button == mouse.Button.left:
        action = "mouse_down" if pressed else "mouse_up"
        win = find_ttr_window()
        if win is not None:
            wx = x - win.x
            wy = y - win.y
            _rec.events.append({"t": _ts(), "type": action, "x": wx, "y": wy})
        else:
            _rec.events.append({"t": _ts(), "type": action, "x": x, "y": y})


# ---------------------------------------------------------------------------
# Recording phases
# ---------------------------------------------------------------------------


def _record_phase(phase_name: str) -> list[dict]:
    _rec.events = []
    _rec.held_keys.clear()
    _phase_done.clear()
    _rec.start_time = time.time()

    print(f"\n  Recording: {phase_name}")
    print("  Use arrow keys to walk, mouse to click. Press F8 when done.")

    kb_listener = keyboard.Listener(on_press=_on_key_press, on_release=_on_key_release)
    ms_listener = mouse.Listener(on_click=_on_click)
    kb_listener.start()
    ms_listener.start()

    _phase_done.wait()

    kb_listener.stop()
    ms_listener.stop()

    result = list(_rec.events)
    print(f"  Recorded {len(result)} events in {_ts():.1f}s")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_phase_start = threading.Event()


def _wait_for_f7():
    """Block until F7 is pressed (starts/advances recording)."""
    _phase_start.clear()

    def _on_press(key):
        if key == keyboard.Key.f7:
            _phase_start.set()
            return False  # stop listener
        return None

    with keyboard.Listener(on_press=_on_press):
        _phase_start.wait()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Name for this sell path")
    args = parser.parse_args()
    name = args.name

    print("=" * 60)
    print("  TTR Bot — Sell Path Recorder")
    print(f"  Location: {name}")
    print("=" * 60)
    print()
    print("  Controls:  F7 = start next phase")
    print("             F8 = end current phase")
    print()
    print("  Focus TTR and use arrow keys / mouse. No need to switch back here.")
    print()

    phases = [
        ("1/3", "WALK TO FISHERMAN", "Walk toward the fisherman NPC until the sell dialog opens."),
        ("2/3", "SELL FISH", "Click Sell All and dismiss any dialogs."),
        ("3/3", "WALK BACK TO DOCK", "Walk back to the dock and sit down to fish."),
    ]

    results: list[list[dict]] = []
    for step, title, desc in phases:
        print(f"  Phase {step}: {title}")
        print(f"    {desc}")
        print("    >>> Press F7 in TTR to START recording <<<")
        _wait_for_f7()
        print("    Recording... (press F8 to stop)")
        events = _record_phase(title)
        results.append(events)
        print()

    os.makedirs(SELL_PATHS_DIR, exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "-")
    filename = f"{safe_name}.json"
    path = os.path.join(SELL_PATHS_DIR, filename)

    data = {
        "name": name,
        "to_fisherman": results[0],
        "sell_actions": results[1],
        "to_dock": results[2],
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    total = sum(len(r) for r in results)
    print(f"  Saved → {path}")
    print(f"  ({len(results[0])} + {len(results[1])} + {len(results[2])} = {total} events)")
    print("=" * 60)


if __name__ == "__main__":
    main()
