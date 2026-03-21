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
import time
import threading

from pynput import keyboard, mouse

from config.settings import PROJECT_ROOT
from core.window_manager import find_ttr_window

SELL_PATHS_DIR = os.path.join(PROJECT_ROOT, "sell_paths")

TRACKED_KEYS = {
    keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right,
}

_events: list[dict] = []
_phase_done = threading.Event()
_start_time: float = 0.0


def _ts() -> float:
    return round(time.time() - _start_time, 3)


# ---------------------------------------------------------------------------
# Keyboard listener
# ---------------------------------------------------------------------------

def _on_key_press(key):
    if key == keyboard.Key.f8:
        _phase_done.set()
        return

    if key in TRACKED_KEYS:
        name = key.name  # "up", "down", "left", "right"
        _events.append({"t": _ts(), "type": "key_down", "key": name})


def _on_key_release(key):
    if key in TRACKED_KEYS:
        name = key.name
        _events.append({"t": _ts(), "type": "key_up", "key": name})


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
            _events.append({"t": _ts(), "type": action, "x": wx, "y": wy})
        else:
            _events.append({"t": _ts(), "type": action, "x": x, "y": y})


# ---------------------------------------------------------------------------
# Recording phases
# ---------------------------------------------------------------------------

def _record_phase(phase_name: str) -> list[dict]:
    global _events, _start_time

    _events = []
    _phase_done.clear()
    _start_time = time.time()

    print(f"\n  Recording: {phase_name}")
    print("  Use arrow keys to walk, mouse to click. Press F8 when done.")

    kb_listener = keyboard.Listener(on_press=_on_key_press, on_release=_on_key_release)
    ms_listener = mouse.Listener(on_click=_on_click)
    kb_listener.start()
    ms_listener.start()

    _phase_done.wait()

    kb_listener.stop()
    ms_listener.stop()

    result = list(_events)
    print(f"  Recorded {len(result)} events in {_ts():.1f}s")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  TTR Bot — Sell Path Recorder")
    print("=" * 60)
    print()
    print("  This records your walk to the fisherman and back.")
    print("  You'll record 3 phases, pressing F8 after each one.")
    print()
    print("  Prerequisites:")
    print("    - Your toon must be at the fishing dock (just exited fishing)")
    print("    - TTR must be the focused window during recording")
    print()

    name = input("  Name for this path (e.g. 'Estate Left Dock'): ").strip()
    if not name:
        print("  Aborted — no name given.")
        return

    print()
    print("  Phase 1/3: WALK TO FISHERMAN")
    print("  Walk from the dock to the fisherman NPC.")
    input("  Press Enter to start recording, then F8 when you reach the fisherman...")
    to_fisherman = _record_phase("Walk to fisherman")

    print()
    print("  Phase 2/3: SELL FISH")
    print("  Click on the fisherman, click Sell All, dismiss any dialogs.")
    input("  Press Enter to start recording, then F8 when selling is done...")
    sell_actions = _record_phase("Sell fish")

    print()
    print("  Phase 3/3: WALK BACK TO DOCK")
    print("  Walk back to the dock and sit down to fish again.")
    input("  Press Enter to start recording, then F8 when you're back at the dock...")
    to_dock = _record_phase("Walk back to dock")

    # Save
    os.makedirs(SELL_PATHS_DIR, exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "-")
    filename = f"{safe_name}.json"
    path = os.path.join(SELL_PATHS_DIR, filename)

    data = {
        "name": name,
        "to_fisherman": to_fisherman,
        "sell_actions": sell_actions,
        "to_dock": to_dock,
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n  Saved → {path}")
    print(f"  ({len(to_fisherman)} + {len(sell_actions)} + {len(to_dock)} events)")
    print()
    print("  To use this path, select it in the bot GUI or set it in config.")
    print("=" * 60)


if __name__ == "__main__":
    main()
