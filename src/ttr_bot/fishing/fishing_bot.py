"""Fishing bot: cast → wait for bite → repeat.

Assumes the toon is already sitting on a fishing dock with the red
cast button visible.  No sell trips, no walking — just fishing.
"""

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from ttr_bot.config import settings
from ttr_bot.core import cast_input
from ttr_bot.core import input_controller as inp
from ttr_bot.core.bot_base import BotBase
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window, is_window_available
from ttr_bot.fishing import bite_detector, fishing_debug
from ttr_bot.fishing.bite_detector import BiteResult, CastOutcome
from ttr_bot.utils import debug_frames as dbg
from ttr_bot.utils.logger import log
from ttr_bot.vision.color_matcher import average_water_brightness, build_water_mask
from ttr_bot.vision.fish_detector import detect_fish_shadows, find_best_fish
from ttr_bot.vision.pond_detector import PondArea, detect_pond


@dataclass(slots=True)
class FishingStats:
    """Running counters for a single fishing session."""

    casts: int = 0
    caught: int = 0
    missed: int = 0
    skipped: int = 0


@dataclass(slots=True)
class FishingConfig:
    """User-adjustable parameters for a fishing run."""

    max_casts: int = settings.DEFAULT_CASTS
    bite_timeout: float = settings.BITE_TIMEOUT_S


class FishingBot(BotBase):
    """Simple fishing loop: find button → shadow → cast → bite → repeat."""

    def __init__(self) -> None:
        super().__init__()
        self.stats = FishingStats()
        self.config = FishingConfig()
        self._last_miss_target: tuple[int, int] | None = None

        self.on_stats_update: Callable[[FishingStats], None] | None = None

    def start(self, config: FishingConfig) -> None:
        self.config = config
        self.stats = FishingStats()
        self._last_miss_target = None
        self._start_thread(self._run)

    def stop(self) -> None:
        super().stop()

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
        """Validate window before the cast loop starts."""
        cast_input.reload_cast_params()

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

            if result is CastOutcome.SKIPPED:
                consecutive_skips += 1
                backoff = min(2.0 * consecutive_skips, 10.0)
                self._status(f"No target — waiting {backoff:.0f}s")
                time.sleep(backoff)
            elif result in (CastOutcome.NO_BEANS, CastOutcome.BUCKET_FULL):
                msg = "Out of jellybeans" if result is CastOutcome.NO_BEANS else "Bucket is full"
                self._finish(msg)
                return
            else:
                consecutive_skips = 0

        reason = "User stopped" if self._stop_event.is_set() else "Completed"
        self._finish(reason)

    def _one_cast(self, win: WindowInfo, pond: PondArea, avg_water_bright: int) -> CastOutcome:
        """Execute a single cast cycle."""
        inp.ensure_focused()

        bite_detector.dismiss_blocking_dialog(win)

        btn, frame = bite_detector.find_cast_button(win, self._stop_event)
        if btn is None:
            self.stats.skipped += 1
            self._notify_stats()
            return CastOutcome.SKIPPED

        fresh = capture_window(win)
        if fresh is not None:
            frame = fresh
        candidates = detect_fish_shadows(frame, pond, avg_water_bright)
        shadow = find_best_fish(
            frame,
            pond,
            avg_water_bright,
            avoid=self._last_miss_target,
            candidates=candidates,
        )

        if dbg.is_enabled():
            fishing_debug.save_shadow_debug(frame, btn, pond, candidates, shadow)

        if shadow is None:
            self.stats.skipped += 1
            self._notify_stats()
            return CastOutcome.SKIPPED

        sx, sy = shadow
        log.info("Casting at shadow (%d,%d) btn=(%d,%d)", sx, sy, btn.x, btn.y)
        self._status(f"Casting at ({sx},{sy})")
        cast_input.fishing_cast_at(btn.x, btn.y, sx, sy, window=win)

        self.stats.casts += 1
        self._notify_stats()

        time.sleep(settings.POST_CAST_DELAY_S)

        bite_result = bite_detector.wait_for_bite(
            win, self.config.bite_timeout, self._stop_event
        )

        if dbg.is_enabled():
            fishing_debug.save_bite_debug(win, bite_result.value, self.stats.casts)

        if bite_result is BiteResult.CAUGHT:
            self.stats.caught += 1
            self._last_miss_target = None
            self._status(f"Caught! ({self.stats.caught} total)")
        elif bite_result is BiteResult.JELLYBEAN:
            self._status("Out of jellybeans — dismissing dialog")
            bite_detector.dismiss_blocking_dialog(win)
            return CastOutcome.NO_BEANS
        elif bite_result is BiteResult.BUCKET_FULL:
            self._status("Bucket full — dismissing dialog")
            bite_detector.dismiss_blocking_dialog(win)
            return CastOutcome.BUCKET_FULL
        else:
            self.stats.missed += 1
            self._last_miss_target = (sx, sy)
            self._status("No bite — recasting")
        self._notify_stats()

        time.sleep(settings.BETWEEN_CAST_DELAY_S)
        return CastOutcome.CAST

    # ------------------------------------------------------------------
    # Pond detection (once per session)
    # ------------------------------------------------------------------

    def _detect_pond_once(self, win: WindowInfo) -> tuple[PondArea, int] | None:
        """Capture a frame and detect the pond.

        Returns ``(pond, avg_water_bright)`` or *None* on failure.
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
                    pond.width,
                    pond.height,
                    pond.x,
                    pond.y,
                    avg_bright,
                )
                dbg.save(
                    frame,
                    "pond",
                    annotations=[
                        {
                            "type": "rect",
                            "pt1": (pond.x, pond.y),
                            "pt2": (pond.x + pond.width, pond.y + pond.height),
                            "color": (0, 255, 0),
                        },
                        {
                            "type": "text",
                            "pos": (pond.x, pond.y - 10),
                            "text": f"pond {pond.width}x{pond.height} bright={avg_bright}",
                            "color": (0, 255, 0),
                        },
                    ],
                )
                return pond, avg_bright
            time.sleep(0.5)
        return None

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_stats(self) -> None:
        if self.on_stats_update:
            with contextlib.suppress(Exception):
                self.on_stats_update(self.stats)

    def _finish(self, reason: str) -> None:
        log.info(
            "Fishing ended: %s (casts=%d caught=%d missed=%d skipped=%d)",
            reason,
            self.stats.casts,
            self.stats.caught,
            self.stats.missed,
            self.stats.skipped,
        )
        super()._finish(reason)
