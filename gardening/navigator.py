"""Two-stage garden navigator: demo replay warm-start + SIFT correction.

Stage 1: Replay the recorded keyboard segment for the bed transition.
          SIFT localizer monitors in parallel and checks for arrival.
Stage 2: If Stage 1 drifts or doesn't arrive, SIFT-guided correction
          uses short key bursts to steer toward the target.

Stuck detection and recovery is also handled here.
"""

from __future__ import annotations

import math
import time
import threading
from typing import Callable

import cv2
import numpy as np
import pyautogui

from config import settings
from core.window_manager import find_ttr_window
from core.screen_capture import capture_window
from core import input_controller as inp
from vision import template_matcher as tm
from vision.localizer import (
    GardenMap, GardenLocalizer, HeadingEstimator,
    LocalizationResult, MapNode,
)
from utils.logger import log


_ARROW_KEYS = {"up", "down", "left", "right"}


class _StallTracker:
    """Detects when the character is stuck based on localization positions."""

    def __init__(self) -> None:
        self._last_pos: tuple[float, float] | None = None
        self._stall_start: float | None = None

    def update(self, x: float, y: float) -> bool:
        """Update with new position. Returns True if stuck."""
        if self._last_pos is not None:
            dx = x - self._last_pos[0]
            dy = y - self._last_pos[1]
            if (dx * dx + dy * dy) < 4.0:
                if self._stall_start is None:
                    self._stall_start = time.monotonic()
                elif time.monotonic() - self._stall_start > settings.NAV_STUCK_TIMEOUT_S:
                    self._stall_start = None
                    self._last_pos = (x, y)
                    return True
            else:
                self._stall_start = None

        self._last_pos = (x, y)
        return False


class NavigationResult:
    """Result of navigating to a single bed."""

    def __init__(self) -> None:
        self.arrived = False
        self.method = ""
        self.duration_s = 0.0
        self.stuck_recoveries = 0
        self.skipped = False


class GardenNavigator:
    """Navigates between garden beds using demo replay + SIFT correction."""

    def __init__(
        self,
        garden_map: GardenMap,
        localizer: GardenLocalizer,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._map = garden_map
        self._localizer = localizer
        self._heading = HeadingEstimator()
        self._stop_event = stop_event or threading.Event()
        self._current_bed: str | None = None
        self._prev_frame: np.ndarray | None = None

        self.on_log: Callable[[str], None] | None = None

    @property
    def current_bed(self) -> str | None:
        return self._current_bed

    @current_bed.setter
    def current_bed(self, value: str | None) -> None:
        self._current_bed = value

    def navigate_to_bed(self, target_bed_id: str) -> NavigationResult:
        """Navigate from current position to the target bed.

        Returns a NavigationResult indicating success/failure and method used.
        """
        result = NavigationResult()
        t0 = time.monotonic()

        target_node = self._map.get_bed(target_bed_id)
        if target_node is None:
            self._log(f"Unknown target bed: {target_bed_id}")
            result.skipped = True
            return result

        self._log(f"NAVIGATION: {self._current_bed or '?'} → {target_bed_id}")
        self._heading.reset()

        # Stage 1: Demo replay
        stage1_ok = self._stage1_demo_replay(target_bed_id, result)
        if self._stop_event.is_set():
            result.duration_s = time.monotonic() - t0
            return result

        if stage1_ok:
            result.arrived = True
            result.method = "demo_replay"
            result.duration_s = time.monotonic() - t0
            self._current_bed = target_bed_id
            self._log(f"ARRIVED via demo replay ({result.duration_s:.1f}s)")
            return result

        # Stage 2: SIFT-guided correction
        self._log("STAGE 2: SIFT correction")
        stage2_ok = self._stage2_sift_correction(target_node, result)
        result.duration_s = time.monotonic() - t0

        if stage2_ok:
            result.arrived = True
            if result.method:
                result.method = "demo+correction"
            else:
                result.method = "sift_correction"
            self._current_bed = target_bed_id
            self._log(f"ARRIVED via {result.method} ({result.duration_s:.1f}s)")
        else:
            self._log(f"FAILED to reach {target_bed_id} ({result.duration_s:.1f}s)")

        return result

    # ------------------------------------------------------------------
    # Stage 1: Demo replay
    # ------------------------------------------------------------------

    def _stage1_demo_replay(self, target_bed_id: str, result: NavigationResult) -> bool:
        """Replay recorded key sequence, localizing in parallel."""
        segment = self._load_segment(target_bed_id)
        if segment is None:
            return False

        events = segment.get("events", [])
        self._log(f"STAGE 1: Demo replay ({len(events)} events, "
                  f"{segment.get('duration', 0):.1f}s)")

        inp.ensure_focused()
        time.sleep(0.05)

        replay_result = self._execute_replay(events, target_bed_id)
        self._release_all_keys()

        if replay_result == "arrived":
            return True
        if replay_result == "drift":
            result.method = "demo"
            return False

        if self._check_arrival():
            return True

        self._log("Demo replay finished but not at target")
        result.method = "demo"
        return False

    def _load_segment(self, target_bed_id: str) -> dict | None:
        """Load the demo segment, returning None with a log if unavailable."""
        if self._current_bed is None:
            self._log("No current bed set — skipping demo replay")
            return None
        segment = self._map.get_demo_segment(self._current_bed, target_bed_id)
        if segment is None:
            self._log("No demo segment available — skipping to Stage 2")
            return None
        if not segment.get("events"):
            self._log("Empty demo segment — skipping to Stage 2")
            return None
        return segment

    def _execute_replay(
        self, events: list[dict], target_bed_id: str,
    ) -> str:
        """Replay key events. Returns 'arrived', 'drift', 'stopped', or 'done'."""
        base_time = time.monotonic()
        first_t = events[0].get("t", 0)
        last_localize = 0.0

        for event in events:
            if self._stop_event.is_set():
                return "stopped"

            status = self._replay_single_event(event, base_time, first_t)
            if status == "stopped":
                return "stopped"
            if status == "skip":
                continue

            now = time.monotonic()
            if now - last_localize < settings.NAV_RECHECK_INTERVAL_MS / 1000.0:
                continue
            last_localize = now

            check = self._replay_localize_check(target_bed_id)
            if check in ("arrived", "drift"):
                return check

        return "done"

    def _replay_single_event(
        self, event: dict, base_time: float, first_t: float,
    ) -> str | None:
        """Process one replay event. Returns 'stopped', 'skip', or None."""
        key = event.get("key", "")
        if key not in _ARROW_KEYS:
            return "skip"

        wait = (base_time + event.get("t", 0) - first_t) - time.monotonic()
        if wait > 0 and not self._interruptible_sleep(wait):
            return "stopped"

        if event.get("event") == "down":
            pyautogui.keyDown(key)
        elif event.get("event") == "up":
            pyautogui.keyUp(key)
        return None

    def _replay_localize_check(self, target_bed_id: str) -> str | None:
        """Localize during replay. Returns 'arrived', 'drift', or None."""
        loc = self._quick_localize()
        if loc is None:
            return None
        self._heading.update(loc)
        if self._is_near_target(loc, target_bed_id):
            self._release_all_keys()
            if self._check_arrival():
                return "arrived"
        if loc.confidence < settings.NAV_REPLAY_DRIFT_THRESHOLD:
            self._log(f"Drift detected (conf={loc.confidence:.2f}) — switching to Stage 2")
            self._release_all_keys()
            return "drift"
        return None

    # ------------------------------------------------------------------
    # Stage 2: SIFT-guided correction
    # ------------------------------------------------------------------

    def _stage2_sift_correction(
        self, target_node: MapNode, result: NavigationResult,
    ) -> bool:
        """Use SIFT localization to steer toward the target bed."""
        deadline = time.monotonic() + settings.NAV_MAX_WALK_TIME_PER_BED
        tracker = _StallTracker()

        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                self._release_all_keys()
                return False

            if self._check_arrival():
                return True

            loc = self._quick_localize()
            if loc is None:
                time.sleep(0.2)
                continue

            self._heading.update(loc)

            stuck = tracker.update(loc.map_x, loc.map_y)
            if stuck:
                result.stuck_recoveries += 1
                if result.stuck_recoveries > settings.NAV_MAX_RECOVERY_ATTEMPTS:
                    self._log("Max recovery attempts — giving up")
                    return False
                self._log(f"STUCK (attempt {result.stuck_recoveries}) — recovering")
                self._stuck_recovery()
                continue

            self._steer_toward(target_node, loc)
            time.sleep(settings.NAV_RECHECK_INTERVAL_MS / 1000.0)

        return False

    def _steer_toward(self, target: MapNode, loc: LocalizationResult) -> None:
        """Calculate direction and execute a key burst toward the target."""
        target_angle = math.degrees(
            math.atan2(target.map_y - loc.map_y, target.map_x - loc.map_x)
        )
        keys = self._angle_to_keys(target_angle)
        self._log(f"  Pos: ({loc.map_x:.0f},{loc.map_y:.0f}) | "
                  f"Heading: {self._heading.heading or 0:.0f}° | "
                  f"Target: {target_angle:.0f}° | Keys: {'+'.join(keys)}")
        self._key_burst(keys, settings.NAV_KEY_BURST_MS / 1000.0)

    # ------------------------------------------------------------------
    # Stuck recovery
    # ------------------------------------------------------------------

    def _stuck_recovery(self) -> None:
        """Attempt to unstick: backup, perpendicular nudge, re-check."""
        self._log("  Recovery: backing up...")
        self._key_burst(["down"], 0.5)
        time.sleep(0.3)

        self._log("  Recovery: perpendicular nudge...")
        self._key_burst(["left"], 0.4)
        time.sleep(0.3)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _quick_localize(self) -> LocalizationResult | None:
        win = find_ttr_window()
        if win is None:
            return None
        frame = capture_window(win)
        if frame is None:
            return None
        self._prev_frame = frame
        return self._localizer.localize(frame)

    def _check_arrival(self) -> bool:
        """Check if interaction buttons are visible (definitive arrival)."""
        win = find_ttr_window()
        if win is None:
            return False
        frame = capture_window(win)
        if frame is None:
            return False
        for btn in ("plant_flower_button", "pick_flower_button"):
            if tm.find_template(frame, btn) is not None:
                return True
        return False

    def _is_near_target(self, loc: LocalizationResult, target_id: str) -> bool:
        """Check if localization suggests we're close to the target."""
        if loc.best_node_id == target_id:
            return loc.confidence >= settings.NAV_REPLAY_CLOSE_RANGE
        target = self._map.get_bed(target_id)
        if target is None:
            return False
        dx = loc.map_x - target.map_x
        dy = loc.map_y - target.map_y
        dist = (dx * dx + dy * dy) ** 0.5
        return dist < 30 and loc.confidence >= 0.4

    def _angle_to_keys(self, angle_deg: float) -> list[str]:
        """Convert a map angle to arrow key(s), accounting for heading.

        Map coordinates: 0° = right, 90° = down.
        TTR arrow keys relative to character/camera heading.
        """
        heading = self._heading.heading
        if heading is not None:
            relative = angle_deg - heading
        else:
            relative = angle_deg

        relative = relative % 360

        keys: list[str] = []
        if 315 <= relative or relative < 45:
            keys.append("up")
        elif 45 <= relative < 135:
            keys.append("right")
        elif 135 <= relative < 225:
            keys.append("down")
        else:
            keys.append("left")

        offset = relative % 90
        if 20 < offset < 70:
            if 0 <= relative < 90:
                keys.append("right")
            elif 90 <= relative < 180:
                keys.append("down")
            elif 180 <= relative < 270:
                keys.append("left")
            else:
                keys.append("up")

        return keys

    def _key_burst(self, keys: list[str], duration: float) -> None:
        """Press multiple keys simultaneously for a short burst."""
        inp.ensure_focused()
        for k in keys:
            pyautogui.keyDown(k)
        try:
            self._interruptible_sleep(duration)
        finally:
            for k in keys:
                pyautogui.keyUp(k)

    def _release_all_keys(self) -> None:
        for k in _ARROW_KEYS:
            try:
                pyautogui.keyUp(k)
            except Exception:
                pass

    def _interruptible_sleep(self, duration: float) -> bool:
        """Sleep for duration, checking stop event. Returns False if interrupted."""
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            time.sleep(min(0.05, deadline - time.monotonic()))
        return True

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Frame differencing for stuck detection (supplementary)
    # ------------------------------------------------------------------

    def is_frame_stuck(self, current: np.ndarray) -> bool:
        """Check if the frame has barely changed (collision/stuck)."""
        if self._prev_frame is None:
            self._prev_frame = current
            return False

        prev_gray = cv2.cvtColor(self._prev_frame, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, curr_gray)
        diff_sum = int(np.sum(diff))
        self._prev_frame = current
        return diff_sum < settings.NAV_STUCK_THRESHOLD
