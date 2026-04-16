"""Garden Sweeper: visual-guided flower-bed navigation.

TTR movement model (fixed camera behind character):
- **Up** = walk forward (direction character faces)
- **Left / Right** = turn in place (pure rotation, no forward movement)
- **Down** = walk backward

Navigation approach:

1.  Scan the screen for visible flowers (red-near-green colour blobs).
2.  Steer toward them: if flowers are to the left, turn left; right -> right.
3.  Walk forward and poll for gardening UI buttons (Pick / Plant / Water).
4.  When buttons appear -> interact with the bed.
5.  After interacting, walk away and scan again.
6.  If no flowers are visible, rotate slowly until some come into view.
"""

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
from ttr_bot.core.screen_capture import grab_frame
from ttr_bot.gardening.bed_ui import detect_bed_button
from ttr_bot.gardening.gardening_bot import GardenBot
from ttr_bot.gardening.sweep_interaction import (
    BedActionContext,
    ScanCallbacks,
    interact_at_bed,
    walk_and_scan,
)
from ttr_bot.utils import debug_frames as dbg
from ttr_bot.utils.logger import log
from ttr_bot.vision.flower_detector import debug_annotate, steering_hint

_DEBUG_DIR = os.path.join(settings.DATA_DIR, "_debug", "sweep")

_ARROW_KEYS = ("up", "down", "left", "right")


@dataclass(slots=True)
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
        dbg.clear_pngs(_DEBUG_DIR)
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

    def _make_bed_ctx(
        self, flower_name: str, bean_sequence: str, result: SweepResult,
    ) -> BedActionContext:
        return BedActionContext(
            flower_name=flower_name,
            bean_sequence=bean_sequence,
            result=result,
            bot=self._bot,
            status_fn=self._status,
            debug_save_fn=self._debug_save,
        )

    def _make_scan_cb(self) -> ScanCallbacks:
        return ScanCallbacks(
            detect_bed_fn=self._detect_bed,
            key_burst_fn=self._key_burst,
            status_fn=self._status,
            grab_frame_fn=self._grab_frame,
            debug_save_fn=self._debug_save,
        )

    def _discover(
        self,
        max_laps: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
        target_beds: int,
    ) -> None:
        bed_ctx = self._make_bed_ctx(flower_name, bean_sequence, result)
        scan_cb = self._make_scan_cb()

        bed_btn = self._detect_bed()
        if bed_btn is not None:
            self._status("Already at a bed — interacting")
            interact_at_bed(bed_ctx)
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

            hint = steering_hint(frame)
            self._debug_save(
                debug_annotate(frame, hint.direction, hint.magnitude), f"steer_{hint.direction}"
            )

            if hint.direction == "none":
                idle_count = self._handle_no_flowers(idle_count, bed_ctx, scan_cb)
                continue

            idle_count = 0

            if hint.direction in ("left", "right"):
                turn_dur = settings.SWEEP_TURN_BURST_S * hint.magnitude
                self._status(
                    f"Flowers {hint.direction} ({hint.magnitude:.2f}) — turning {turn_dur:.2f}s"
                )
                self._key_burst([hint.direction], turn_dur)

            self._status(f"Walking toward flowers (visited {result.beds_visited}/{target_beds})")
            outcome = walk_and_scan(
                ["up"], settings.SWEEP_WALK_BURST_S, self._stop_event, scan_cb,
            )
            if outcome == "bed_found":
                interact_at_bed(bed_ctx)
                self._walk_away()

    def _handle_no_flowers(
        self,
        idle_count: int,
        bed_ctx: BedActionContext,
        scan_cb: ScanCallbacks,
    ) -> int:
        """React when no flowers are visible. Returns the updated idle counter."""
        idle_count += 1
        if idle_count >= settings.SWEEP_MAX_IDLE:
            self._recover_from_stuck()
            return 0
        if idle_count <= settings.SWEEP_WALK_BEFORE_ROTATE:
            self._status(f"No flowers — walking forward to search ({idle_count})")
            outcome = walk_and_scan(
                ["up"], settings.SWEEP_WALK_BURST_S, self._stop_event, scan_cb,
            )
            if outcome == "bed_found":
                interact_at_bed(bed_ctx)
                self._walk_away()
        else:
            self._status("No flowers — rotating to scan")
            self._key_burst(["right"], settings.SWEEP_SCAN_ROTATE_S)
        return idle_count

    # ------------------------------------------------------------------
    # Bed detection
    # ------------------------------------------------------------------

    def _detect_bed(self) -> str | None:
        frame = grab_frame()
        return detect_bed_button(frame) if frame is not None else None

    # ------------------------------------------------------------------
    # Movement helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _grab_frame():
        return grab_frame()

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
        return not self._stop_event.wait(timeout=duration)

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
