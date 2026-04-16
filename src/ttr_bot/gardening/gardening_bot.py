"""Core gardening automation: plant flowers and water plants.

GardenBot inherits from BotBase for thread management, pause/resume,
stop signaling, and status/end callbacks.  Planting is delegated to
plant_sequence; template clicking goes through garden_ui_helpers.
"""

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from ttr_bot.config import settings
from ttr_bot.core.bot_base import BotBase
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.gardening.garden_ui_helpers import ensure_calibrated, find_and_click
from ttr_bot.gardening.plant_sequence import execute_plant
from ttr_bot.utils.logger import log
from ttr_bot.vision.template_matcher import is_element_visible


@dataclass(slots=True)
class GardeningStats:
    """Running counters for a gardening session."""

    flowers_planted: int = 0
    waters_done: int = 0
    current_action: str = ""


@dataclass(slots=True)
class GardenAction:
    """A single gardening action for the bot to execute."""

    action: str  # "plant" or "water"
    flower_name: str = ""
    bean_sequence: str = ""
    water_count: int = 1


class GardenBot(BotBase):
    """Controls gardening automation (plant / water) in a background thread."""

    def __init__(self) -> None:
        super().__init__()
        self.stats = GardeningStats()
        self.on_stats_update: Callable[[GardeningStats], None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

    def reset(self) -> None:
        """Reset internal state so the bot can be reused by a routine."""
        self._stop_event.clear()
        self._running = False
        self._paused = False

    # ------------------------------------------------------------------
    # Internal: thread management
    # ------------------------------------------------------------------

    def _start(self, actions: list[GardenAction]) -> None:
        self.stats = GardeningStats()
        self._start_thread(self._run_actions, actions)

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
            self._status(f"{label} Planting {action.flower_name}...")
            self.stats.current_action = f"Planting {action.flower_name}"
            self._notify_stats()
            if not self.plant_flower(action.flower_name, action.bean_sequence):
                return f"Plant failed: {action.flower_name}"
            self.stats.flowers_planted += 1
            self._notify_stats()
        elif action.action == "water":
            self._status(f"{label} Watering x{action.water_count}...")
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
        if not find_and_click("pick_flower_button", stop_event=self._stop_event):
            self._status("Pick button not found")
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
        return execute_plant(
            flower_name,
            bean_sequence,
            self._stop_event,
            status_fn=self._status,
            water_fn=self.water_plant,
        )

    def plant_flower(self, flower_name: str, bean_sequence: str) -> bool:
        """Full plant sequence: auto-detect bed state -> pick if needed -> plant -> water."""
        win = find_ttr_window()
        if win is not None:
            frame = capture_window(win)
            if frame is not None and is_element_visible(frame, "pick_flower_button"):
                self._status(f"Existing flower detected — picking before planting {flower_name}")
                if not find_and_click("pick_flower_button", stop_event=self._stop_event):
                    self._status("Pick button not found")
                    return False
                time.sleep(settings.GARDEN_POST_PICK_DELAY_S)

        return execute_plant(
            flower_name,
            bean_sequence,
            self._stop_event,
            status_fn=self._status,
            water_fn=self.water_plant,
        )

    def water_plant(self, count: int) -> bool:
        """Click the watering can *count* times. Returns False on failure."""
        for i in range(count):
            if self._stop_event.is_set():
                return False
            self._wait_if_paused()

            t0 = time.monotonic()
            if not find_and_click("watering_can_button", stop_event=self._stop_event):
                self._status("Watering can button not found")
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

    def ensure_calibrated(self) -> bool:
        """Verify scale calibration is set, running it if needed."""
        return ensure_calibrated(status_fn=self._status)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_stats(self) -> None:
        if self.on_stats_update:
            with contextlib.suppress(Exception):
                self.on_stats_update(self.stats)

    def _finish(self, reason: str) -> None:
        log.info(
            "Gardening ended: %s  (planted=%d, watered=%d)",
            reason,
            self.stats.flowers_planted,
            self.stats.waters_done,
        )
        super()._finish(reason)
