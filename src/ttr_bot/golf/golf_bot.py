"""Orchestrates golf: auto course detection + JSON action replay."""

import threading
import time
from collections.abc import Callable
from time import perf_counter

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
        round_t0 = perf_counter()

        while holes_played < holes_per_round and not self._stop_event.is_set():
            hole_num = holes_played + 1
            hole_t0 = perf_counter()
            log.info(
                "Golf [auto %d/%d] — start hole (round +%.1fs)",
                hole_num,
                holes_per_round,
                perf_counter() - round_t0,
            )
            self._emit(f"Hole {hole_num}/{holes_per_round}…")

            def _wait_manual(
                options: list[str],
                _cb=self.on_need_manual_course,
            ) -> str | None:
                if _cb:
                    return _cb(options)
                self._emit(
                    "No course detected — add pytesseract+tesseract, templates, or JSON files."
                )
                return None

            # After hole 1+, wait until the turn timer appears *before* opening the scoreboard.
            # Otherwise OCR still reads the previous hole's course name and we would stall forever
            # on "same course as last hole" or play the wrong JSON.
            if holes_played > 0:
                self._emit("Step: wait for turn (before scoreboard)…")
                wait_until_ready_to_swing(
                    self._stop_event.is_set, interval_s=0.5, phase="pre_scoreboard"
                )
                if self._stop_event.is_set():
                    break

            self._emit("Step: detect course via scoreboard…")
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
                holes_per_round,
                perf_counter() - t0,
                stem or "None",
            )

            if self._stop_event.is_set():
                break
            if not stem:
                log.warning(
                    "Golf [auto %d/%d] — no stem; retrying loop (+%.1fs in hole)",
                    hole_num,
                    holes_per_round,
                    perf_counter() - hole_t0,
                )
                continue

            if not action_file_exists(stem):
                self._emit(f"No action file for: {stem}.json — add it under golf_actions/")
                time.sleep(2.0)
                continue

            self._emit("Step: wait for turn (before swing)…")
            wait_until_ready_to_swing(self._stop_event.is_set, interval_s=0.5, phase="pre_swing")
            if self._stop_event.is_set():
                break

            log.info(
                "Golf [auto %d/%d] — pre-swing delay %.1fs",
                hole_num,
                holes_per_round,
                settings.GOLF_PRE_SWING_DELAY_S,
            )
            time.sleep(settings.GOLF_PRE_SWING_DELAY_S)

            path = path_for_stem(stem)
            self._emit(f"Step: replay JSON — {stem}")
            t_play = perf_counter()
            perform_golf_actions(path, self._stop_event)
            log.info(
                "Golf [auto %d/%d] — replay finished in %.1fs (file=%s)",
                hole_num,
                holes_per_round,
                perf_counter() - t_play,
                path,
            )
            if self._stop_event.is_set():
                break

            holes_played += 1
            self._emit(f"Hole {holes_played}/{holes_per_round} done.")
            log.info(
                "Golf [auto %d/%d] — hole complete in %.1fs total",
                holes_played,
                holes_per_round,
                perf_counter() - hole_t0,
            )

            if holes_played < holes_per_round:
                self._emit(
                    f"Step: between-holes sleep {settings.GOLF_BETWEEN_HOLES_DELAY_S:.0f}s…"
                )
                time.sleep(settings.GOLF_BETWEEN_HOLES_DELAY_S)

        if self._stop_event.is_set():
            self._emit("Golf stopped.")
        else:
            self._emit("Round complete.")
        log.info(
            "Golf [auto] — round finished in %.1fs (holes=%d/%d)",
            perf_counter() - round_t0,
            holes_played,
            holes_per_round,
        )
