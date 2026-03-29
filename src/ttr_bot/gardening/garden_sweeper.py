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
7.  Falls back to a perimeter walk pattern if vision fails repeatedly.
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass
from typing import Callable

import pyautogui

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.vision import template_matcher as tm
from ttr_bot.vision.flower_detector import steering_hint
from ttr_bot.gardening.gardening_bot import GardenBot
from ttr_bot.gardening.garden_mapper import GardenMapper
from ttr_bot.utils.logger import log


_BED_BUTTONS = (
    "remove_button",
    "pick_flower_button",
    "plant_flower_button",
    "watering_can_button",
)

_ARROW_KEYS = ("up", "down", "left", "right")

# Fallback rectangular walk pattern used when vision finds no flowers.
_FALLBACK_WALK_PATTERN: list[tuple[list[str], float]] = [
    (["up"], 8.0),
    (["right"], 2.5),
    (["up"], 6.0),
    (["right"], 2.5),
    (["up"], 8.0),
    (["right"], 2.5),
    (["up"], 6.0),
    (["right"], 2.5),
]

_VISUAL_WALK_BURST_S = 1.5
_VISUAL_TURN_BURST_S = 0.4
_VISUAL_SCAN_ROTATE_S = 0.6
_MAX_BLIND_ROTATIONS = 12


@dataclass
class SweepResult:
    beds_visited: int = 0
    beds_planted: int = 0
    beds_watered: int = 0
    beds_picked: int = 0
    laps_completed: int = 0
    phase2_navigations: int = 0
    total_time_s: float = 0.0
    reason: str = ""
    map_image_path: str = ""
    map_json_path: str = ""


class GardenSweeper:
    """Walk-and-scan garden automation with live 2-D mapping."""

    def __init__(
        self,
        garden_bot: GardenBot,
        stop_event: threading.Event,
    ) -> None:
        self._bot = garden_bot
        self._stop_event = stop_event
        self._mapper = GardenMapper()
        self.on_status: Callable[[str], None] | None = None

    @property
    def mapper(self) -> GardenMapper:
        return self._mapper

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sweep(
        self,
        flower_name: str,
        bean_sequence: str,
        target_beds: int = 0,
        max_laps: int = 0,
        walk_pattern: list[tuple[list[str], float]] | None = None,
        saved_map_path: str | None = None,
    ) -> SweepResult:
        if target_beds <= 0:
            target_beds = settings.SWEEP_TARGET_BEDS
        if max_laps <= 0:
            max_laps = settings.SWEEP_MAX_LAPS
        pattern = walk_pattern or _FALLBACK_WALK_PATTERN
        result = SweepResult()
        t0 = time.monotonic()

        self._status(f"Starting sweep — {flower_name}, target {target_beds} beds")

        if not self._bot._ensure_calibrated():
            result.reason = "Calibration failed"
            return result

        try:
            self._run_sweep_phases(
                pattern,
                max_laps,
                flower_name,
                bean_sequence,
                result,
                target_beds,
                saved_map_path,
            )
        finally:
            self._release_all_keys()

        result.map_json_path, result.map_image_path = self._save_map()

        result.total_time_s = time.monotonic() - t0
        result.reason = (
            "User stopped"
            if self._stop_event.is_set()
            else f"Done — {result.beds_visited} beds in "
            f"{result.laps_completed} laps + "
            f"{result.phase2_navigations} targeted navs"
        )
        self._print_summary(result)
        return result

    def _run_sweep_phases(
        self,
        pattern: list[tuple[list[str], float]],
        max_laps: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
        target_beds: int,
        saved_map_path: str | None,
    ) -> None:
        loaded_map = self._try_load_map(saved_map_path)
        if loaded_map is not None:
            self._mapper = loaded_map
            self._status(
                f"Loaded saved map with {self._mapper.bed_count} beds "
                "— skipping to targeted navigation"
            )
        else:
            self._phase1_discovery(
                pattern,
                max_laps,
                flower_name,
                bean_sequence,
                result,
                target_beds,
            )

        if not self._should_stop(result, target_beds) and self._mapper.bed_count > 0:
            self._phase2_targeted(flower_name, bean_sequence, result, target_beds)

    # ------------------------------------------------------------------
    # Phase 1: Visual discovery
    # ------------------------------------------------------------------

    def _phase1_discovery(
        self,
        pattern: list[tuple[list[str], float]],
        max_laps: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
        target_beds: int,
    ) -> None:
        bed_btn = self._detect_bed(fast=False)
        if bed_btn is not None:
            self._status("Already at a bed — interacting")
            self._mapper.mark_bed(bed_btn)
            self._interact_at_bed(flower_name, bean_sequence, result)
            self._walk_away()

        self._status("Phase 1 — visual scan-and-navigate")
        blind_streak = 0

        for _ in range(max_laps * len(pattern)):
            if self._should_stop(result, target_beds):
                break

            frame = self._grab_frame()
            if frame is None:
                break

            direction, magnitude = steering_hint(frame)

            if direction == "none":
                blind_streak += 1
                if blind_streak > _MAX_BLIND_ROTATIONS:
                    self._status("No flowers visible — falling back to walk pattern")
                    self._run_fallback_lap(
                        pattern, flower_name, bean_sequence, result, target_beds,
                    )
                    result.laps_completed += 1
                    blind_streak = 0
                    continue
                self._status(f"Scanning… rotating to find flowers ({blind_streak})")
                self._execute_turn(["right"], _VISUAL_SCAN_ROTATE_S)
                continue

            blind_streak = 0

            if direction in ("left", "right"):
                turn_dur = _VISUAL_TURN_BURST_S * max(0.3, magnitude)
                self._status(f"Flowers visible {direction} — turning")
                self._execute_turn([direction], turn_dur)

            self._status(
                f"Walking toward flowers "
                f"(visited {result.beds_visited}/{target_beds})"
            )
            outcome = self._walk_and_scan(["up"], _VISUAL_WALK_BURST_S)
            if outcome == "bed_found":
                self._interact_at_bed(flower_name, bean_sequence, result)
                self._walk_away()

    def _run_fallback_lap(
        self,
        pattern: list[tuple[list[str], float]],
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
        target_beds: int,
    ) -> None:
        """Execute one lap of the fixed rectangular walk pattern."""
        for keys, duration in pattern:
            if self._should_stop(result, target_beds):
                break
            is_turn = "up" not in keys and "down" not in keys
            if is_turn:
                self._execute_turn(keys, duration)
            else:
                outcome = self._walk_and_scan(keys, duration)
                if outcome == "bed_found":
                    self._interact_at_bed(flower_name, bean_sequence, result)
                    self._walk_away()

    # ------------------------------------------------------------------
    # Phase 2: Targeted navigation via map
    # ------------------------------------------------------------------

    def _phase2_targeted(
        self,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
        target_beds: int,
    ) -> None:
        visited_ids: set[int] = set()
        route = self._mapper.plan_route(visited_ids)
        if not route:
            return

        self._status(
            f"Phase 2 — navigating to {len(route)} known beds (nearest-neighbor route)"
        )

        for bed in route:
            if self._should_stop(result, target_beds):
                break

            keys, est_duration = self._mapper.direction_to(bed.x, bed.y)
            if not keys:
                continue

            self._status(
                f"Phase 2 · heading to bed #{bed.index} "
                f"({'+'.join(keys)} ~{est_duration:.1f}s)"
            )

            arrived = self._navigate_to_target(est_duration, bed.x, bed.y)
            result.phase2_navigations += 1

            if arrived:
                self._mapper.mark_bed(self._detect_bed() or bed.bed_type)
                self._interact_at_bed(flower_name, bean_sequence, result)
                visited_ids.add(bed.index)
                self._walk_away()
            else:
                self._status(f"Phase 2 · missed bed #{bed.index} — continuing")

    def _navigate_to_target(
        self,
        est_duration: float,
        target_x: float,
        target_y: float,
    ) -> bool:
        """Steer toward a mapped target, polling for bed arrival.

        Recalculates heading each iteration so the character self-corrects:
        first a turn action, then forward walking.
        """
        check = settings.SWEEP_CHECK_INTERVAL_S
        elapsed = 0.0
        budget = est_duration * 1.5 + 2.0

        while elapsed < budget:
            if self._stop_event.is_set():
                return False

            keys, remaining = self._mapper.direction_to(target_x, target_y)
            if not keys or remaining < 0.15:
                break

            burst = min(check, budget - elapsed, remaining)
            self._key_burst(keys, burst)
            self._mapper.update(keys, burst)
            elapsed += burst

            bed_btn = self._detect_bed()
            if bed_btn is not None:
                time.sleep(0.3)
                if self._detect_bed() is not None:
                    return True

        return self._detect_bed() is not None

    # ------------------------------------------------------------------
    # Walk-and-scan (Phase 1 core loop)
    # ------------------------------------------------------------------

    def _grab_frame(self):
        """Capture the current game frame, or None on failure."""
        win = find_ttr_window()
        if win is None:
            return None
        return capture_window(win)

    def _execute_turn(self, keys: list[str], duration: float) -> None:
        """Turn in place without bed-detection overhead."""
        if self._stop_event.is_set():
            return
        self._key_burst(keys, duration)
        self._mapper.update(keys, duration)

    def _walk_and_scan(
        self,
        keys: list[str],
        leg_duration: float,
    ) -> str:
        """Walk using *keys* for *leg_duration*, polling for beds.

        Every burst is recorded in the mapper.
        Returns ``"bed_found"``, ``"leg_complete"``, or ``"stopped"``.
        """
        check_interval = settings.SWEEP_CHECK_INTERVAL_S
        elapsed = 0.0

        while elapsed < leg_duration:
            if self._stop_event.is_set():
                return "stopped"

            burst = min(check_interval, leg_duration - elapsed)
            self._key_burst(keys, burst)
            self._mapper.update(keys, burst)
            elapsed += burst

            bed_btn = self._detect_bed()
            if bed_btn is not None:
                time.sleep(0.3)
                bed_btn = self._detect_bed()
                if bed_btn is not None:
                    self._status(f"Bed detected via {bed_btn}")
                    self._mapper.mark_bed(bed_btn)
                    return "bed_found"
                # Walked past — back up a little.
                self._key_burst(["down"], 0.6)
                self._mapper.update(["down"], 0.6)
                time.sleep(0.3)
                bed_btn = self._detect_bed()
                if bed_btn is not None:
                    self._status("Bed confirmed after backtrack")
                    self._mapper.mark_bed(bed_btn)
                    return "bed_found"

        return "leg_complete"

    # ------------------------------------------------------------------
    # Bed detection & interaction
    # ------------------------------------------------------------------

    def _detect_bed(self, fast: bool = True) -> str | None:
        """Return the bed-indicator button visible on screen, or None.

        Checks Remove *before* Pick because the two templates look similar
        and Pick can false-positive when Remove is the real button.
        When *fast=True*, uses the locked scale only (no fallback probes).
        """
        win = find_ttr_window()
        if win is None:
            return None
        frame = capture_window(win)
        if frame is None:
            return None
        match_fn = tm.find_template_fast if fast else tm.find_template
        for btn in _BED_BUTTONS:
            if match_fn(frame, btn) is not None:
                return btn
        return None

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

        state = self._classify_bed_state(frame)
        self._execute_bed_action(state, bed_num, flower_name, bean_sequence, result)
        time.sleep(0.5)

    def _classify_bed_state(self, frame) -> str:
        """Return one of 'pick', 'plant', 'growing', 'water', or 'unknown'."""
        has_remove = tm.find_template(frame, "remove_button") is not None
        if has_remove:
            has_water = tm.find_template(frame, "watering_can_button") is not None
            return "growing" if has_water else "unknown"

        if tm.find_template(frame, "pick_flower_button") is not None:
            return "pick"
        if tm.find_template(frame, "plant_flower_button") is not None:
            return "plant"
        if tm.find_template(frame, "watering_can_button") is not None:
            return "water"
        return "unknown"

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
            if self._bot._plant_flower(flower_name, bean_sequence):
                result.beds_planted += 1
        elif state in ("growing", "water"):
            label = "growing — watering only" if state == "growing" else "watering"
            self._status(f"Bed #{bed_num}: {label}")
            if self._bot._water_plant(settings.GARDEN_WATERS_AFTER_PLANT):
                result.beds_watered += 1

    def _do_pick_and_plant(
        self,
        bed_num: int,
        flower_name: str,
        bean_sequence: str,
        result: SweepResult,
    ) -> None:
        self._status(f"Bed #{bed_num}: picking grown flower")
        if self._bot._pick_flower():
            result.beds_picked += 1
            time.sleep(1.0)
            self._status(f"Bed #{bed_num}: planting {flower_name}")
            if self._bot._plant_flower(flower_name, bean_sequence):
                result.beds_planted += 1

    # ------------------------------------------------------------------
    # Movement helpers
    # ------------------------------------------------------------------

    def _walk_away(self) -> None:
        """Walk forward to leave the bed's interaction zone."""
        dur = settings.SWEEP_POST_INTERACT_WALK_S
        self._key_burst(["up"], dur)
        self._mapper.update(["up"], dur)
        time.sleep(0.3)

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
        """Force-release all arrow keys (e.g. after stop while keys are held)."""
        try:
            inp.ensure_focused()
        except Exception:
            pass
        for k in _ARROW_KEYS:
            try:
                pyautogui.keyUp(k)
            except Exception:
                pass

    def _interruptible_sleep(self, duration: float) -> bool:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            time.sleep(min(0.05, deadline - time.monotonic()))
        return True

    # ------------------------------------------------------------------
    # Map persistence
    # ------------------------------------------------------------------

    def _try_load_map(self, path: str | None) -> GardenMapper | None:
        if path is None:
            path = settings.SWEEP_MAP_JSON
        if not os.path.isfile(path):
            return None
        try:
            return GardenMapper.load(path)
        except Exception as exc:
            log.warning("Failed to load saved map: %s", exc)
            return None

    def _save_map(self) -> tuple[str, str]:
        json_path = settings.SWEEP_MAP_JSON
        img_path = settings.SWEEP_MAP_IMAGE
        try:
            self._mapper.save(json_path)
            self._mapper.save_image(img_path)
            self._status(f"Map saved ({self._mapper.bed_count} beds)")
        except Exception as exc:
            log.warning("Failed to save map: %s", exc)
        return json_path, img_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_stop(self, result: SweepResult, target_beds: int) -> bool:
        return self._stop_event.is_set() or result.beds_visited >= target_beds

    def _status(self, msg: str) -> None:
        log.info("[Sweeper] %s", msg)
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _print_summary(self, r: SweepResult) -> None:
        msg = (
            f"\n{'═' * 44}\n"
            f" SWEEP COMPLETE\n"
            f"{'═' * 44}\n"
            f" Beds visited:       {r.beds_visited}\n"
            f" Planted:            {r.beds_planted}\n"
            f" Picked:             {r.beds_picked}\n"
            f" Watered:            {r.beds_watered}\n"
            f" Discovery laps:     {r.laps_completed}\n"
            f" Targeted navs:      {r.phase2_navigations}\n"
            f" Time:               {int(r.total_time_s) // 60}m "
            f"{int(r.total_time_s) % 60:02d}s\n"
            f" Map:                {r.map_image_path}\n"
            f"{'═' * 44}"
        )
        self._status(msg)
