"""Passive cast recorder: watches the user fish manually and records samples.

Each sample captures the drag vector (via mouse tracking), the shadow
positions before the cast, and the bobber landing position.  After
recording, fit_cast_params() derives power/aim curve constants.
"""

import time

import pyautogui

from ttr_bot.config import settings
from ttr_bot.core.bobber_detector import detect_bobber
from ttr_bot.core.bot_base import BotBase
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.fishing.cast_fitter import CastSample
from ttr_bot.utils import debug_frames as dbg
from ttr_bot.utils.logger import log
from ttr_bot.vision.color_matcher import average_water_brightness, build_water_mask
from ttr_bot.vision.fish_detector import FishCandidate, detect_fish_shadows
from ttr_bot.vision.pond_detector import PondArea, detect_pond
from ttr_bot.vision.template_matcher import find_template

_RETINA_SCALE = settings.RETINA_SCALE


def _to_screen(win: WindowInfo, wx: int, wy: int) -> tuple[int, int]:
    return win.x + wx // _RETINA_SCALE, win.y + wy // _RETINA_SCALE


class CastRecorder(BotBase):
    """Passively records manual fishing casts."""

    def __init__(self) -> None:
        super().__init__()
        self.samples: list[CastSample] = []

    @property
    def recording(self) -> bool:
        return self.running

    def start(self) -> None:
        self.samples.clear()
        self._start_thread(self._loop)

    def stop(self) -> None:
        super().stop()

    def _loop(self) -> None:
        from ttr_bot.core.calibration_service import CalibrationService

        result = CalibrationService().calibrate()
        if not result.success:
            self._status(result.error)
            return

        win = find_ttr_window()
        if win is None:
            self._status("TTR window not found")
            return

        frame = capture_window(win)
        if frame is None:
            self._status("Capture failed")
            return

        pond = detect_pond(frame)
        if pond.empty:
            self._status("No pond detected")
            return

        crop = frame[pond.y : pond.y + pond.height, pond.x : pond.x + pond.width]
        wm = build_water_mask(crop)
        avg_bright = average_water_brightness(crop, wm)

        self._status("Recording — fish normally!")

        while not self._stop_event.is_set():
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

        while not self._stop_event.is_set():
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
        while time.monotonic() < deadline and not self._stop_event.is_set():
            frame = capture_window(win)
            if frame is not None and find_template(frame, "red_fishing_button") is not None:
                return
            time.sleep(0.3)
