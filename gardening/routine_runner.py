"""Execute gardening routines: walk between flower beds and plant at each.

Routines are JSON files stored in gardening_routines/.  They only describe
the navigation between beds — the actual planting logic (pick existing flower,
plant new one, water) is handled by GardenBot._plant_flower().

Format:
    {
        "repeat": 1,
        "beds": [
            [],
            [{"direction": "left", "duration": 0.8}],
            [{"direction": "left", "duration": 0.6}, {"direction": "up", "duration": 0.3}]
        ]
    }

Each entry in "beds" is a list of walk segments to reach that bed from the
previous one.  The first entry is typically empty (you start at bed 1).
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass
from typing import Callable

from config import settings
from core import input_controller as inp
from gardening.flowers import lookup_flower
from gardening.gardening_bot import GardenBot
from utils.logger import log


@dataclass
class RoutineProgress:
    current_bed: int = 0
    total_beds: int = 0
    flowers_planted: int = 0
    status: str = ""


class RoutineRunner:
    """Loads and executes gardening routines from JSON files."""

    def __init__(self, garden_bot: GardenBot) -> None:
        self._bot = garden_bot
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._default_flower: str = ""

        self.on_progress: Callable[[RoutineProgress], None] | None = None
        self.on_status_update: Callable[[str], None] | None = None
        self.on_routine_ended: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, routine_path: str, default_flower: str = "") -> None:
        """Load a routine JSON and run it in a background thread."""
        if self._running:
            log.warning("Routine already running")
            return

        try:
            with open(routine_path, "r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Failed to load routine %s: %s", routine_path, exc)
            if self.on_routine_ended:
                self.on_routine_ended(f"Load error: {exc}")
            return

        if isinstance(data, dict):
            beds = data.get("beds", [])
            repeat = max(1, int(data.get("repeat", 1)))
        elif isinstance(data, list):
            beds = data
            repeat = 1
        else:
            if self.on_routine_ended:
                self.on_routine_ended("Invalid routine format")
            return

        if not beds:
            if self.on_routine_ended:
                self.on_routine_ended("No beds in routine")
            return

        self._default_flower = default_flower
        self._stop_event.clear()
        self._bot.reset()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, args=(beds, repeat), daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._bot.stop()
        self._running = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, beds: list[list[dict]], repeat: int = 1) -> None:
        try:
            total = len(beds)
            progress = RoutineProgress(total_beds=total)

            if not self._bot._ensure_calibrated():
                self._finish("Calibration failed")
                return

            flower = self._default_flower
            if not flower:
                self._finish("No flower selected — pick one in the UI")
                return

            info = lookup_flower(flower)
            if info is None:
                self._finish(f"Unknown flower: {flower}")
                return
            beans = info[1]

            for cycle in range(repeat):
                if self._stop_event.is_set():
                    break

                cycle_label = f"[Cycle {cycle + 1}/{repeat}] " if repeat > 1 else ""

                for bed_idx, walk_segments in enumerate(beds):
                    if self._stop_event.is_set():
                        break

                    bed_num = bed_idx + 1
                    progress.current_bed = bed_num
                    progress.status = f"{cycle_label}Bed {bed_num}/{total}"

                    # Walk to this bed
                    if walk_segments:
                        self._notify_status(f"{cycle_label}Walking to bed {bed_num}…")
                        self._notify_progress(progress)
                        self._do_walks(walk_segments)
                        if self._stop_event.is_set():
                            break
                        self._interruptible_sleep(0.5)
                        if self._stop_event.is_set():
                            break

                    # Plant at this bed (handles pick → plant → water)
                    if self._stop_event.is_set():
                        break
                    self._notify_status(f"{cycle_label}Planting at bed {bed_num}…")
                    self._notify_progress(progress)
                    ok = self._bot._plant_flower(flower, beans)
                    if ok:
                        progress.flowers_planted += 1
                    else:
                        self._finish(f"Plant failed at bed {bed_num} — aborting")
                        return

                if repeat > 1 and cycle < repeat - 1 and not self._stop_event.is_set():
                    self._notify_status(f"Cycle {cycle + 1}/{repeat} done")
                    time.sleep(1.0)

            reason = "User stopped" if self._stop_event.is_set() else "Routine complete"
            self._finish(reason)

        except Exception as exc:
            log.exception("Routine crashed")
            self._finish(f"Error: {exc}")

    def _interruptible_sleep(self, duration: float) -> None:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and not self._stop_event.is_set():
            time.sleep(min(0.25, deadline - time.monotonic()))

    def _do_walks(self, segments: list[dict]) -> None:
        _VALID = {"up", "down", "left", "right"}
        inp.ensure_focused()
        time.sleep(0.05)
        for seg in segments:
            if self._stop_event.is_set():
                return
            direction = seg.get("direction", "up").lower()
            if direction not in _VALID:
                continue
            duration = max(0.01, float(seg.get("duration", 0.5)))
            import pyautogui
            pyautogui.keyDown(direction)
            try:
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    if self._stop_event.is_set():
                        return
                    time.sleep(min(0.1, deadline - time.monotonic()))
            finally:
                pyautogui.keyUp(direction)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_progress(self, progress: RoutineProgress) -> None:
        if self.on_progress:
            try:
                self.on_progress(progress)
            except Exception:
                pass

    def _notify_status(self, msg: str) -> None:
        log.info(msg)
        if self.on_status_update:
            try:
                self.on_status_update(msg)
            except Exception:
                pass

    def _finish(self, reason: str) -> None:
        self._running = False
        log.info("Routine ended: %s", reason)
        if self.on_routine_ended:
            try:
                self.on_routine_ended(reason)
            except Exception:
                pass


# ------------------------------------------------------------------
# Utility: list available routines
# ------------------------------------------------------------------

def list_routines() -> list[dict[str, str]]:
    """Return a list of {name, path} dicts for saved routine files."""
    routines_dir = settings.GARDENING_ROUTINES_DIR
    if not os.path.isdir(routines_dir):
        return []

    results = []
    for fname in sorted(os.listdir(routines_dir)):
        if fname.endswith(".json"):
            results.append({
                "name": fname.removesuffix(".json"),
                "path": os.path.join(routines_dir, fname),
            })
    return results
