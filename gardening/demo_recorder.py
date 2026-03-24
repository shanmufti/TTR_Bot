"""Record a TTR gardening demo: screen frames + keyboard events.

Captures the TTR game window at ~5 FPS and logs all arrow-key events
via macOS Quartz event tapping.  The recording is saved to a timestamped
directory under gardening_routines/demos/ for later processing by
demo_processor.py.
"""

from __future__ import annotations

import json
import os
import time
import threading
from datetime import datetime
from typing import Callable

import cv2

from Quartz import (
    CGEventGetIntegerValueField,
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
from core.window_manager import find_ttr_window
from core.screen_capture import capture_window
from utils.logger import log

_VK_TO_DIR = {123: "left", 124: "right", 125: "down", 126: "up"}


class _KeyEventLogger:
    """Background thread that captures arrow key events via Quartz."""

    def __init__(self, base_time: float) -> None:
        self._base_time = base_time
        self._events: list[dict] = []
        self._held: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_loop = None
        self._lock = threading.Lock()

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._flush_held()
        self._stop.set()
        if self._run_loop:
            CFRunLoopStop(self._run_loop)
        if self._thread:
            self._thread.join(timeout=2)

    def get_events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def _flush_held(self) -> None:
        now = time.monotonic()
        with self._lock:
            for direction, start in dict(self._held).items():
                rel_t = round(now - self._base_time, 3)
                dur = round(now - start, 3)
                if dur > 0.02:
                    self._events.append({
                        "t": rel_t, "key": direction,
                        "event": "up", "duration": dur,
                    })
            self._held.clear()

    def _callback(self, proxy, event_type, event, refcon):
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        direction = _VK_TO_DIR.get(keycode)
        if direction is None:
            return event

        now = time.monotonic()
        rel_t = round(now - self._base_time, 3)

        with self._lock:
            if event_type == kCGEventKeyDown and direction not in self._held:
                self._held[direction] = now
                self._events.append({
                    "t": rel_t, "key": direction, "event": "down",
                })
            elif event_type == kCGEventKeyUp and direction in self._held:
                start = self._held.pop(direction)
                dur = round(now - start, 3)
                self._events.append({
                    "t": rel_t, "key": direction,
                    "event": "up", "duration": dur,
                })
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
            log.error(
                "Could not create event tap. "
                "Grant Accessibility permission to Terminal/iTerm in "
                "System Settings > Privacy & Security > Accessibility"
            )
            return

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        self._run_loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._run_loop, source, kCFRunLoopCommonModes)
        CFRunLoopRun()


class DemoRecorder:
    """Records TTR screen frames and keyboard events simultaneously."""

    def __init__(self) -> None:
        self._recording = False
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._key_logger: _KeyEventLogger | None = None
        self._demo_dir: str = ""
        self._frame_count = 0
        self._base_time = 0.0
        self._frame_timestamps: list[float] = []

        self.on_status: Callable[[str], None] | None = None

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def duration(self) -> float:
        if not self._recording:
            return 0.0
        return time.monotonic() - self._base_time

    def start(self) -> str:
        """Start recording. Returns the demo directory path."""
        if self._recording:
            return self._demo_dir

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._demo_dir = os.path.join(settings.DEMO_SAVE_DIR, f"demo_{ts}")
        frames_dir = os.path.join(self._demo_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        self._frame_count = 0
        self._frame_timestamps = []
        self._stop_event.clear()
        self._base_time = time.monotonic()

        self._key_logger = _KeyEventLogger(self._base_time)
        self._key_logger.start()

        self._recording = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True,
        )
        self._capture_thread.start()

        self._notify(f"Recording started → {self._demo_dir}")
        return self._demo_dir

    def stop(self) -> dict:
        """Stop recording and save metadata. Returns a summary dict."""
        if not self._recording:
            return {}

        self._stop_event.set()
        self._recording = False

        if self._capture_thread:
            self._capture_thread.join(timeout=5)
        if self._key_logger:
            self._key_logger.stop()

        summary = self._save_metadata()
        self._notify(self._format_summary(summary))
        return summary

    def _capture_loop(self) -> None:
        interval = settings.DEMO_FRAME_INTERVAL_MS / 1000.0
        frames_dir = os.path.join(self._demo_dir, "frames")

        while not self._stop_event.is_set():
            t_start = time.monotonic()

            win = find_ttr_window()
            if win is not None:
                frame = capture_window(win)
                if frame is not None:
                    h, w = frame.shape[:2]
                    half = cv2.resize(frame, (w // 2, h // 2),
                                      interpolation=cv2.INTER_AREA)

                    rel_t = round(t_start - self._base_time, 3)
                    fname = f"{self._frame_count:05d}.jpg"
                    path = os.path.join(frames_dir, fname)

                    cv2.imwrite(path, half, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    self._frame_timestamps.append(rel_t)
                    self._frame_count += 1

            elapsed = time.monotonic() - t_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                self._stop_event.wait(sleep_time)

    def _save_metadata(self) -> dict:
        duration = round(time.monotonic() - self._base_time, 1)
        key_events = self._key_logger.get_events() if self._key_logger else []
        key_press_count = sum(1 for e in key_events if e["event"] == "down")

        keyboard_path = os.path.join(self._demo_dir, "keyboard.jsonl")
        with open(keyboard_path, "w") as f:
            for ev in key_events:
                f.write(json.dumps(ev) + "\n")

        timestamps_path = os.path.join(self._demo_dir, "frame_timestamps.json")
        with open(timestamps_path, "w") as f:
            json.dump(self._frame_timestamps, f)

        total_bytes = 0
        frames_dir = os.path.join(self._demo_dir, "frames")
        for fname in os.listdir(frames_dir):
            total_bytes += os.path.getsize(os.path.join(frames_dir, fname))

        meta = {
            "start_time": datetime.now().isoformat(),
            "duration_s": duration,
            "frame_count": self._frame_count,
            "avg_fps": round(self._frame_count / max(duration, 0.1), 1),
            "keyboard_events": len(key_events),
            "keyboard_presses": key_press_count,
            "total_frame_bytes": total_bytes,
        }

        meta_path = os.path.join(self._demo_dir, "meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        return meta

    def _format_summary(self, meta: dict) -> str:
        size_mb = meta.get("total_frame_bytes", 0) / (1024 * 1024)
        return (
            f"{'═' * 42}\n"
            f" RECORDING SUMMARY\n"
            f"{'═' * 42}\n"
            f" Duration:         {meta['duration_s']:.1f} seconds\n"
            f" Frames captured:  {meta['frame_count']} "
            f"({meta['avg_fps']} FPS average)\n"
            f" Keyboard events:  {meta['keyboard_events']} "
            f"({meta['keyboard_presses']} key presses)\n"
            f" Total size:       {size_mb:.1f} MB\n"
            f" Saved to:         {self._demo_dir}\n"
            f"{'═' * 42}"
        )

    def _notify(self, msg: str) -> None:
        log.info(msg)
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass
