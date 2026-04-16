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
from ttr_bot.vision.fish_detector import find_best_fish, detect_fish_shadows
from ttr_bot.vision.template_matcher import find_template
from ttr_bot.utils import debug_frames as dbg
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
        self._last_miss_target: tuple[int, int] | None = None

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
        self._last_miss_target = None
        self._stop_event.clear()
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._running = False
        self._thread = None

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        log.info("Fishing %s", "PAUSED" if self._paused else "RESUMED")
        self._status("PAUSED" if self._paused else "RESUMED")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        dbg._reset_session()
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
        """Validate window before the cast loop starts.

        Returns the WindowInfo on success, or None after calling _finish.
        """

        inp.reload_cast_params()

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

    def _save_shadow_debug(self, frame, btn, pond, candidates, shadow) -> None:
        """Save an annotated debug frame showing shadow candidates and cast target."""
        margin_bot = pond.height * 40 // 100
        margin_top = pond.height * 10 // 100
        margin_x = pond.width * 10 // 100
        inner_y1 = pond.y + margin_top
        inner_y2 = pond.y + pond.height - margin_bot
        inner_x1 = pond.x + margin_x
        inner_x2 = pond.x + pond.width - margin_x

        anns: list[dict] = [
            {"type": "rect",
             "pt1": (pond.x, pond.y),
             "pt2": (pond.x + pond.width, pond.y + pond.height),
             "color": (100, 100, 100), "thickness": 1},
            {"type": "rect",
             "pt1": (inner_x1, inner_y1),
             "pt2": (inner_x2, inner_y2),
             "color": (0, 200, 200), "thickness": 2},
        ]
        for c in candidates:
            clr = (0, 255, 255) if c.has_bubbles else (0, 165, 255)
            anns.append({"type": "circle", "center": (c.cx, c.cy), "radius": 18,
                         "color": clr, "thickness": 2})
            anns.append({"type": "text", "pos": (c.cx + 20, c.cy - 6),
                         "text": f"s={c.score:.2f} {'B' if c.has_bubbles else ''}",
                         "color": clr, "thickness": 2})
        if shadow is not None:
            anns.append({"type": "circle", "center": shadow, "radius": 24,
                         "color": (0, 255, 0), "thickness": 4})
            anns.append({"type": "line", "pt1": (btn.x, btn.y), "pt2": shadow,
                         "color": (0, 255, 0), "thickness": 2})
        anns.append({"type": "circle", "center": (btn.x, btn.y), "radius": 14,
                     "color": (0, 0, 255), "thickness": 3})
        dbg.save(frame, "cast_target" if shadow else "no_shadow", annotations=anns)

    def _save_bite_debug(self, win: WindowInfo, bite_result: str) -> None:
        """Save a debug frame capturing the bite outcome."""
        bite_frame = capture_window(win)
        if bite_frame is not None:
            dbg.save(bite_frame, f"bite_{bite_result}", annotations=[
                {"type": "text", "pos": (20, 40),
                 "text": f"result={bite_result}  cast#{self.stats.casts}",
                 "color": (0, 255, 0), "thickness": 2},
            ])

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
        candidates = detect_fish_shadows(frame, pond, avg_water_bright)
        shadow = find_best_fish(
            frame, pond, avg_water_bright,
            avoid=self._last_miss_target,
        )

        if dbg.is_enabled():
            self._save_shadow_debug(frame, btn, pond, candidates, shadow)

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

        if dbg.is_enabled():
            self._save_bite_debug(win, bite_result)

        if bite_result == "caught":
            self.stats.caught += 1
            self._last_miss_target = None
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
            self._last_miss_target = (sx, sy)
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
                dbg.save(frame, "pond", annotations=[
                    {"type": "rect",
                     "pt1": (pond.x, pond.y),
                     "pt2": (pond.x + pond.width, pond.y + pond.height),
                     "color": (0, 255, 0)},
                    {"type": "text", "pos": (pond.x, pond.y - 10),
                     "text": f"pond {pond.width}x{pond.height} bright={avg_bright}",
                     "color": (0, 255, 0)},
                ])
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
                btn = find_template(frame, "red_fishing_button", threshold=0.55)
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
                if find_template(frame, "jellybean_exit") is not None:
                    return "jellybean"
                if find_template(frame, "ok_button") is not None:
                    return "bucket_full"

            poll += 1
            time.sleep(settings.BITE_POLL_INTERVAL_S)
        return "timeout"

    # ------------------------------------------------------------------
    # Dialog dismissal
    # ------------------------------------------------------------------

    def _dismiss_blocking_dialog(self, win: WindowInfo) -> None:
        """Click away any blocking dialog (jellybean / bucket-full / catch popup).

        Tries up to 3 times, looking for known dismiss buttons.
        """
        for _ in range(3):
            frame = capture_window(win)
            if frame is None:
                time.sleep(0.2)
                continue

            target = (
                find_template(frame, "jellybean_exit", threshold=0.75)
                or find_template(frame, "ok_button", threshold=0.75)
                or find_template(frame, "fish_popup_close", threshold=0.75)
            )
            if target is None:
                return

            log.info("Dismissing dialog: clicking (%d,%d)", target.x, target.y)
            inp.ensure_focused()
            time.sleep(0.1)
            inp.click(target.x, target.y, window=win)
            time.sleep(1.0)

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
