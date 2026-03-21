"""Main fishing loop: cast → wait for bite → catch → repeat.

Ported from FishingStrategyBase.cs + FishingService.cs in the reference bot.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable

from config import settings
from core import input_controller as inp
from core.screen_capture import capture_window
from core.window_manager import find_ttr_window, is_window_available, WindowInfo
from vision.pond_detector import detect_pond, PondArea
from vision.fish_detector import find_best_fish
from vision.template_matcher import find_template, is_element_visible
from utils.logger import log


@dataclass
class FishingStats:
    cast_count: int = 0
    fish_caught: int = 0
    session_casts: int = 0
    session_fish: int = 0
    current_round: int = 0
    total_rounds: int = 0


@dataclass
class FishingConfig:
    location: str = "Fish Anywhere"
    casts_per_round: int = settings.DEFAULT_CASTS
    sell_rounds: int = settings.DEFAULT_SELL_ROUNDS
    variance: int = settings.DEFAULT_VARIANCE
    auto_detect: bool = False
    quick_cast: bool = False
    bite_timeout: float = settings.BITE_TIMEOUT_S
    sell_path_file: str | None = None  # path to recorded sell-path JSON


class FishingBot:
    """Controls the complete fishing automation loop."""

    def __init__(self) -> None:
        self.stats = FishingStats()
        self.config = FishingConfig()

        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_reason: str | None = None

        # Callbacks for UI updates
        self.on_stats_update: Callable[[FishingStats], None] | None = None
        self.on_status_update: Callable[[str], None] | None = None
        self.on_fishing_ended: Callable[[str], None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self, config: FishingConfig) -> None:
        """Start fishing in a background thread."""
        if self._running:
            log.warning("Fishing already running")
            return
        self.config = config
        self.stats = FishingStats(total_rounds=config.sell_rounds)
        self._stop_event.clear()
        self._stop_reason = None
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the fishing loop to stop."""
        self._stop_event.set()
        self._running = False

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        state = "PAUSED" if self._paused else "RESUMED"
        log.info("Fishing %s", state)
        self._notify_status(state)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main fishing session loop (runs in a background thread)."""
        try:
            if not is_window_available():
                self._finish("TTR window not found")
                return

            inp.ensure_focused()
            time.sleep(1.0)

            cfg = self.config
            sells_remaining = cfg.sell_rounds
            is_first_cycle = True

            while sells_remaining > 0 and not self._stop_event.is_set():
                self.stats.current_round = cfg.sell_rounds - sells_remaining + 1
                self._notify_stats()

                if not is_first_cycle:
                    self._notify_status("Settling at dock…")
                    time.sleep(settings.SELL_WALK_DELAY_S)

                self._notify_status("Fishing…")
                bucket_full = self._fishing_round(cfg, is_first_cycle)
                is_first_cycle = False

                if self._stop_event.is_set():
                    break
                if self._stop_reason:
                    break

                if cfg.location == "Fish Anywhere":
                    self._exit_fishing()
                    sells_remaining = 0
                else:
                    # Exit the dock UI (bucket-full already dismissed the
                    # popup and kicked us off the dock, so skip exit in
                    # that case).
                    if not bucket_full:
                        self._exit_fishing()
                    time.sleep(0.5)

                    # Sell fish — always run this so we empty the bucket
                    self._notify_status("Selling fish…")
                    self._sell_fish(cfg.location, cfg.sell_path_file)
                    sells_remaining -= 1

            reason = (
                "User stopped"
                if self._stop_event.is_set()
                else self._stop_reason or "Completed all rounds"
            )
            self._finish(reason)

        except Exception as exc:
            log.exception("Fishing loop crashed")
            self._finish(f"Error: {exc}")

    def _fishing_round(self, cfg: FishingConfig, _is_first: bool) -> bool:
        """Execute one round of casts. Returns True if bucket became full."""
        self.stats.cast_count = 0
        self.stats.fish_caught = 0
        casts_left = cfg.casts_per_round

        win = find_ttr_window()
        if win is None:
            self._stop_reason = "TTR window lost"
            return False

        # Detect pond once per round
        frame = capture_window(win)
        if frame is None:
            self._stop_reason = "Screen capture failed"
            return False
        pond = detect_pond(frame)

        while casts_left > 0 and not self._stop_event.is_set():
            while self._paused and not self._stop_event.is_set():
                time.sleep(0.25)
            if self._stop_event.is_set():
                break

            self.stats.cast_count += 1
            self.stats.session_casts += 1
            self._notify_stats()

            # Cast
            cast_ok = self._do_cast(win, pond, cfg)
            if not cast_ok:
                break

            # Brief pause for "no jellybeans" popup
            time.sleep(0.3)

            # Wait for cast animation
            delay = (
                settings.POST_CAST_DELAY_QUICK_S
                if cfg.quick_cast
                else settings.POST_CAST_DELAY_S
            )
            time.sleep(delay)

            self._notify_status(f"Waiting for bite… (cast {cfg.casts_per_round - casts_left + 1}/{cfg.casts_per_round})")

            # Poll for bite
            caught = self._wait_for_bite(win, cfg.bite_timeout)

            if caught:
                self.stats.fish_caught += 1
                self.stats.session_fish += 1
                self._notify_stats()
                self._notify_status("Fish caught!")
                time.sleep(settings.POST_CATCH_DELAY_S)
                self._close_catch_popup(win)
            else:
                # Check for bucket full
                frame = capture_window(win)
                if frame is not None and is_element_visible(frame, "bucket_full_popup"):
                    log.info("Bucket full!")
                    self._notify_status("Bucket full – selling fish")
                    self._close_bucket_full_popup(win)
                    return True
                self._notify_status("No bite (timeout)")

            casts_left -= 1
            time.sleep(settings.BETWEEN_CAST_DELAY_S)

        return False

    # ------------------------------------------------------------------
    # Casting
    # ------------------------------------------------------------------

    def _do_cast(self, win: WindowInfo, pond: PondArea, cfg: FishingConfig) -> bool:
        """Find the red button, optionally detect fish, and cast."""
        frame = capture_window(win)
        if frame is None:
            self._stop_reason = "Screen capture failed"
            return False

        btn = find_template(frame, "red_fishing_button")
        if btn is None:
            log.warning("Red fishing button not found – is toon at dock?")
            self._stop_reason = "Red fishing button not found"
            return False

        if cfg.auto_detect and not pond.empty:
            fish_pos = find_best_fish(frame, pond)
            if fish_pos is not None:
                fx, fy = fish_pos
                log.info("Auto-detect: casting at fish (%d, %d)", fx, fy)
                self._notify_status(f"Fish detected at ({fx},{fy}) – casting")
                inp.fishing_cast_at(btn.x, btn.y, fx, fy, window=win)
                return True

        self._notify_status("Casting…")
        inp.fishing_cast(btn.x, btn.y, variance=cfg.variance, window=win)
        return True

    # ------------------------------------------------------------------
    # Bite detection
    # ------------------------------------------------------------------

    def _wait_for_bite(self, win: WindowInfo, timeout: float) -> bool:
        """Poll until the red fishing button disappears (= fish caught).

        Returns True if a bite was detected within the timeout.
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self._stop_event.is_set():
                return False

            frame = capture_window(win)
            if frame is None:
                continue

            if not is_element_visible(frame, "red_fishing_button"):
                return True

            time.sleep(settings.BITE_POLL_INTERVAL_S)

        return False

    # ------------------------------------------------------------------
    # Popup handling
    # ------------------------------------------------------------------

    def _close_catch_popup(self, win: WindowInfo) -> None:
        """Close the fish-caught popup by clicking its close button."""
        for _ in range(10):
            frame = capture_window(win)
            if frame is None:
                break
            match = find_template(frame, "fish_popup_close")
            if match is not None:
                inp.click(match.x, match.y, window=win)
                time.sleep(0.3)
                return
            time.sleep(0.2)
        log.warning("Could not find fish popup close button")

    def _close_bucket_full_popup(self, win: WindowInfo) -> None:
        """Dismiss the 'bucket full' popup via OK button."""
        for _ in range(10):
            frame = capture_window(win)
            if frame is None:
                break
            match = find_template(frame, "ok_button")
            if match is not None:
                inp.click(match.x, match.y, window=win)
                time.sleep(0.5)
                return
            time.sleep(0.2)
        log.warning("Could not find OK button for bucket full popup")

    def _exit_fishing(self) -> None:
        """Click the Exit Fishing button to leave the dock."""
        win = find_ttr_window()
        if win is None:
            return
        for _ in range(10):
            frame = capture_window(win)
            if frame is None:
                break
            match = find_template(frame, "exit_fishing_button")
            if match is not None:
                inp.click(match.x, match.y, window=win)
                time.sleep(1.0)
                return
            time.sleep(0.3)
        log.warning("Could not find exit fishing button")

    def _sell_fish(self, location: str, sell_path_file: str | None = None) -> None:
        """Execute a sell-fish walk sequence for the given location."""
        from fishing.sell_controller import walk_and_sell
        walk_and_sell(location, sell_path_file=sell_path_file)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_stats(self) -> None:
        if self.on_stats_update:
            try:
                self.on_stats_update(self.stats)
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
        log.info(
            "Fishing ended: %s  (casts=%d, fish=%d)",
            reason, self.stats.session_casts, self.stats.session_fish,
        )
        if self.on_fishing_ended:
            try:
                self.on_fishing_ended(reason)
            except Exception:
                pass
