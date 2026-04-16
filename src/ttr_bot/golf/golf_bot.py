"""Orchestrates golf: auto course detection + JSON action replay."""

import time
from collections.abc import Callable
from time import perf_counter

from ttr_bot.config import settings
from ttr_bot.core.bot_base import BotBase
from ttr_bot.golf.action_files import action_file_exists, path_for_stem
from ttr_bot.golf.action_player import perform_golf_actions
from ttr_bot.golf.course_detector import wait_for_course_detection
from ttr_bot.golf.swing_detector import wait_until_ready_to_swing
from ttr_bot.utils.logger import log


class GolfBot(BotBase):
    """Background golf automation (same threading style as GardenBot / FishingBot)."""

    def __init__(self) -> None:
        super().__init__()
        self.on_need_manual_course: Callable[[list[str]], str | None] | None = None

    def stop(self) -> None:
        super().stop()

    def start_custom_file(self, file_path: str) -> None:
        """Replay a single JSON file."""

        def _work() -> None:
            try:
                self._status("Starting custom golf actions…")
                perform_golf_actions(file_path, self._stop_event)
                reason = "cancelled" if self._stop_event.is_set() else "completed"
                self._finish(reason)
            finally:
                self._running = False

        self._start_thread(_work)

    def start_auto_round(self, holes: int = 3) -> None:
        """Detect course each hole, wait for turn, execute matching JSON."""

        def _work() -> None:
            try:
                self._run_continuous(holes)
            finally:
                if not self._stop_event.is_set():
                    self._finish("completed")
                else:
                    self._finish("cancelled")
                self._running = False

        self._start_thread(_work)

    def _run_continuous(self, holes_per_round: int) -> None:
        holes_played = 0
        round_t0 = perf_counter()

        while holes_played < holes_per_round and not self._stop_event.is_set():
            hole_num = holes_played + 1
            self._status(f"Hole {hole_num}/{holes_per_round}…")

            played = self._play_hole(hole_num, holes_per_round, is_first=(holes_played == 0))
            if self._stop_event.is_set():
                break
            if not played:
                continue

            holes_played += 1
            self._status(f"Hole {holes_played}/{holes_per_round} done.")

            if holes_played < holes_per_round:
                self._status(
                    f"Step: between-holes sleep {settings.GOLF_BETWEEN_HOLES_DELAY_S:.0f}s…"
                )
                time.sleep(settings.GOLF_BETWEEN_HOLES_DELAY_S)

        self._status("Golf stopped." if self._stop_event.is_set() else "Round complete.")
        log.info(
            "Golf [auto] — round finished in %.1fs (holes=%d/%d)",
            perf_counter() - round_t0,
            holes_played,
            holes_per_round,
        )

    def _play_hole(self, hole_num: int, total_holes: int, *, is_first: bool) -> bool:
        """Detect course, wait for turn, and replay the JSON for one hole.

        Returns True if the hole was played, False to retry detection.
        """
        hole_t0 = perf_counter()

        if not is_first:
            self._status("Step: wait for turn (before scoreboard)…")
            wait_until_ready_to_swing(
                self._stop_event.is_set,
                interval_s=0.5,
                phase="pre_scoreboard",
            )
            if self._stop_event.is_set():
                return False

        stem = self._detect_course(hole_num, total_holes)
        if self._stop_event.is_set():
            return False
        if not stem:
            log.warning(
                "Golf [auto %d/%d] — no stem; retrying (+%.1fs)",
                hole_num,
                total_holes,
                perf_counter() - hole_t0,
            )
            return False

        if not action_file_exists(stem):
            self._status(f"No action file for: {stem}.json — add it under golf_actions/")
            time.sleep(2.0)
            return False

        self._status("Step: wait for turn (before swing)…")
        wait_until_ready_to_swing(self._stop_event.is_set, interval_s=0.5, phase="pre_swing")
        if self._stop_event.is_set():
            return False

        time.sleep(settings.GOLF_PRE_SWING_DELAY_S)

        path = path_for_stem(stem)
        self._status(f"Step: replay JSON — {stem}")
        t_play = perf_counter()
        perform_golf_actions(path, self._stop_event)
        log.info(
            "Golf [auto %d/%d] — replay finished in %.1fs (file=%s)",
            hole_num,
            total_holes,
            perf_counter() - t_play,
            path,
        )
        log.info(
            "Golf [auto %d/%d] — hole complete in %.1fs total",
            hole_num,
            total_holes,
            perf_counter() - hole_t0,
        )
        return not self._stop_event.is_set()

    def _detect_course(self, hole_num: int, total_holes: int) -> str | None:
        """Open the scoreboard and OCR the course name."""

        def _wait_manual(
            options: list[str],
            _cb: Callable[[list[str]], str | None] | None = self.on_need_manual_course,
        ) -> str | None:
            if _cb:
                return _cb(options)
            self._status(
                "No course detected — add pytesseract+tesseract, templates, or JSON files."
            )
            return None

        self._status("Step: detect course via scoreboard…")
        t0 = perf_counter()
        stem = wait_for_course_detection(
            self._stop_event.is_set,
            scan_interval_s=settings.GOLF_SCAN_INTERVAL_S,
            max_scoreboard_attempts=3,
            on_need_manual=_wait_manual,
        )
        log.info(
            "Golf [auto %d/%d] — course detection finished in %.1fs (stem=%s)",
            hole_num,
            total_holes,
            perf_counter() - t0,
            stem or "None",
        )
        return stem
