"""Core gardening automation: plant flowers and water plants.

Follows the same threading / callback pattern as fishing_bot.FishingBot.
All clicks go through input_controller.click() which handles Retina scaling.
"""

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.gardening.flowers import BEAN_CHAR_TO_TEMPLATE
from ttr_bot.utils.logger import log
from ttr_bot.vision.template_matcher import find_template, is_element_visible


@dataclass
class GardeningStats:
    """Running counters for a gardening session."""

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


class GardenBot:
    """Controls gardening automation (plant / water) in a background thread."""

    def __init__(self) -> None:
        self.stats = GardeningStats()

        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

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
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._running = False
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
        self._thread = threading.Thread(
            target=self._run_actions,
            args=(actions,),
            daemon=True,
        )
        self._thread.start()

    def _run_actions(self, actions: list[GardenAction]) -> None:
        try:
            if not self.ensure_calibrated():
                self._finish("Calibration failed — stand at garden first")
                return

            for i, action in enumerate(actions):
                if self._stop_event.is_set():
                    break
                self._wait_if_paused()
                if self._stop_event.is_set():
                    break

                err = self._execute_action(action, f"[{i + 1}/{len(actions)}]")
                if err is not None:
                    self._finish(err)
                    return

            reason = "User stopped" if self._stop_event.is_set() else "Completed"
            self._finish(reason)

        except Exception as exc:
            log.exception("Gardening loop crashed")
            self._finish(f"Error: {exc}")

    def _execute_action(self, action: GardenAction, label: str) -> str | None:
        """Run one garden action. Returns an error message on failure, None on success."""
        if action.action == "plant":
            self._notify_status(f"{label} Planting {action.flower_name}...")
            self.stats.current_action = f"Planting {action.flower_name}"
            self._notify_stats()
            if not self.plant_flower(action.flower_name, action.bean_sequence):
                return f"Plant failed: {action.flower_name}"
            self.stats.flowers_planted += 1
            self._notify_stats()
        elif action.action == "water":
            self._notify_status(f"{label} Watering x{action.water_count}...")
            self.stats.current_action = f"Watering x{action.water_count}"
            self._notify_stats()
            if not self.water_plant(action.water_count):
                return "Water failed: button not found"
        return None

    # ------------------------------------------------------------------
    # Core gardening operations
    # ------------------------------------------------------------------

    def pick_flower(self) -> bool:
        """Click the Pick button to remove the existing flower."""
        t0 = time.monotonic()
        if not self._find_and_click("pick_flower_button"):
            self._notify_status("Pick button not found")
            return False
        log.info("[Timing] pick_click=%.0fms", (time.monotonic() - t0) * 1000)

        t1 = time.monotonic()
        time.sleep(settings.GARDEN_POST_PICK_DELAY_S)
        log.info(
            "[Timing] pick_anim_wait=%.0fms (POST_PICK_DELAY=%.2fs)",
            (time.monotonic() - t1) * 1000,
            settings.GARDEN_POST_PICK_DELAY_S,
        )
        log.info("Picked flower — total %.0fms", (time.monotonic() - t0) * 1000)
        return True

    def plant_flower_no_pick(self, flower_name: str, bean_sequence: str) -> bool:
        """Plant sequence skipping auto-pick (caller already picked)."""
        return self._do_plant(flower_name, bean_sequence)

    def plant_flower(self, flower_name: str, bean_sequence: str) -> bool:
        """Full plant sequence: auto-detect bed state → pick if needed → plant → water."""

        win = find_ttr_window()
        if win is not None:
            frame = capture_window(win)
            if frame is not None and is_element_visible(frame, "pick_flower_button"):
                self._notify_status(
                    f"Existing flower detected — picking before planting {flower_name}"
                )
                if not self._find_and_click("pick_flower_button"):
                    self._notify_status("Pick button not found")
                    return False
                time.sleep(settings.GARDEN_POST_PICK_DELAY_S)

        return self._do_plant(flower_name, bean_sequence)

    def _do_plant(self, flower_name: str, bean_sequence: str) -> bool:
        """Shared plant+water logic used by both _plant_flower and _plant_flower_no_pick."""
        plant_t0 = time.monotonic()
        win = find_ttr_window()
        if win is None:
            self._notify_status("Window not found")
            return False

        if not self._click_plant_button(win):
            return False
        if not self._select_beans(bean_sequence, win):
            return False
        if not self._confirm_plant(flower_name):
            return False

        log.info("[Timing] _do_plant total=%.0fms", (time.monotonic() - plant_t0) * 1000)
        log.info("Planted %s successfully", flower_name)
        return True

    def _click_plant_button(self, win: WindowInfo) -> bool:
        """Click the "Plant Flower" button and wait for the dialog."""
        t0 = time.monotonic()
        if not self._find_and_click("plant_flower_button", win=win):
            self._notify_status("Plant Flower button not found")
            return False
        log.info("[Timing] plant_btn_click=%.0fms", (time.monotonic() - t0) * 1000)
        time.sleep(settings.GARDEN_POST_CONFIRM_DELAY_S)
        return True

    def _select_beans(self, bean_sequence: str, win: WindowInfo) -> bool:
        """Click each jellybean in the recipe, caching positions for repeats."""
        beans_t0 = time.monotonic()
        bean_positions: dict[str, tuple[int, int]] = {}

        for i, bean_char in enumerate(bean_sequence):
            if self._stop_event.is_set():
                return False
            template_name = BEAN_CHAR_TO_TEMPLATE.get(bean_char)
            if template_name is None:
                log.warning("Unknown bean character: %r", bean_char)
                return False

            t0 = time.monotonic()

            if template_name in bean_positions:
                pos = bean_positions[template_name]
                inp.ensure_focused()
                time.sleep(0.05)
                inp.click(pos[0], pos[1], window=win)
                log.info(
                    "  Bean %d/%d: %s at (%d,%d) [repeat] %.0fms",
                    i + 1,
                    len(bean_sequence),
                    template_name,
                    pos[0],
                    pos[1],
                    (time.monotonic() - t0) * 1000,
                )
            else:
                pos = self._find_and_click(template_name, win=win)
                if pos is None:
                    self._notify_status(f"Jellybean button not found: {bean_char}")
                    return False
                bean_positions[template_name] = pos
                log.info(
                    "  Bean %d/%d: %s [found+clicked] %.0fms",
                    i + 1,
                    len(bean_sequence),
                    template_name,
                    (time.monotonic() - t0) * 1000,
                )

            time.sleep(settings.GARDEN_POST_BEAN_DELAY_S)

        log.info(
            "[Timing] all_beans=%.0fms (%d beans)",
            (time.monotonic() - beans_t0) * 1000,
            len(bean_sequence),
        )
        return True

    def _confirm_plant(self, flower_name: str) -> bool:
        """Confirm the plant, dismiss the OK dialog, and water if configured."""
        t0 = time.monotonic()
        if not self._find_and_click("blue_plant_button"):
            self._notify_status("Plant confirmation button not found")
            return False
        log.info("[Timing] plant_confirm_click=%.0fms", (time.monotonic() - t0) * 1000)
        time.sleep(settings.GARDEN_POST_PLANT_DELAY_S)

        t0 = time.monotonic()
        ok_found = self._find_and_click("ok_button", timeout=8.0)
        ok_ms = (time.monotonic() - t0) * 1000
        log.info("[Timing] ok_btn_%s=%.0fms", "click" if ok_found else "timeout", ok_ms)
        time.sleep(settings.GARDEN_POST_CONFIRM_DELAY_S)

        if settings.GARDEN_WATERS_AFTER_PLANT > 0:
            self._notify_status(f"Watering new {flower_name}…")
            t0 = time.monotonic()
            if not self.water_plant(settings.GARDEN_WATERS_AFTER_PLANT):
                self._notify_status("Watering failed after planting — game state may have changed")
                return False
            log.info("[Timing] water_after_plant=%.0fms", (time.monotonic() - t0) * 1000)

        return True

    def water_plant(self, count: int) -> bool:
        """Click the watering can *count* times. Returns False on failure."""
        for i in range(count):
            if self._stop_event.is_set():
                return False
            self._wait_if_paused()

            t0 = time.monotonic()
            if not self._find_and_click("watering_can_button"):
                self._notify_status("Watering can button not found")
                return False
            log.info("  Water %d/%d — click=%.0fms", i + 1, count, (time.monotonic() - t0) * 1000)
            self.stats.waters_done += 1
            self._notify_stats()
            t0 = time.monotonic()
            time.sleep(settings.GARDEN_POST_WATER_DELAY_S)
            log.info(
                "[Timing] water_anim_wait=%.0fms (POST_WATER_DELAY=%.2fs)",
                (time.monotonic() - t0) * 1000,
                settings.GARDEN_POST_WATER_DELAY_S,
            )

        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_and_click(
        self,
        template_name: str,
        win: WindowInfo | None = None,
        timeout: float = settings.GARDEN_FIND_TIMEOUT_S,
    ) -> tuple[int, int] | None:
        """Poll for a template on screen and click it.

        Returns ``(x, y)`` of the clicked position on success, or ``None`` on
        failure.
        """
        if win is None:
            win = find_ttr_window()
        if win is None:
            return None

        t_start = time.monotonic()
        polls = 0
        deadline = t_start + timeout
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return None

            polls += 1
            t_cap = time.monotonic()
            frame = capture_window(win)
            cap_ms = (time.monotonic() - t_cap) * 1000
            if frame is None:
                time.sleep(0.1)
                continue

            t_match = time.monotonic()
            match = find_template(frame, template_name)
            match_ms = (time.monotonic() - t_match) * 1000

            if match is not None:
                inp.ensure_focused()
                time.sleep(0.05)
                inp.click(match.x, match.y, window=win)
                total_ms = (time.monotonic() - t_start) * 1000
                log.info(
                    "Clicked %s at (%d,%d) conf=%.2f  "
                    "(polls=%d cap=%.0fms match=%.0fms total=%.0fms)",
                    template_name,
                    match.x,
                    match.y,
                    match.confidence,
                    polls,
                    cap_ms,
                    match_ms,
                    total_ms,
                )
                return (match.x, match.y)

            time.sleep(0.2)

        log.warning("Template %s not found within %.1fs (%d polls)", template_name, timeout, polls)
        return None

    def ensure_calibrated(self) -> bool:
        """Verify scale calibration is set, running it if needed."""
        from ttr_bot.core.window_manager import set_calibrated_bounds
        from ttr_bot.vision.template_matcher import _default as tm_instance

        if tm_instance.scale is not None:
            return True

        self._notify_status("Calibrating…")
        win = find_ttr_window()
        if win is None:
            log.warning("Calibration failed: TTR window not found")
            return False

        set_calibrated_bounds(win)

        frame = capture_window(win)
        if frame is None:
            log.warning("Calibration failed: could not capture frame")
            return False

        from ttr_bot.vision.template_matcher import calibrate_scale

        scale = calibrate_scale(frame)
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
            with contextlib.suppress(Exception):
                self.on_status_update(msg)

    def _notify_stats(self) -> None:
        if self.on_stats_update:
            with contextlib.suppress(Exception):
                self.on_stats_update(self.stats)

    def _finish(self, reason: str) -> None:
        self._running = False
        log.info(
            "Gardening ended: %s  (planted=%d, watered=%d)",
            reason,
            self.stats.flowers_planted,
            self.stats.waters_done,
        )
        if self.on_gardening_ended:
            with contextlib.suppress(Exception):
                self.on_gardening_ended(reason)
