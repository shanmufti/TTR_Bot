"""Garden UI helpers: find-and-click polling and scale calibration."""

import threading
import time
from collections.abc import Callable

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.utils.logger import log
from ttr_bot.vision.template_matcher import find_template


def _crop_frame_region(
    frame,
    region_frac: tuple[float, float, float, float],
) -> tuple[object, int, int]:
    """Crop *frame* using fractional bounds (left, top, right, bottom).

    Each fraction is in ``[0, 1]`` relative to width or height. Returns the
    cropped array (or full *frame* if the crop would be degenerate) and the
    ``(x_offset, y_offset)`` to map match coordinates back to full-frame space.
    """
    fh, fw = frame.shape[:2]
    lf, tf, rf, bf = region_frac
    x0 = max(0, min(fw, int(fw * lf)))
    y0 = max(0, min(fh, int(fh * tf)))
    x1 = max(0, min(fw, int(fw * rf)))
    y1 = max(0, min(fh, int(fh * bf)))
    if x1 <= x0 + 32 or y1 <= y0 + 32:
        return frame, 0, 0
    return frame[y0:y1, x0:x1], x0, y0


def find_and_click(  # noqa: PLR0913 — optional vision kwargs are intentional
    template_name: str,
    win: WindowInfo | None = None,
    timeout: float = settings.GARDEN_FIND_TIMEOUT_S,
    stop_event: threading.Event | None = None,
    *,
    threshold: float | None = None,
    region_frac: tuple[float, float, float, float] | None = None,
    click_offset: tuple[int, int] = (0, 0),
) -> tuple[int, int] | None:
    """Poll for a template on screen and click it.

    Returns ``(x, y)`` of the clicked position on success, or ``None`` on
    failure.

    *region_frac* optionally restricts matching to a rectangle
    ``(left, top, right, bottom)`` as fractions of the frame width/height,
    e.g. ``(0.05, 0.08, 0.95, 0.76)`` excludes the bottom strip where the
    jellybean tray can false-match ``ok_button``.

    *click_offset* is added to the match center in window pixels (negative Y
    moves the click upward).
    """
    if win is None:
        win = find_ttr_window()
    if win is None:
        return None

    thr = settings.TEMPLATE_MATCH_THRESHOLD if threshold is None else threshold

    t_start = time.monotonic()
    polls = 0
    deadline = t_start + timeout
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            return None

        polls += 1
        t_cap = time.monotonic()
        frame = capture_window(win)
        cap_ms = (time.monotonic() - t_cap) * 1000
        if frame is None:
            time.sleep(0.1)
            continue

        search_frame = frame
        ox, oy = 0, 0
        if region_frac is not None:
            search_frame, ox, oy = _crop_frame_region(frame, region_frac)

        t_match = time.monotonic()
        match = find_template(search_frame, template_name, threshold=thr)
        match_ms = (time.monotonic() - t_match) * 1000

        if match is not None:
            cx, cy = match.x + ox, match.y + oy
            dx, dy = click_offset
            fh, fw = frame.shape[:2]
            cx = max(0, min(fw - 1, cx + dx))
            cy = max(0, min(fh - 1, cy + dy))
            inp.ensure_focused()
            time.sleep(0.05)
            inp.click(cx, cy, window=win)
            total_ms = (time.monotonic() - t_start) * 1000
            log.info(
                "Clicked %s at (%d,%d) conf=%.2f  (polls=%d cap=%.0fms match=%.0fms total=%.0fms)",
                template_name,
                cx,
                cy,
                match.confidence,
                polls,
                cap_ms,
                match_ms,
                total_ms,
            )
            return (cx, cy)

        time.sleep(0.2)

    log.warning("Template %s not found within %.1fs (%d polls)", template_name, timeout, polls)
    return None


def ensure_calibrated(
    status_fn: Callable[[str], None] | None = None,
) -> bool:
    """Verify scale calibration is set, running it if needed."""
    from ttr_bot.core.calibration_service import CalibrationService
    from ttr_bot.vision.template_matcher import _default as tm_instance

    if tm_instance.scale is not None:
        return True

    if status_fn:
        status_fn("Calibrating…")

    result = CalibrationService().calibrate()
    if not result.success:
        log.warning("Calibration failed: %s", result.error)
        return False

    if status_fn:
        status_fn(f"Calibrated: scale={result.scale:.1f}")
    return True
