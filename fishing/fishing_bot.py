"""Main fishing loop: cast → wait for bite → catch → repeat.

Ported from FishingStrategyBase.cs + FishingService.cs in the reference bot.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from config import settings
from core import input_controller as inp
from core.screen_capture import capture_window
from core.window_manager import find_ttr_window, is_window_available, WindowInfo
from vision.pond_detector import detect_pond, PondArea
from vision.fish_detector import find_best_fish
from vision.template_matcher import find_template, is_element_visible, calibrate_scale, clear_cache
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

    _MSG_NO_JELLYBEANS = "Out of jellybeans – selling fish"

    def __init__(self) -> None:
        self.stats = FishingStats()
        self.config = FishingConfig()

        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_reason: str | None = None
        self._jellybean_error = False
        self._jellybean_triggered = False

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
            time.sleep(0.5)

            win = find_ttr_window()
            if win is None:
                self._finish("TTR window not found")
                return

            clear_cache()
            frame = capture_window(win)
            if frame is not None:
                calibrate_scale(frame)
            else:
                log.warning("Could not capture frame for scale calibration")

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
                    sells_remaining = 0
                else:
                    log.info("Pre-sell delay (1.0s)…")
                    time.sleep(1.0)
                    self._notify_status("Selling fish…")
                    t_sell = time.monotonic()
                    self._sell_fish(cfg.location, cfg.sell_path_file)
                    log.info("Sell trip took %.1fs", time.monotonic() - t_sell)
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
        no_button_streak = 0

        win = find_ttr_window()
        if win is None:
            self._stop_reason = "TTR window lost"
            return False

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

            inp.ensure_focused()

            self.stats.cast_count += 1
            self.stats.session_casts += 1
            self._notify_stats()

            t0 = time.monotonic()
            cast_ok, frame = self._do_cast(win, pond, cfg)
            log.info("_do_cast took %.1fs", time.monotonic() - t0)
            if not cast_ok:
                no_button_streak += 1
                if no_button_streak >= 10:
                    self._stop_reason = "Red fishing button not found (10 retries)"
                    break
                log.info("Cast button not found (retry %d) – waiting 2s…", no_button_streak)
                self.stats.cast_count -= 1
                self.stats.session_casts -= 1
                time.sleep(2.0)
                continue
            no_button_streak = 0

            log.info("Jellybean check (0.4s wait)…")
            time.sleep(0.4)
            frame = capture_window(win)
            if frame is not None:
                no_jb = self._check_no_jellybeans(win, frame)
                if no_jb:
                    log.info(self._MSG_NO_JELLYBEANS)
                    self._notify_status(self._MSG_NO_JELLYBEANS)
                    self._exit_fishing()
                    return True

            log.info("Post-cast delay (%.1fs)…", settings.POST_CAST_DELAY_S)
            time.sleep(settings.POST_CAST_DELAY_S)

            cast_label = f"cast {cfg.casts_per_round - casts_left + 1}/{cfg.casts_per_round}"
            self._notify_status(f"Waiting for bite… ({cast_label})")

            t1 = time.monotonic()
            caught = self._wait_for_bite(win, cfg.bite_timeout)
            log.info("Bite wait took %.1fs (caught=%s)", time.monotonic() - t1, caught)

            if self._jellybean_error:
                log.info(self._MSG_NO_JELLYBEANS)
                self._notify_status(self._MSG_NO_JELLYBEANS)
                self._dismiss_jellybean_dialog(win)
                self._jellybean_triggered = True
                return True

            if caught:
                self.stats.fish_caught += 1
                self.stats.session_fish += 1
                self._notify_stats()
                self._notify_status("Fish caught!")
                t2 = time.monotonic()
                self._close_catch_popup(win)
                log.info("Close popup took %.1fs", time.monotonic() - t2)

                time.sleep(0.3)
                frame = capture_window(win)
                if frame is not None and is_element_visible(frame, "bucket_full_popup"):
                    log.info("Bucket full!")
                    self._notify_status("Bucket full – selling fish")
                    self._close_bucket_full_popup(win)
                    return True

                casts_left -= 1
            else:
                self._notify_status("No bite – recasting")

            log.info("Between-cast delay (%.1fs)…", settings.BETWEEN_CAST_DELAY_S)
            time.sleep(settings.BETWEEN_CAST_DELAY_S)

        return False

    # ------------------------------------------------------------------
    # Casting
    # ------------------------------------------------------------------

    def _do_cast(
        self, win: WindowInfo, pond: PondArea, cfg: FishingConfig,
    ) -> tuple[bool, "np.ndarray | None"]:
        """Find the red button, aim at a fish shadow, and cast.

        Returns (success, frame) so the caller can reuse the last frame.
        """
        btn = None
        frame = None
        for _ in range(20):
            frame = capture_window(win)
            if frame is not None:
                btn = find_template(frame, "red_fishing_button")
                if btn is not None:
                    break
            time.sleep(0.2)

        if btn is None or frame is None:
            log.warning("Red fishing button not found – is toon at dock?")
            return False, frame

        if not pond.empty:
            fish_pos = find_best_fish(frame, pond)
            if fish_pos is not None:
                fx, fy = fish_pos
                self._notify_status(f"Casting at shadow ({fx},{fy})")
                inp.fishing_cast_at(
                    btn.x, btn.y, fx, fy,
                    pond.x, pond.y, pond.width, pond.height,
                    window=win,
                )
                return True, frame

        self._notify_status("No shadow – random cast")
        inp.fishing_cast(btn.x, btn.y, variance=cfg.variance, window=win)
        return True, frame

    # ------------------------------------------------------------------
    # Bite detection
    # ------------------------------------------------------------------

    def _wait_for_bite(self, win: WindowInfo, timeout: float) -> bool:
        """Poll until the fish-caught popup appears.

        Uses wall-clock time for the timeout (accounts for slow template
        matching on Retina frames).
        Returns True if a catch was detected, False on timeout or
        jellybean error (which sets _jellybean_error flag).
        """
        self._jellybean_error = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False

            frame = capture_window(win)
            if frame is None:
                time.sleep(0.05)
                continue

            if find_template(frame, "jellybean_exit") is not None:
                self._jellybean_error = True
                return False

            if is_element_visible(frame, "fish_popup_close"):
                return True

            time.sleep(settings.BITE_POLL_INTERVAL_S)

        return False

    # ------------------------------------------------------------------
    # Popup handling
    # ------------------------------------------------------------------

    def _check_no_jellybeans(self, win: WindowInfo, frame) -> bool:
        """Detect the 'not enough jellybeans' dialog.

        Uses the jellybean_exit template (red X + "Exit" label) which is
        unique to error dialogs. The fish catch popup has a similar X
        button but without the "Exit" label.
        """
        jb = find_template(frame, "jellybean_exit")
        if jb is not None:
            inp.click(jb.x, jb.y, window=win)
            time.sleep(0.3)
            return True

        ok = find_template(frame, "ok_button")
        if ok is not None:
            inp.click(ok.x, ok.y, window=win)
            time.sleep(0.3)
            return True

        return False

    def _dismiss_jellybean_dialog(self, win: WindowInfo) -> None:
        """Click the Exit button on the no-jellybeans dialog."""
        for _ in range(8):
            frame = capture_window(win)
            if frame is None:
                time.sleep(0.2)
                continue
            jb = find_template(frame, "jellybean_exit")
            if jb is None:
                close = find_template(frame, "fish_popup_close")
                if close is not None:
                    inp.ensure_focused()
                    time.sleep(0.1)
                    inp.click(close.x, close.y, window=win)
                    time.sleep(0.5)
                    continue
                return
            inp.ensure_focused()
            time.sleep(0.1)
            inp.click(jb.x, jb.y, window=win)
            time.sleep(0.5)

    def _close_catch_popup(self, win: WindowInfo) -> None:
        """Close the fish-caught popup by clicking its close button.

        Re-detects the button position each attempt to handle UI shifts
        from in-game events (e.g. Bingo card).
        """
        for _ in range(8):
            frame = capture_window(win)
            if frame is None:
                time.sleep(0.2)
                continue
            match = find_template(frame, "fish_popup_close")
            if match is None:
                return
            inp.ensure_focused()
            time.sleep(0.1)
            inp.click(match.x, match.y, window=win)
            time.sleep(0.5)
        log.warning("Could not close fish popup after retries")

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
