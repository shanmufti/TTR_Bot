"""Core gardening automation: plant flowers and water plants.

Follows the same threading / callback pattern as fishing_bot.FishingBot.
All clicks go through input_controller.click() which handles Retina scaling.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable

from config import settings
from core import input_controller as inp
from core.screen_capture import capture_window
from core.window_manager import find_ttr_window, WindowInfo
from gardening.flowers import BEAN_CHAR_TO_TEMPLATE
from vision.template_matcher import find_template, is_element_visible
from utils.logger import log


@dataclass
class GardeningStats:
    flowers_planted: int = 0
    waters_done: int = 0
    current_action: str = ""


@dataclass
class GardenAction:
    """A single gardening action for the bot to execute."""
    action: str  # "plant" or "water"
    flower_name: str = ""
    bean_sequence: str = ""
    water_count: int = 1


_CACHEABLE_TEMPLATES: frozenset[str] = frozenset(BEAN_CHAR_TO_TEMPLATE.values()) | {
    "blue_plant_button",
    "watering_can_button",
    "pick_flower_button",
}


class GardenBot:
    """Controls gardening automation (plant / water) in a background thread."""

    def __init__(self) -> None:
        self.stats = GardeningStats()

        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Cache of (x, y) click positions for jellybean & plant buttons.
        # These stay fixed while the bean picker dialog is open.
        self._click_cache: dict[str, tuple[int, int]] = {}

        self.on_status_update: Callable[[str], None] | None = None
        self.on_stats_update: Callable[[GardeningStats], None] | None = None
        self.on_gardening_ended: Callable[[str], None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    def start_plant(self, flower_name: str, bean_sequence: str) -> None:
        """Plant a single flower in a background thread."""
        action = GardenAction(
            action="plant",
            flower_name=flower_name,
            bean_sequence=bean_sequence,
        )
        self._start([action])

    def start_water(self, count: int) -> None:
        """Water the current plant *count* times in a background thread."""
        action = GardenAction(action="water", water_count=count)
        self._start([action])

    def start_actions(self, actions: list[GardenAction]) -> None:
        """Execute a list of gardening actions sequentially."""
        self._start(actions)

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def reset(self) -> None:
        """Reset internal state so the bot can be reused by a routine."""
        self._stop_event.clear()
        self._running = False
        self._paused = False

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        state = "PAUSED" if self._paused else "RESUMED"
        log.info("Gardening %s", state)
        self._notify_status(state)

    # ------------------------------------------------------------------
    # Internal: thread management
    # ------------------------------------------------------------------

    def _start(self, actions: list[GardenAction]) -> None:
        if self._running:
            log.warning("Gardening already running")
            return
        self.stats = GardeningStats()
        self._stop_event.clear()
        self._running = True
        self._paused = False
        self._click_cache.clear()
        self._thread = threading.Thread(
            target=self._run_actions, args=(actions,), daemon=True,
        )
        self._thread.start()

    def _run_actions(self, actions: list[GardenAction]) -> None:
        try:
            if not self._ensure_calibrated():
                self._finish("Calibration failed — stand at garden first")
                return

            for i, action in enumerate(actions):
                if self._stop_event.is_set():
                    break
                self._wait_if_paused()
                if self._stop_event.is_set():
                    break

                label = f"[{i + 1}/{len(actions)}]"

                if action.action == "plant":
                    self._notify_status(f"{label} Planting {action.flower_name}…")
                    self.stats.current_action = f"Planting {action.flower_name}"
                    self._notify_stats()
                    ok = self._plant_flower(action.flower_name, action.bean_sequence)
                    if ok:
                        self.stats.flowers_planted += 1
                        self._notify_stats()
                    else:
                        self._finish(f"Plant failed: {action.flower_name}")
                        return

                elif action.action == "water":
                    self._notify_status(f"{label} Watering ×{action.water_count}…")
                    self.stats.current_action = f"Watering ×{action.water_count}"
                    self._notify_stats()
                    ok = self._water_plant(action.water_count)
                    if not ok:
                        self._finish("Water failed: button not found")
                        return

                elif action.action == "walk":
                    pass  # handled by routine_runner

                elif action.action == "delay":
                    pass  # handled by routine_runner

            reason = "User stopped" if self._stop_event.is_set() else "Completed"
            self._finish(reason)

        except Exception as exc:
            log.exception("Gardening loop crashed")
            self._finish(f"Error: {exc}")

    # ------------------------------------------------------------------
    # Core gardening operations
    # ------------------------------------------------------------------

    def _pick_flower(self) -> bool:
        """Click the Pick button to remove the existing flower."""
        if not self._find_and_click("pick_flower_button"):
            self._notify_status("Pick button not found")
            return False

        time.sleep(settings.GARDEN_POST_PICK_DELAY_S)
        log.info("Picked flower")
        return True

    def _plant_flower(self, flower_name: str, bean_sequence: str) -> bool:
        """Full plant sequence: auto-detect bed state → pick if needed → plant → water."""

        # Step 0: detect bed state — pick existing flower if needed
        win = find_ttr_window()
        if win is not None:
            frame = capture_window(win)
            if frame is not None and is_element_visible(frame, "pick_flower_button"):
                self._notify_status(f"Existing flower detected — picking before planting {flower_name}")
                if not self._find_and_click("pick_flower_button"):
                    self._notify_status("Pick button not found")
                    return False
                time.sleep(settings.GARDEN_POST_PICK_DELAY_S)

        # Step 1: Click "Plant Flower" button
        if not self._find_and_click("plant_flower_button"):
            self._notify_status("Plant Flower button not found")
            return False
        time.sleep(settings.GARDEN_POST_CONFIRM_DELAY_S)

        # Step 2: Click each jellybean in the recipe
        for i, bean_char in enumerate(bean_sequence):
            if self._stop_event.is_set():
                return False
            template_name = BEAN_CHAR_TO_TEMPLATE.get(bean_char)
            if template_name is None:
                log.warning("Unknown bean character: %r", bean_char)
                return False

            log.info("  Bean %d/%d: %s", i + 1, len(bean_sequence), template_name)
            if not self._find_and_click(template_name):
                self._notify_status(f"Jellybean button not found: {bean_char}")
                return False
            time.sleep(settings.GARDEN_POST_BEAN_DELAY_S)

        # Step 3: Click "Plant" confirmation button
        if not self._find_and_click("blue_plant_button"):
            self._notify_status("Plant confirmation button not found")
            return False
        time.sleep(settings.GARDEN_POST_PLANT_DELAY_S)

        # Step 4: Click "OK" on the result dialog (may not appear on all flowers)
        if not self._find_and_click("ok_button", timeout=3.0):
            log.info("OK button not found after planting — continuing")
        time.sleep(settings.GARDEN_POST_CONFIRM_DELAY_S)

        # Step 5: Water the newly planted flower (if configured)
        if settings.GARDEN_WATERS_AFTER_PLANT > 0:
            self._notify_status(f"Watering new {flower_name}…")
            if not self._water_plant(settings.GARDEN_WATERS_AFTER_PLANT):
                self._notify_status("Watering failed after planting — game state may have changed")
                return False

        log.info("Planted %s successfully", flower_name)
        return True

    def _water_plant(self, count: int) -> bool:
        """Click the watering can *count* times. Returns False on failure."""
        for i in range(count):
            if self._stop_event.is_set():
                return False
            self._wait_if_paused()

            log.info("  Water %d/%d", i + 1, count)
            if not self._find_and_click("watering_can_button"):
                self._notify_status("Watering can button not found")
                return False
            self.stats.waters_done += 1
            self._notify_stats()
            time.sleep(settings.GARDEN_POST_WATER_DELAY_S)

        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_and_click(
        self,
        template_name: str,
        win: WindowInfo | None = None,
        timeout: float = settings.GARDEN_FIND_TIMEOUT_S,
    ) -> bool:
        """Poll for a template and click it. Returns True on success.

        Re-detects the window each call to handle position changes (lesson 6).
        Jellybean and plant-confirm buttons are cached after the first hit
        because they stay fixed while the bean picker dialog is open.
        """
        if win is None:
            win = find_ttr_window()
        if win is None:
            return False

        cacheable = template_name in _CACHEABLE_TEMPLATES
        cached_pos = self._click_cache.get(template_name) if cacheable else None

        if cached_pos is not None:
            inp.ensure_focused()
            time.sleep(0.05)
            inp.click(cached_pos[0], cached_pos[1], window=win)
            log.info("Clicked %s at cached (%d,%d)",
                     template_name, cached_pos[0], cached_pos[1])
            return True

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False

            frame = capture_window(win)
            if frame is None:
                time.sleep(0.1)
                continue

            match = find_template(frame, template_name)
            if match is not None:
                if cacheable:
                    self._click_cache[template_name] = (match.x, match.y)
                    log.info("Cached %s at (%d,%d)", template_name, match.x, match.y)

                inp.ensure_focused()
                time.sleep(0.05)
                inp.click(match.x, match.y, window=win)
                log.info("Clicked %s at (%d,%d) conf=%.2f",
                         template_name, match.x, match.y, match.confidence)
                return True

            time.sleep(0.2)

        log.warning("Template %s not found within %.1fs", template_name, timeout)
        return False

    def _ensure_calibrated(self) -> bool:
        """Verify scale calibration is set, running it if needed."""
        from vision import template_matcher as tm
        from core.window_manager import set_calibrated_bounds

        if tm._global_scale is not None:
            return True

        self._notify_status("Calibrating…")
        win = find_ttr_window()
        if win is None:
            log.warning("Calibration failed: TTR window not found")
            return False

        set_calibrated_bounds(win.x, win.y, win.width, win.height)

        frame = capture_window(win)
        if frame is None:
            log.warning("Calibration failed: could not capture frame")
            return False

        scale = tm.calibrate_scale(frame)
        if scale < 0:
            log.warning("Calibration failed: no anchor template found")
            return False

        self._notify_status(f"Calibrated: scale={scale:.1f}")
        return True

    def _wait_if_paused(self) -> None:
        while self._paused and not self._stop_event.is_set():
            time.sleep(0.25)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_status(self, msg: str) -> None:
        log.info(msg)
        if self.on_status_update:
            try:
                self.on_status_update(msg)
            except Exception:
                pass

    def _notify_stats(self) -> None:
        if self.on_stats_update:
            try:
                self.on_stats_update(self.stats)
            except Exception:
                pass

    def _finish(self, reason: str) -> None:
        self._running = False
        log.info(
            "Gardening ended: %s  (planted=%d, watered=%d)",
            reason, self.stats.flowers_planted, self.stats.waters_done,
        )
        if self.on_gardening_ended:
            try:
                self.on_gardening_ended(reason)
            except Exception:
                pass
