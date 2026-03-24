"""Execute gardening routines: walk between flower beds and plant at each.

Supports two modes:
1. Legacy: timing-based walk segments from a JSON file
2. Smart: SIFT-localization + demo-replay navigation via a garden map

The actual planting logic (pick existing flower, plant new one, water)
is handled by GardenBot._plant_flower().
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass
from typing import Callable

import pyautogui

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.gardening.flowers import lookup_flower
from ttr_bot.gardening.gardening_bot import GardenBot
from ttr_bot.utils.logger import log


@dataclass
class RoutineProgress:
    current_bed: int = 0
    total_beds: int = 0
    flowers_planted: int = 0
    status: str = ""
    nav_method: str = ""
    stuck_recoveries: int = 0


@dataclass
class RoutineSummary:
    beds_completed: int = 0
    total_beds: int = 0
    via_demo_only: int = 0
    via_demo_correction: int = 0
    via_sift_only: int = 0
    beds_skipped: int = 0
    stuck_recoveries: int = 0
    nav_time_s: float = 0.0
    total_time_s: float = 0.0


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

    def start_smart(self, map_path: str, default_flower: str = "",
                    route: list[int] | None = None, repeat: int = 1) -> None:
        """Run a smart routine using the garden map + navigator."""
        if self._running:
            log.warning("Routine already running")
            return

        from ttr_bot.vision.localizer import GardenMap, GardenLocalizer

        if not os.path.isfile(map_path):
            if self.on_routine_ended:
                self.on_routine_ended(f"Map not found: {map_path}")
            return

        garden_map = GardenMap.load(map_path)
        localizer = GardenLocalizer(garden_map)

        if route is None:
            route = garden_map.route_order
        if not route:
            if self.on_routine_ended:
                self.on_routine_ended("No route defined in map")
            return

        self._default_flower = default_flower
        self._stop_event.clear()
        self._bot.reset()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_smart,
            args=(garden_map, localizer, route, repeat),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._bot.stop()
        self._running = False

    # ------------------------------------------------------------------
    # Internal: Smart navigation
    # ------------------------------------------------------------------

    def _run_smart(self, garden_map, localizer, route: list[int],
                   repeat: int = 1) -> None:
        """Execute garden routine using SIFT-based navigation."""
        from ttr_bot.gardening.navigator import GardenNavigator

        try:
            flower, beans = self._validate_flower()
            if flower is None:
                return

            if not self._bot._ensure_calibrated():
                self._finish("Calibration failed")
                return

            self._lock_camera(garden_map.camera_tab_count)

            navigator = GardenNavigator(garden_map, localizer, self._stop_event)
            navigator.on_log = lambda msg: self._notify_status(msg)

            summary = RoutineSummary(total_beds=len(route))
            t0 = time.monotonic()

            for cycle in range(repeat):
                if self._stop_event.is_set():
                    break
                cycle_label = f"[Cycle {cycle + 1}/{repeat}] " if repeat > 1 else ""
                self._smart_cycle(navigator, route, cycle, cycle_label,
                                  flower, beans, summary)

            summary.total_time_s = time.monotonic() - t0
            self._print_summary(summary)
            reason = "User stopped" if self._stop_event.is_set() else "Routine complete"
            self._finish(reason)

        except Exception as exc:
            log.exception("Smart routine crashed")
            self._finish(f"Error: {exc}")

    def _validate_flower(self) -> tuple[str | None, str | None]:
        """Validate flower selection. Returns (flower, beans) or (None, None)."""
        flower = self._default_flower
        if not flower:
            self._finish("No flower selected — pick one in the UI")
            return (None, None)
        info = lookup_flower(flower)
        if info is None:
            self._finish(f"Unknown flower: {flower}")
            return (None, None)
        return (flower, info[1])

    def _smart_cycle(self, navigator, route: list[int], cycle: int,
                     cycle_label: str, flower: str, beans: str,
                     summary: RoutineSummary) -> None:
        """Execute one cycle of the smart routine."""
        total = len(route)

        for i, bed_num in enumerate(route):
            if self._stop_event.is_set():
                return

            bed_id = f"bed_{bed_num}"
            progress = RoutineProgress(
                current_bed=bed_num, total_beds=total,
                flowers_planted=summary.beds_completed,
                status=f"{cycle_label}Bed {bed_num}/{total}",
            )
            self._notify_progress(progress)

            if not self._smart_navigate_to(navigator, bed_id, bed_num,
                                           i, cycle, cycle_label, summary):
                continue

            if self._stop_event.is_set():
                return

            self._notify_status(f"{cycle_label}Planting at bed {bed_num}…")
            ok = self._bot._plant_flower(flower, beans)
            if ok:
                summary.beds_completed += 1
            else:
                self._finish(f"Plant failed at bed {bed_num} — aborting")
                return

    def _smart_navigate_to(self, navigator, bed_id: str, bed_num: int,
                           index: int, cycle: int, cycle_label: str,
                           summary: RoutineSummary) -> bool:
        """Navigate to a bed, return True if arrived (or first bed)."""
        if index == 0 and cycle == 0:
            navigator.current_bed = bed_id
            self._notify_status(f"{cycle_label}Starting at bed {bed_num}")
            return True

        nav_t0 = time.monotonic()
        self._notify_status(f"{cycle_label}Navigating to bed {bed_num}…")
        nav_result = navigator.navigate_to_bed(bed_id)
        summary.nav_time_s += time.monotonic() - nav_t0
        summary.stuck_recoveries += nav_result.stuck_recoveries

        if not nav_result.arrived:
            summary.beds_skipped += 1
            self._notify_status(f"Skipped bed {bed_num} (navigation failed)")
            return False

        self._categorize_nav(nav_result, summary)
        return True

    @staticmethod
    def _categorize_nav(nav_result, summary: RoutineSummary) -> None:
        if nav_result.method == "demo_replay":
            summary.via_demo_only += 1
        elif nav_result.method == "demo+correction":
            summary.via_demo_correction += 1
        elif nav_result.method == "sift_correction":
            summary.via_sift_only += 1

    def _lock_camera(self, tab_count: int) -> None:
        """Press Tab N times to set the camera to zoomed-out chase view."""
        inp.ensure_focused()
        time.sleep(0.2)
        for _ in range(tab_count):
            pyautogui.press("tab")
            time.sleep(0.3)
        self._notify_status(f"Camera locked ({tab_count} Tab presses)")

    def _print_summary(self, s: RoutineSummary) -> None:
        msg = (
            f"\n{'═' * 42}\n"
            f" ROUTINE COMPLETE\n"
            f"{'═' * 42}\n"
            f" Beds completed: {s.beds_completed}/{s.total_beds}\n"
            f" Via demo replay only: {s.via_demo_only}/{s.total_beds}\n"
            f" Via demo + SIFT correction: {s.via_demo_correction}/{s.total_beds}\n"
            f" Via SIFT-only: {s.via_sift_only}/{s.total_beds}\n"
            f" Beds skipped: {s.beds_skipped}\n"
            f" Stuck recoveries: {s.stuck_recoveries}\n"
            f" Total navigation time: {s.nav_time_s:.0f}s\n"
            f" Total routine time: {int(s.total_time_s) // 60}m "
            f"{int(s.total_time_s) % 60:02d}s\n"
            f"{'═' * 42}"
        )
        log.info(msg)
        self._notify_status(msg)

    # ------------------------------------------------------------------
    # Internal: Legacy walk-based navigation
    # ------------------------------------------------------------------

    def _run(self, beds: list[list[dict]], repeat: int = 1) -> None:
        try:
            flower, beans = self._validate_flower()
            if flower is None:
                return

            if not self._bot._ensure_calibrated():
                self._finish("Calibration failed")
                return

            total = len(beds)
            progress = RoutineProgress(total_beds=total)

            for cycle in range(repeat):
                if self._stop_event.is_set():
                    break
                cycle_label = f"[Cycle {cycle + 1}/{repeat}] " if repeat > 1 else ""
                self._legacy_cycle(beds, flower, beans, cycle_label, progress)
                if repeat > 1 and cycle < repeat - 1 and not self._stop_event.is_set():
                    self._notify_status(f"Cycle {cycle + 1}/{repeat} done")
                    time.sleep(1.0)

            reason = "User stopped" if self._stop_event.is_set() else "Routine complete"
            self._finish(reason)

        except Exception as exc:
            log.exception("Routine crashed")
            self._finish(f"Error: {exc}")

    def _legacy_cycle(self, beds: list[list[dict]], flower: str, beans: str,
                      cycle_label: str, progress: RoutineProgress) -> None:
        """Execute one cycle of the legacy timing-based routine."""
        total = len(beds)
        for bed_idx, walk_segments in enumerate(beds):
            if self._stop_event.is_set():
                return

            bed_num = bed_idx + 1
            progress.current_bed = bed_num
            progress.status = f"{cycle_label}Bed {bed_num}/{total}"

            if not self._legacy_walk_to_bed(walk_segments, bed_num, cycle_label, progress):
                return

            self._notify_status(f"{cycle_label}Planting at bed {bed_num}…")
            self._notify_progress(progress)
            ok = self._bot._plant_flower(flower, beans)
            if ok:
                progress.flowers_planted += 1
            else:
                self._finish(f"Plant failed at bed {bed_num} — aborting")
                return

    def _legacy_walk_to_bed(self, walk_segments: list[dict], bed_num: int,
                            cycle_label: str, progress: RoutineProgress) -> bool:
        """Walk to a bed using timing. Returns False if stopped."""
        if not walk_segments:
            return not self._stop_event.is_set()
        self._notify_status(f"{cycle_label}Walking to bed {bed_num}…")
        self._notify_progress(progress)
        self._do_walks(walk_segments)
        if self._stop_event.is_set():
            return False
        self._interruptible_sleep(0.5)
        return not self._stop_event.is_set()

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
