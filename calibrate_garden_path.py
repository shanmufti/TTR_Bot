"""Record walk paths between flower beds and save as a routine JSON.

Usage:
    python calibrate_garden_path.py [--beds N]

A small 'Mark Bed' button floats on top of TTR.  Walk your toon
normally in-game, then click the button (or press Enter in it)
each time you arrive at a new bed.  Between clicks, the script
records arrow-key inputs by briefly polling pyautogui.

The game window is automatically refocused after every button click
so your arrow keys keep working in TTR.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import subprocess
import tkinter as tk
from threading import Thread, Event

import cv2
import pyautogui
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventGetIntegerValueField,
    CGEventSourceCreate,
    CGEventTapCreate,
    CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent,
    CFRunLoopAddSource,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionListenOnly,
    kCFRunLoopCommonModes,
    kCGKeyboardEventKeycode,
)

from config import settings

# macOS virtual key codes for arrow keys
_VK_TO_DIR = {
    123: "left",
    124: "right",
    125: "down",
    126: "up",
}


class _KeyLogger:
    """Background thread that listens for arrow key events via Quartz."""

    def __init__(self) -> None:
        self._segments: list[dict] = []
        self._held: dict[str, float] = {}
        self._stop = Event()
        self._thread: Thread | None = None
        self._run_loop = None

    @property
    def segments(self) -> list[dict]:
        return list(self._segments)

    def start(self) -> None:
        self._segments = []
        self._held = {}
        self._stop.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def flush_and_reset(self) -> list[dict]:
        """Flush any held keys, return recorded segments, and reset."""
        now = time.monotonic()
        for direction, start in list(self._held.items()):
            dur = round(now - start, 3)
            if dur > 0.03:
                self._segments.append({"direction": direction, "duration": dur})
        self._held.clear()
        result = self._segments[:]
        self._segments = []
        return result

    def stop(self) -> None:
        self._stop.set()
        if self._run_loop:
            CFRunLoopStop(self._run_loop)
        if self._thread:
            self._thread.join(timeout=2)

    def _callback(self, proxy, event_type, event, refcon):
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        direction = _VK_TO_DIR.get(keycode)
        if direction is None:
            return event

        now = time.monotonic()
        if event_type == kCGEventKeyDown:
            if direction not in self._held:
                self._held[direction] = now
        elif event_type == kCGEventKeyUp:
            if direction in self._held:
                start = self._held.pop(direction)
                dur = round(now - start, 3)
                if dur > 0.03:
                    self._segments.append({"direction": direction, "duration": dur})

        return event

    def _run(self) -> None:
        mask = (1 << kCGEventKeyDown) | (1 << kCGEventKeyUp)
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if tap is None:
            print("ERROR: Could not create event tap.")
            print("Grant Accessibility permission to Terminal/iTerm in")
            print("System Settings → Privacy & Security → Accessibility")
            return

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        self._run_loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._run_loop, source, kCFRunLoopCommonModes)
        CFRunLoopRun()


def _focus_ttr() -> None:
    """Bring TTR to the foreground."""
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "Toontown Rewritten" to activate'],
            timeout=2, capture_output=True,
        )
    except Exception:
        pass


class PathRecorder:
    """Tiny overlay window with a 'Mark Bed' button."""

    def __init__(self, num_beds: int) -> None:
        self._num_beds = num_beds
        self._beds: list[list[dict]] = []
        self._key_logger = _KeyLogger()
        self._bed_index = 1
        self._done = False

        self._root = tk.Tk()
        self._root.title("Garden Path")
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#0f3460")
        self._root.geometry("300x140")
        self._root.resizable(False, False)

        self._label = tk.Label(
            self._root,
            text="",
            font=("Helvetica", 13, "bold"),
            fg="#eaeaea",
            bg="#0f3460",
            wraplength=280,
        )
        self._label.pack(pady=(12, 6))

        self._btn = tk.Button(
            self._root,
            text="",
            font=("Helvetica", 14, "bold"),
            width=22,
            command=self._on_click,
        )
        self._btn.pack(pady=8)

        self._root.bind("<Return>", lambda _: self._on_click())
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_ui()

    def run(self) -> list[list[dict]]:
        self._root.mainloop()
        return self._beds

    def _update_ui(self) -> None:
        if self._bed_index == 1:
            self._label.config(text=f"Stand at bed 1. ({self._num_beds} beds total)\nClick Start then walk to bed 2.")
            self._btn.config(text="▶ Start")
        elif self._bed_index <= self._num_beds:
            self._label.config(text=f"Walk to bed {self._bed_index} in TTR.\nClick when you arrive.")
            self._btn.config(text=f"✓ Arrived at bed {self._bed_index}")
        else:
            self._label.config(text="Done! Saved to\ngardening_routines/full_cycle.json")
            self._btn.config(text="Close", command=self._root.destroy)

    def _on_click(self) -> None:
        if self._done:
            return

        if self._bed_index == 1:
            # Capture starting position screenshot for alignment
            self._capture_start_screenshot()
            self._beds.append([])
            self._bed_index = 2
            self._key_logger.start()
            self._update_ui()
            _focus_ttr()
            return

        # Record segments for this bed
        segments = self._key_logger.flush_and_reset()
        self._beds.append(segments)
        desc = ", ".join(f"{s['direction']} {s['duration']}s" for s in segments)
        print(f"  Bed {self._bed_index}: {desc or '(no movement)'}")

        if self._bed_index >= self._num_beds:
            self._key_logger.stop()
            self._done = True
            self._save()
            self._update_ui()
        else:
            self._bed_index += 1
            self._update_ui()
            _focus_ttr()

    def _capture_start_screenshot(self) -> None:
        """Capture the TTR screen at the starting position for alignment."""
        from core.window_manager import find_ttr_window
        from core.screen_capture import capture_window

        win = find_ttr_window()
        if win is None:
            print("  Warning: could not capture start screenshot (TTR not found)")
            return
        frame = capture_window(win)
        if frame is None:
            print("  Warning: could not capture start screenshot")
            return

        os.makedirs(settings.GARDENING_ROUTINES_DIR, exist_ok=True)
        path = os.path.join(settings.GARDENING_ROUTINES_DIR, "start_position.png")
        cv2.imwrite(path, frame)
        print(f"  Saved start position screenshot → {path}")

    def _on_close(self) -> None:
        self._key_logger.stop()
        self._root.destroy()

    def _save(self) -> None:
        routine = {
            "_description": f"Auto-recorded garden path for {self._num_beds} beds.",
            "repeat": 1,
            "beds": self._beds,
        }

        os.makedirs(settings.GARDENING_ROUTINES_DIR, exist_ok=True)
        path = os.path.join(settings.GARDENING_ROUTINES_DIR, "full_cycle.json")
        with open(path, "w") as f:
            json.dump(routine, f, indent=2)

        total_walks = sum(len(b) for b in self._beds)
        print(f"\nSaved: {path}")
        print(f"  {self._num_beds} beds, {total_walks} walk segments")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record garden walk paths")
    parser.add_argument("--beds", type=int, default=10, help="Number of flower beds")
    args = parser.parse_args()

    print("=" * 50)
    print("  Garden Path Recorder")
    print("  Arrow keys are recorded in the background.")
    print("  TTR stays focused — click the overlay button")
    print("  each time you arrive at a bed.")
    print("=" * 50)

    recorder = PathRecorder(args.beds)
    recorder.run()


if __name__ == "__main__":
    main()
