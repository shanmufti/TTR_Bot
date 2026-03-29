"""Fishing bot: cast → wait for bite → repeat.

Assumes the toon is already sitting on a fishing dock with the red
cast button visible.  No sell trips, no walking — just fishing.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window, is_window_available, WindowInfo
from ttr_bot.vision.color_matcher import build_water_mask, average_water_brightness
from ttr_bot.vision.pond_detector import detect_pond, PondArea
from ttr_bot.vision.fish_detector import find_best_fish
from ttr_bot.vision.template_matcher import find_template_fast
from ttr_bot.utils.logger import log


@dataclass
class FishingStats:
    casts: int = 0
    caught: int = 0
    missed: int = 0
    skipped: int = 0


@dataclass
class FishingConfig:
    max_casts: int = settings.DEFAULT_CASTS
    bite_timeout: float = settings.BITE_TIMEOUT_S


class FishingBot:
    """Simple fishing loop: find button → shadow → cast → bite → repeat."""

    def __init__(self) -> None:
        self.stats = FishingStats()
        self.config = FishingConfig()

        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self.on_stats_update: Callable[[FishingStats], None] | None = None
        self.on_status_update: Callable[[str], None] | None = None
        self.on_fishing_ended: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self, config: FishingConfig) -> None:
        if self._running:
            return
        self.config = config
        self.stats = FishingStats()
        self._stop_event.clear()
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        log.info("Fishing %s", "PAUSED" if self._paused else "RESUMED")
        self._status("PAUSED" if self._paused else "RESUMED")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            win = self._preflight()
            if win is None:
                return

            pond_result = self._detect_pond_once(win)
            if pond_result is None:
                self._finish("No pond detected — is toon at dock?")
                return
            pond, avg_water_bright = pond_result

            self._cast_loop(win, pond, avg_water_bright)

        except Exception as exc:
            log.exception("Fishing loop crashed")
            self._finish(f"Error: {exc}")

    def _preflight(self) -> WindowInfo | None:
        """Validate calibration and window before the cast loop starts.

        Returns the WindowInfo on success, or None after calling _finish.
        """
        from ttr_bot.core.cast_calibration import cast_calibration
        if not cast_calibration.is_calibrated:
            cast_calibration.load()
        if not cast_calibration.is_calibrated:
            self._finish("No cast calibration — run Calibrate Cast first")
            return None

        if not is_window_available():
            self._finish("TTR window not found")
            return None

        inp.ensure_focused()
        time.sleep(0.3)

        win = find_ttr_window()
        if win is None:
            self._finish("TTR window not found")
            return None

        self._status("Fishing started")
        return win

    def _wait_if_paused(self) -> None:
        """Block while the bot is paused."""
        while self._paused and not self._stop_event.is_set():
            time.sleep(0.25)

    def _cast_loop(self, win: WindowInfo, pond: PondArea, avg_water_bright: int) -> None:
        """Run the main cast-check-repeat loop until done or stopped."""
        consecutive_skips = 0

        while not self._stop_event.is_set():
            if self.stats.casts >= self.config.max_casts:
                break

            self._wait_if_paused()
            if self._stop_event.is_set():
                break

            result = self._one_cast(win, pond, avg_water_bright)

            if result == "skipped":
                consecutive_skips += 1
                backoff = min(2.0 * consecutive_skips, 10.0)
                self._status(f"No target — waiting {backoff:.0f}s")
                time.sleep(backoff)
            elif result in ("no_beans", "bucket_full"):
                msg = "Out of jellybeans" if result == "no_beans" else "Bucket is full"
                self._finish(msg)
                return
            else:
                consecutive_skips = 0

        reason = "User stopped" if self._stop_event.is_set() else "Completed"
        self._finish(reason)

    def _one_cast(self, win: WindowInfo, pond: PondArea, avg_water_bright: int) -> str:
        """Execute a single cast cycle.

        Returns:
            ``"cast"``        — cast completed (caught or missed)
            ``"skipped"``     — no button or no shadow found
            ``"no_beans"``    — out of jellybeans
            ``"bucket_full"`` — bucket full
        """
        inp.ensure_focused()

        self._dismiss_blocking_dialog(win)

        btn, frame = self._find_cast_button(win)
        if btn is None:
            self.stats.skipped += 1
            self._notify_stats()
            return "skipped"

        fresh = capture_window(win)
        if fresh is not None:
            frame = fresh
        shadow = find_best_fish(frame, pond, avg_water_bright)

        if shadow is None:
            self.stats.skipped += 1
            self._notify_stats()
            return "skipped"

        sx, sy = shadow
        log.info("Casting at shadow (%d,%d) btn=(%d,%d)", sx, sy, btn.x, btn.y)
        self._status(f"Casting at ({sx},{sy})")
        inp.fishing_cast_at(btn.x, btn.y, sx, sy, window=win)

        self.stats.casts += 1
        self._notify_stats()

        time.sleep(settings.POST_CAST_DELAY_S)

        bite_result = self._wait_for_bite(win)

        if bite_result == "caught":
            self.stats.caught += 1
            self._status(f"Caught! ({self.stats.caught} total)")
        elif bite_result == "jellybean":
            self._status("Out of jellybeans — dismissing dialog")
            self._dismiss_blocking_dialog(win)
            return "no_beans"
        elif bite_result == "bucket_full":
            self._status("Bucket full — dismissing dialog")
            self._dismiss_blocking_dialog(win)
            return "bucket_full"
        else:
            self.stats.missed += 1
            self._status("No bite — recasting")
        self._notify_stats()

        time.sleep(settings.BETWEEN_CAST_DELAY_S)
        return "cast"

    # ------------------------------------------------------------------
    # Pond detection (once per session)
    # ------------------------------------------------------------------

    def _detect_pond_once(self, win: WindowInfo) -> tuple[PondArea, int] | None:
        """Capture a frame and detect the pond.

        Returns ``(pond, avg_water_bright)`` or *None* on failure.
        The brightness is cached for the session and passed to shadow/bubble
        detection so it doesn't need to be recomputed every cast.
        """
        for _ in range(5):
            frame = capture_window(win)
            if frame is None:
                time.sleep(0.2)
                continue
            pond = detect_pond(frame)
            if not pond.empty:
                crop = frame[pond.y : pond.y + pond.height, pond.x : pond.x + pond.width]
                water_mask = build_water_mask(crop)
                avg_bright = average_water_brightness(crop, water_mask)
                log.info(
                    "Pond locked: %dx%d at (%d,%d)  water_brightness=%d",
                    pond.width, pond.height, pond.x, pond.y, avg_bright,
                )
                return pond, avg_bright
            time.sleep(0.5)
        return None

    # ------------------------------------------------------------------
    # Find the red cast button (with retries)
    # ------------------------------------------------------------------

    def _find_cast_button(self, win: WindowInfo):
        """Poll for the red fishing button. Returns (MatchResult, frame) or (None, None)."""
        for _ in range(30):
            if self._stop_event.is_set():
                return None, None
            frame = capture_window(win)
            if frame is not None:
                btn = find_template_fast(frame, "red_fishing_button")
                if btn is not None:
                    return btn, frame
            time.sleep(0.1)

        log.warning("Cast button not found after 30 attempts")
        self._status("Cast button not found — is toon at dock?")
        return None, None

    # ------------------------------------------------------------------
    # Bite detection
    # ------------------------------------------------------------------

    @staticmethod
    def _has_catch_popup(frame: np.ndarray) -> bool:
        """Detect the fish-caught popup by its warm-yellow card background.

        Checks the center-top region for the popup's distinctive
        cream/yellow pixels (HSV H=25-35, S=40-90, V>220).
        """
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        roi = hsv[h // 6 : h // 2, w // 4 : 3 * w // 4]
        card = (
            (roi[:, :, 0] >= 25)
            & (roi[:, :, 0] <= 35)
            & (roi[:, :, 1] >= 40)
            & (roi[:, :, 1] <= 90)
            & (roi[:, :, 2] >= 220)
        )
        return np.sum(card) / card.size > 0.05

    def _wait_for_bite(self, win: WindowInfo) -> str:
        """Poll until a popup appears or timeout.

        Check order is optimised: the cheap HSV check runs every poll;
        the more expensive template matches only run every 3rd poll.

        Returns:
            ``"caught"``       — fish-caught popup detected
            ``"jellybean"``    — out-of-jellybeans dialog detected
            ``"bucket_full"``  — bucket-full popup detected
            ``"timeout"``      — nothing happened before deadline
        """
        deadline = time.monotonic() + self.config.bite_timeout
        poll = 0
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return "timeout"

            frame = capture_window(win)
            if frame is None:
                time.sleep(0.05)
                continue

            if self._has_catch_popup(frame):
                return "caught"

            # Template checks are ~3× more expensive than HSV; skip
            # some polls to keep the loop responsive for catch detection.
            if poll % 3 == 0:
                if find_template_fast(frame, "jellybean_exit") is not None:
                    return "jellybean"
                if find_template_fast(frame, "ok_button") is not None:
                    return "bucket_full"

            poll += 1
            time.sleep(settings.BITE_POLL_INTERVAL_S)
        return "timeout"

    # ------------------------------------------------------------------
    # Dialog dismissal
    # ------------------------------------------------------------------

    def _dismiss_blocking_dialog(self, win: WindowInfo) -> None:
        """Click away any blocking dialog (jellybean / bucket-full / catch popup).

        Tries up to 8 times, looking for known dismiss buttons.
        """
        for _ in range(8):
            frame = capture_window(win)
            if frame is None:
                time.sleep(0.2)
                continue

            target = (
                find_template_fast(frame, "jellybean_exit")
                or find_template_fast(frame, "ok_button")
                or find_template_fast(frame, "fish_popup_close")
            )
            if target is None:
                return

            log.info("Dismissing dialog: clicking (%d,%d)", target.x, target.y)
            inp.ensure_focused()
            time.sleep(0.1)
            inp.click(target.x, target.y, window=win)
            time.sleep(0.5)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_stats(self) -> None:
        if self.on_stats_update:
            try:
                self.on_stats_update(self.stats)
            except Exception:
                pass

    def _status(self, msg: str) -> None:
        log.info(msg)
        if self.on_status_update:
            try:
                self.on_status_update(msg)
            except Exception:
                pass

    def _finish(self, reason: str) -> None:
        self._running = False
        log.info(
            "Fishing ended: %s (casts=%d caught=%d missed=%d skipped=%d)",
            reason, self.stats.casts, self.stats.caught,
            self.stats.missed, self.stats.skipped,
        )
        if self.on_fishing_ended:
            try:
                self.on_fishing_ended(reason)
            except Exception:
                pass
