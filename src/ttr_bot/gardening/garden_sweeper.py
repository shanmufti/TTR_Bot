"""Garden Sweeper: visual-guided flower-bed navigation.

TTR movement model (fixed camera behind character):
- **Up** = walk forward (direction character faces)
- **Left / Right** = turn in place (pure rotation, no forward movement)
- **Down** = walk backward

Navigation approach:

1.  Scan the screen for visible flowers (red-near-green colour blobs).
2.  Steer toward them: if flowers are to the left, turn left; right → right.
3.  Walk forward and poll for gardening UI buttons (Pick / Plant / Water).
4.  When buttons appear → interact with the bed.
5.  After interacting, walk away and scan again.
6.  If no flowers are visible, rotate slowly until some come into view.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import pyautogui

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.gardening.bed_ui import BED_BUTTON_NAMES, classify_bed_state, detect_bed_button
from ttr_bot.gardening.gardening_bot import GardenBot
from ttr_bot.utils.logger import log
from ttr_bot.vision import template_matcher as tm
from ttr_bot.vision.flower_detector import debug_annotate, steering_hint

_DEBUG_DIR = os.path.join(settings.DATA_DIR, "_debug", "sweep")

_ARROW_KEYS = ("up", "down", "left", "right")


@dataclass
class SweepResult:
    """Summary returned after one full garden sweep pass."""

    beds_visited: int = 0
    beds_planted: int = 0
    beds_watered: int = 0
    beds_picked: int = 0
    total_time_s: float = 0.0
    reason: str = ""


class GardenSweeper:
    """Walk-and-scan garden automation using flower vision."""

    def __init__(
        self,
        garden_bot: GardenBot,
        stop_event: threading.Event,
    ) -> None:
        self._bot = garden_bot
        self._stop_event = stop_event
        self.on_status: Callable[[str], None] | None = None
        self._debug_seq = 0
        os.makedirs(_DEBUG_DIR, exist_ok=True)

    def _debug_save(self, frame, label: str) -> None:
        self._debug_seq += 1
        path = os.path.join(_DEBUG_DIR, f"{self._debug_seq:03d}_{label}.png")
        cv2.imwrite(path, frame)
        log.info("[DEBUG] saved %s", path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sweep(
        self,
        flower_name: str,
        bean_sequence: str,
        target_beds: int = 0,
        max_laps: int = 0,
    ) -> SweepResult:
        if target_beds <= 0:
            target_beds = settings.SWEEP_TARGET_BEDS
        if max_laps <= 0:
            max_laps = settings.SWEEP_MAX_LAPS
        result = SweepResult()
        t0 = time.monotonic()

        self._debug_seq = 0
        for f in os.listdir(_DEBUG_DIR):
            if f.endswith(".png"):
                os.remove(os.path.join(_DEBUG_DIR, f))
        self._status(f"Starting sweep — {flower_name}, target {target_beds} beds")

        if not self._bot.ensure_calibrated():
            result.reason = "Calibration failed"
            return result

        try:
            self._discover(max_laps, flower_name, bean_sequence, result, target_beds)
        finally:
            self._release_all_keys()

        result.total_time_s = time.monotonic() - t0
        result.reason = (
            "User stopped" if self._stop_event.is_set() else f"Done — {result.beds_visited} beds"
        )
        self._print_summary(result)
        return result

    # ------------------------------------------------------------------
    # Visual discovery loop
    # ------------------------------------------------------------------

    def _discover(
        self,
        max_laps: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
        target_beds: int,
    ) -> None:
        bed_btn = self._detect_bed()
        if bed_btn is not None:
            self._status("Already at a bed — interacting")
            self._interact_at_bed(flower_name, bean_sequence, result)
            self._walk_away()

        self._status("Visual scan-and-navigate")

        max_iterations = max_laps * 50
        idle_count = 0
        last_beds = result.beds_visited
        for _ in range(max_iterations):
            if self._should_stop(result, target_beds):
                break

            if result.beds_visited > last_beds:
                idle_count = 0
                last_beds = result.beds_visited

            frame = self._grab_frame()
            if frame is None:
                break

            direction, magnitude = steering_hint(frame)
            self._debug_save(debug_annotate(frame, direction, magnitude), f"steer_{direction}")

            if direction == "none":
                idle_count += 1
                if idle_count >= 10:
                    self._recover_from_stuck()
                    idle_count = 0
                    continue
                if idle_count <= 4:
                    self._status(f"No flowers — walking forward to search ({idle_count})")
                    outcome = self._walk_and_scan(["up"], settings.SWEEP_WALK_BURST_S)
                    if outcome == "bed_found":
                        self._interact_at_bed(flower_name, bean_sequence, result)
                        self._walk_away()
                else:
                    self._status("No flowers — rotating to scan")
                    self._key_burst(["right"], settings.SWEEP_SCAN_ROTATE_S)
                continue

            idle_count = 0

            if direction in ("left", "right"):
                turn_dur = settings.SWEEP_TURN_BURST_S * magnitude
                self._status(f"Flowers {direction} ({magnitude:.2f}) — turning {turn_dur:.2f}s")
                self._key_burst([direction], turn_dur)

            self._status(f"Walking toward flowers (visited {result.beds_visited}/{target_beds})")
            outcome = self._walk_and_scan(["up"], settings.SWEEP_WALK_BURST_S)
            if outcome == "bed_found":
                self._interact_at_bed(flower_name, bean_sequence, result)
                self._walk_away()

    # ------------------------------------------------------------------
    # Walk-and-scan
    # ------------------------------------------------------------------

    def _grab_frame(self):
        win = find_ttr_window()
        if win is None:
            return None
        return capture_window(win)

    def _walk_and_scan(
        self,
        keys: list[str],
        leg_duration: float,
    ) -> str:
        """Walk for *leg_duration*, polling for beds.

        Returns ``"bed_found"``, ``"leg_complete"``, or ``"stopped"``.
        """
        check_interval = settings.SWEEP_CHECK_INTERVAL_S
        elapsed = 0.0

        while elapsed < leg_duration:
            if self._stop_event.is_set():
                return "stopped"

            burst = min(check_interval, leg_duration - elapsed)
            self._key_burst(keys, burst)
            elapsed += burst

            bed_btn = self._detect_bed()
            if bed_btn is not None:
                detect_frame = self._grab_frame()
                if detect_frame is not None:
                    self._debug_save(detect_frame, f"bed_detect_{bed_btn}")
                time.sleep(0.3)
                bed_btn = self._detect_bed()
                if bed_btn is not None:
                    self._status(f"Bed detected via {bed_btn}")
                    return "bed_found"
                self._key_burst(["down"], 0.6)
                time.sleep(0.3)
                bed_btn = self._detect_bed()
                if bed_btn is not None:
                    self._status("Bed confirmed after backtrack")
                    return "bed_found"

        return "leg_complete"

    # ------------------------------------------------------------------
    # Bed detection & interaction
    # ------------------------------------------------------------------

    def _detect_bed(self) -> str | None:
        win = find_ttr_window()
        if win is None:
            return None
        frame = capture_window(win)
        if frame is None:
            return None
        return detect_bed_button(frame)

    def _interact_at_bed(
        self,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
    ) -> None:
        result.beds_visited += 1
        bed_num = result.beds_visited
        self._status(f"Bed #{bed_num}: checking state…")

        win = find_ttr_window()
        if win is None:
            return
        frame = capture_window(win)
        if frame is None:
            return

        state = classify_bed_state(frame)

        debug_frame = frame.copy()
        cv2.putText(
            debug_frame,
            f"STATE: {state}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 255, 255),
            3,
        )
        y_off = 80
        for btn_name in BED_BUTTON_NAMES:
            m = tm.find_template(frame, btn_name)
            label = f"{btn_name}: {m.confidence:.3f} @({m.x},{m.y})" if m else f"{btn_name}: ---"
            cv2.putText(
                debug_frame, label, (20, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
            )
            y_off += 30
        self._debug_save(debug_frame, f"bed{bed_num}_state_{state}")
        self._execute_bed_action(state, bed_num, flower_name, bean_sequence, result)
        time.sleep(0.5)

    def _execute_bed_action(
        self,
        state: str,
        bed_num: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
    ) -> None:
        if state == "pick":
            self._do_pick_and_plant(bed_num, flower_name, bean_sequence, result)
        elif state == "plant":
            self._status(f"Bed #{bed_num}: planting {flower_name}")
            if self._bot.plant_flower(flower_name, bean_sequence):
                result.beds_planted += 1
        else:
            self._status(f"Bed #{bed_num}: state={state} — skipping")

    def _do_pick_and_plant(
        self,
        bed_num: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
    ) -> None:
        self._status(f"Bed #{bed_num}: picking grown flower")
        if self._bot.pick_flower():
            result.beds_picked += 1
            time.sleep(1.0)
            self._status(f"Bed #{bed_num}: planting {flower_name}")
            if self._bot.plant_flower_no_pick(flower_name, bean_sequence):
                result.beds_planted += 1

    # ------------------------------------------------------------------
    # Movement helpers
    # ------------------------------------------------------------------

    def _recover_from_stuck(self) -> None:
        """Walk backward and turn to escape camera-clipping / stuck spots."""
        self._status("Stuck — recovering…")
        self._key_burst(["down"], 1.0)
        time.sleep(0.2)
        self._key_burst(["right"], 0.8)
        time.sleep(0.2)
        self._key_burst(["up"], 0.6)
        time.sleep(0.2)

    def _walk_away(self) -> None:
        self._key_burst(["down"], settings.SWEEP_POST_INTERACT_WALK_S)
        time.sleep(0.2)
        for _ in range(6):
            if self._stop_event.is_set():
                return
            if self._detect_bed() is None:
                return
            self._key_burst(["down"], 0.3)
            time.sleep(0.2)

    def _key_burst(self, keys: list[str], duration: float) -> None:
        inp.ensure_focused()
        for k in keys:
            pyautogui.keyDown(k)
        try:
            self._interruptible_sleep(duration)
        finally:
            inp.ensure_focused()
            for k in keys:
                pyautogui.keyUp(k)

    def _release_all_keys(self) -> None:
        with contextlib.suppress(Exception):
            inp.ensure_focused()
        for k in _ARROW_KEYS:
            with contextlib.suppress(Exception):
                pyautogui.keyUp(k)

    def _interruptible_sleep(self, duration: float) -> bool:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            time.sleep(min(0.05, deadline - time.monotonic()))
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_stop(self, result: SweepResult, target_beds: int) -> bool:
        return self._stop_event.is_set() or result.beds_visited >= target_beds

    def _status(self, msg: str) -> None:
        log.info("[Sweeper] %s", msg)
        if self.on_status:
            with contextlib.suppress(Exception):
                self.on_status(msg)

    def _print_summary(self, r: SweepResult) -> None:
        msg = (
            f"\n{'═' * 44}\n"
            f" SWEEP COMPLETE\n"
            f"{'═' * 44}\n"
            f" Beds visited:       {r.beds_visited}\n"
            f" Planted:            {r.beds_planted}\n"
            f" Picked:             {r.beds_picked}\n"
            f" Watered:            {r.beds_watered}\n"
            f" Time:               {int(r.total_time_s) // 60}m "
            f"{int(r.total_time_s) % 60:02d}s\n"
            f"{'═' * 44}"
        )
        self._status(msg)
