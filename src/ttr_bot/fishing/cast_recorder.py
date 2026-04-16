"""Passive cast recorder: watches the user fish manually and records samples.

Each sample captures the drag vector (via mouse tracking), the shadow
positions before the cast, and the bobber landing position.  After
recording, fit_cast_params() derives power/aim curve constants.
"""

import contextlib
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pyautogui

from ttr_bot.config import settings
from ttr_bot.core.cast_calibration import detect_bobber
from ttr_bot.core.cast_params import CastParams
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.utils import debug_frames as dbg
from ttr_bot.utils.logger import log
from ttr_bot.vision.color_matcher import average_water_brightness, build_water_mask
from ttr_bot.vision.fish_detector import FishCandidate, detect_fish_shadows
from ttr_bot.vision.pond_detector import PondArea, detect_pond
from ttr_bot.vision.template_matcher import find_template

_RETINA_SCALE = settings.RETINA_SCALE


@dataclass
class CastSample:
    """Raw observation from a single user-performed cast."""

    button_x: int
    button_y: int
    target_x: int
    target_y: int
    bobber_x: int
    bobber_y: int
    drag_dx: float
    drag_dy: float


def _to_screen(win: WindowInfo, wx: int, wy: int) -> tuple[int, int]:
    return win.x + wx // _RETINA_SCALE, win.y + wy // _RETINA_SCALE


class CastRecorder:
    """Passively records manual fishing casts."""

    def __init__(self) -> None:
        self.samples: list[CastSample] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_status: Callable[[str], None] | None = None

    @property
    def recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.recording:
            return
        self.samples.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _status(self, msg: str) -> None:
        log.info("Recorder: %s", msg)
        if self.on_status:
            with contextlib.suppress(Exception):
                self.on_status(msg)

    def _loop(self) -> None:
        from ttr_bot.core.window_manager import set_calibrated_bounds
        from ttr_bot.vision.template_matcher import calibrate_scale, clear_cache

        win = find_ttr_window()
        if win is None:
            self._status("TTR window not found")
            return

        set_calibrated_bounds(win)

        frame = capture_window(win)
        if frame is None:
            self._status("Capture failed")
            return

        clear_cache()
        scale = calibrate_scale(frame)
        if scale < 0:
            self._status("Calibration failed — sit on dock first")
            return

        pond = detect_pond(frame)
        if pond.empty:
            self._status("No pond detected")
            return

        crop = frame[pond.y : pond.y + pond.height, pond.x : pond.x + pond.width]
        wm = build_water_mask(crop)
        avg_bright = average_water_brightness(crop, wm)

        self._status("Recording — fish normally!")

        while not self._stop.is_set():
            sample = self._record_one_cast(win, pond, avg_bright)
            if sample is not None:
                self.samples.append(sample)
                self._status(f"Recorded cast {len(self.samples)}")

        self._status(f"Stopped — {len(self.samples)} casts recorded")

    def _wait_for_cast_start(
        self,
        win: WindowInfo,
        pond: PondArea,
        avg_bright: int,
    ) -> tuple | None:
        """Poll until the user initiates a cast (button disappears).

        Continuously tracks mouse positions alongside button detection so we
        capture the full drag even for fast flick-casts. Returns
        ``(btn_match, btn_screen, drag_vec, shadows, before_frame)`` or None.
        """
        btn_pos = None
        btn_screen: tuple[int, int] | None = None
        shadows: list[FishCandidate] = []
        before_frame = None
        mouse_buf: list[tuple[int, int]] = []
        buf_size = 60

        while not self._stop.is_set():
            frame = capture_window(win)
            if frame is None:
                time.sleep(0.05)
                continue

            cur = pyautogui.position()
            mouse_buf.append((cur[0], cur[1]))
            if len(mouse_buf) > buf_size:
                mouse_buf.pop(0)

            btn = find_template(frame, "red_fishing_button")
            if btn is not None:
                btn_pos = btn
                btn_screen = _to_screen(win, btn.x, btn.y)
                cands = detect_fish_shadows(frame, pond, avg_bright)
                if cands:
                    shadows = cands
                before_frame = frame
                mouse_buf.clear()
                time.sleep(0.05)
            elif btn_pos is not None and btn_screen is not None:
                drag = self._compute_drag(btn_screen, mouse_buf)
                return btn_pos, btn_screen, drag, shadows, before_frame
            else:
                time.sleep(0.05)

        return None

    @staticmethod
    def _compute_drag(
        origin: tuple[int, int],
        buf: list[tuple[int, int]],
    ) -> tuple[int, int]:
        """Find the drag endpoint — the position furthest from origin."""
        if not buf:
            return (0, 0)
        ox, oy = origin
        best = max(buf, key=lambda p: (p[0] - ox) ** 2 + (p[1] - oy) ** 2)
        return best[0] - ox, best[1] - oy

    def _record_one_cast(
        self,
        win: WindowInfo,
        pond: PondArea,
        avg_bright: int,
    ) -> CastSample | None:
        """Wait for one complete manual cast cycle and return a sample."""

        result = self._wait_for_cast_start(win, pond, avg_bright)
        if result is None:
            return None
        btn_pos, _, drag, shadows, before_frame = result

        log.info("Recorder: cast detected — tracking mouse")
        drag_dx, drag_dy = drag
        log.info("Recorder: drag=(%+d,%+d)", drag_dx, drag_dy)

        time.sleep(1.5)

        after_frame = capture_window(win)
        if after_frame is None or before_frame is None:
            return None

        bobber = detect_bobber(
            before_frame,
            after_frame,
            (pond.x, pond.y, pond.width, pond.height),
            drag_label=f"rec_{len(self.samples)}",
        )
        if bobber is None:
            log.info("Recorder: bobber not detected — skipping cast")
            self._wait_for_button(win)
            return None

        bx, by = bobber

        if not shadows:
            log.info("Recorder: no shadows were visible — skipping cast")
            self._wait_for_button(win)
            return None

        nearest = min(shadows, key=lambda s: (s.cx - bx) ** 2 + (s.cy - by) ** 2)
        log.info(
            "Recorder: bobber=(%d,%d) nearest_shadow=(%d,%d) btn=(%d,%d)",
            bx,
            by,
            nearest.cx,
            nearest.cy,
            btn_pos.x,
            btn_pos.y,
        )

        self._save_recording_debug(after_frame, bx, by, nearest, btn_pos)
        self._wait_for_button(win)

        return CastSample(
            button_x=btn_pos.x,
            button_y=btn_pos.y,
            target_x=nearest.cx,
            target_y=nearest.cy,
            bobber_x=bx,
            bobber_y=by,
            drag_dx=drag_dx,
            drag_dy=drag_dy,
        )

    def _save_recording_debug(self, frame, bx, by, nearest, btn_pos) -> None:
        if not dbg.is_enabled():
            return
        anns = [
            {
                "type": "circle",
                "center": (bx, by),
                "radius": 15,
                "color": (0, 0, 255),
                "thickness": 3,
            },
            {
                "type": "text",
                "pos": (bx + 18, by),
                "text": "bobber",
                "color": (0, 0, 255),
                "thickness": 2,
            },
            {
                "type": "circle",
                "center": (nearest.cx, nearest.cy),
                "radius": 12,
                "color": (0, 255, 0),
                "thickness": 2,
            },
            {
                "type": "text",
                "pos": (nearest.cx + 14, nearest.cy - 4),
                "text": "target",
                "color": (0, 255, 0),
                "thickness": 1,
            },
            {
                "type": "circle",
                "center": (btn_pos.x, btn_pos.y),
                "radius": 10,
                "color": (0, 0, 255),
            },
            {
                "type": "line",
                "pt1": (btn_pos.x, btn_pos.y),
                "pt2": (bx, by),
                "color": (255, 0, 0),
                "thickness": 1,
            },
        ]
        dbg.save(frame, f"rec_cast_{len(self.samples)}", annotations=anns)

    def _wait_for_button(self, win: WindowInfo) -> None:
        """Wait for the cast button to reappear (end of cast cycle)."""
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not self._stop.is_set():
            frame = capture_window(win)
            if frame is not None and find_template(frame, "red_fishing_button") is not None:
                return
            time.sleep(0.3)


_MIN_DRAG_MAGNITUDE = 30
_MIN_USABLE_SAMPLES = 2
_MIN_OFFSET_PX = 10
_DEFAULT_AIM_FALLBACK = 3.0


def fit_cast_params(samples: list[CastSample]) -> CastParams | None:
    """Fit power_base and aim_base from recorded cast samples.

    Model: drag_dy = power_base * sqrt(abs(offset_y))
           drag_dx = aim_base * sqrt(abs(offset_x)) * sign(offset_x)
    """
    usable = [
        s
        for s in samples
        if math.hypot(s.drag_dx, s.drag_dy) >= _MIN_DRAG_MAGNITUDE and s.drag_dy > 0
    ]
    if len(usable) < _MIN_USABLE_SAMPLES:
        log.warning(
            "Need %d+ usable samples (drag >= %dpx), have %d of %d",
            _MIN_USABLE_SAMPLES,
            _MIN_DRAG_MAGNITUDE,
            len(usable),
            len(samples),
        )
        return None

    power_estimates = []
    aim_estimates = []

    for s in usable:
        offset_y = abs(s.target_y - s.button_y) / _RETINA_SCALE
        offset_x = abs(s.target_x - s.button_x) / _RETINA_SCALE

        if offset_y > _MIN_OFFSET_PX:
            pb = abs(s.drag_dy) / math.sqrt(offset_y)
            power_estimates.append(pb)

        if offset_x > _MIN_OFFSET_PX:
            ab = abs(s.drag_dx) / math.sqrt(offset_x)
            aim_estimates.append(ab)

    if not power_estimates:
        log.warning("No valid power samples")
        return None

    power_base = float(np.median(power_estimates))
    aim_base = float(np.median(aim_estimates)) if aim_estimates else _DEFAULT_AIM_FALLBACK

    log.info(
        "Fitted cast params: power_base=%.2f (from %d samples), aim_base=%.2f (from %d samples)",
        power_base,
        len(power_estimates),
        aim_base,
        len(aim_estimates),
    )

    for i, s in enumerate(usable):
        off_x = (s.target_x - s.button_x) / _RETINA_SCALE
        off_y = (s.target_y - s.button_y) / _RETINA_SCALE
        log.info(
            "  sample %d: offset=(%+.0f,%+.0f) drag=(%+.0f,%+.0f) est_power=%.1f est_aim=%.1f",
            i,
            off_x,
            off_y,
            s.drag_dx,
            s.drag_dy,
            abs(s.drag_dy) / max(1, math.sqrt(abs(off_y))) if abs(off_y) > _MIN_OFFSET_PX else 0,
            abs(s.drag_dx) / max(1, math.sqrt(abs(off_x))) if abs(off_x) > _MIN_OFFSET_PX else 0,
        )

    params = CastParams(power_base=round(power_base, 2), aim_base=round(aim_base, 2))
    params.save()
    return params
