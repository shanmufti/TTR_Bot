"""Execute the garden sweep routine in a background thread.

The actual planting logic (pick existing flower, plant new one, water)
is handled by GardenBot.  This module wires up the sweeper, validates
the flower selection, and relays progress / status to the UI.
"""

from __future__ import annotations

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


class RoutineRunner:
    """Runs the garden sweep in a background thread."""

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

    def start_sweep(
        self,
        default_flower: str = "",
        target_beds: int = 0,
        max_laps: int = 0,
    ) -> None:
        """Run a garden sweep: walk toward visible flowers and interact."""
        if self._running:
            log.warning("Routine already running")
            return

        self._default_flower = default_flower
        self._stop_event.clear()
        self._bot.reset()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_sweep,
            args=(target_beds, max_laps),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._bot.stop()
        self._running = False
        self._release_all_keys()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_sweep(self, target_beds: int, max_laps: int) -> None:
        from ttr_bot.gardening.garden_sweeper import GardenSweeper

        try:
            flower, beans = self._validate_flower()
            if flower is None:
                return

            sweeper = GardenSweeper(self._bot, self._stop_event)
            sweeper.on_status = lambda msg: self._notify_status(msg)

            result = sweeper.sweep(
                flower, beans,
                target_beds=target_beds,
                max_laps=max_laps,
            )

            progress = RoutineProgress(
                current_bed=result.beds_visited,
                total_beds=target_beds or settings.SWEEP_TARGET_BEDS,
                flowers_planted=result.beds_planted,
                status=result.reason,
            )
            self._notify_progress(progress)
            self._finish(result.reason)

        except Exception as exc:
            log.exception("Sweep routine crashed")
            self._finish(f"Error: {exc}")

    def _validate_flower(self) -> tuple[str | None, str | None]:
        flower = self._default_flower
        if not flower:
            self._finish("No flower selected — pick one in the UI")
            return (None, None)
        info = lookup_flower(flower)
        if info is None:
            self._finish(f"Unknown flower: {flower}")
            return (None, None)
        return (flower, info[1])

    @staticmethod
    def _release_all_keys() -> None:
        try:
            inp.ensure_focused()
        except Exception:
            pass
        for k in ("up", "down", "left", "right"):
            try:
                pyautogui.keyUp(k)
            except Exception:
                pass

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
