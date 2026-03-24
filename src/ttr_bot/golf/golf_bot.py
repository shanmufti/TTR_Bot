"""Orchestrates golf: auto course detection + JSON action replay."""

from __future__ import annotations

import threading
import time
from typing import Callable

from ttr_bot.config import settings
from ttr_bot.golf.action_player import perform_golf_actions
from ttr_bot.golf.detector import (
    action_file_exists,
    path_for_stem,
    wait_for_course_detection,
    wait_until_ready_to_swing,
)
from ttr_bot.utils.logger import log


class GolfBot:
    """Background golf automation (same threading style as GardenBot / FishingBot)."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

        self.on_status_update: Callable[[str], None] | None = None
        self.on_golf_ended: Callable[[str], None] | None = None

        # Set by UI for auto mode when manual course pick is needed
        self.on_need_manual_course: Callable[[list[str]], str | None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._stop_event.set()

    def start_custom_file(self, file_path: str) -> None:
        """Replay a single JSON file."""
        self._stop_event.clear()

        def _work() -> None:
            self._running = True
            try:
                self._emit("Starting custom golf actions…")
                perform_golf_actions(file_path, self._stop_event)
                reason = "cancelled" if self._stop_event.is_set() else "completed"
                self._emit_done(reason)
            finally:
                self._running = False

        self._thread = threading.Thread(target=_work, daemon=True)
        self._thread.start()

    def start_auto_round(self, holes: int = 3) -> None:
        """Detect course each hole, wait for turn, execute matching JSON."""
        self._stop_event.clear()

        def _work() -> None:
            self._running = True
            try:
                self._run_continuous(holes)
            finally:
                self._running = False
                if not self._stop_event.is_set():
                    self._emit_done("completed")
                else:
                    self._emit_done("cancelled")

        self._thread = threading.Thread(target=_work, daemon=True)
        self._thread.start()

    def _emit(self, msg: str) -> None:
        log.info("Golf: %s", msg)
        if self.on_status_update:
            self.on_status_update(msg)

    def _emit_done(self, reason: str) -> None:
        if self.on_golf_ended:
            self.on_golf_ended(reason)

    def _run_continuous(self, holes_per_round: int) -> None:
        holes_played = 0
        last_stem: str | None = None

        while holes_played < holes_per_round and not self._stop_event.is_set():
            self._emit(f"Scanning for course (hole {holes_played + 1}/{holes_per_round})…")

            manual = self.on_need_manual_course

            def _wait_manual(options: list[str]) -> str | None:
                if manual:
                    return manual(options)
                self._emit("No course detected — add pytesseract+tesseract, templates, or JSON files.")
                return None

            stem = wait_for_course_detection(
                self._stop_event.is_set,
                scan_interval_s=settings.GOLF_SCAN_INTERVAL_S,
                max_scoreboard_attempts=3,
                on_need_manual=_wait_manual,
            )

            if self._stop_event.is_set():
                break
            if not stem:
                continue

            if stem == last_stem:
                log.info("Golf: same course as last hole, waiting…")
                self._emit("Waiting for next hole to load…")
                time.sleep(2.0)
                continue

            if not action_file_exists(stem):
                self._emit(f"No action file for: {stem}.json — add it under golf_actions/")
                time.sleep(2.0)
                continue

            self._emit(f"Detected: {stem} — waiting for your turn…")
            wait_until_ready_to_swing(self._stop_event.is_set, interval_s=0.5)
            if self._stop_event.is_set():
                break

            time.sleep(settings.GOLF_PRE_SWING_DELAY_S)

            path = path_for_stem(stem)
            self._emit(f"Playing {stem}…")
            perform_golf_actions(path, self._stop_event)
            if self._stop_event.is_set():
                break

            holes_played += 1
            last_stem = stem
            self._emit(f"Hole {holes_played}/{holes_per_round} done.")

            if holes_played < holes_per_round:
                self._emit("Waiting for next hole…")
                time.sleep(settings.GOLF_BETWEEN_HOLES_DELAY_S)

        if self._stop_event.is_set():
            self._emit("Golf stopped.")
        else:
            self._emit("Round complete.")
