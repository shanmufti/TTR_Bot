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


def find_and_click(
    template_name: str,
    win: WindowInfo | None = None,
    timeout: float = settings.GARDEN_FIND_TIMEOUT_S,
    stop_event: threading.Event | None = None,
) -> tuple[int, int] | None:
    """Poll for a template on screen and click it.

    Returns ``(x, y)`` of the clicked position on success, or ``None`` on
    failure.
    """
    if win is None:
        win = find_ttr_window()
    if win is None:
        return None

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

        t_match = time.monotonic()
        match = find_template(frame, template_name)
        match_ms = (time.monotonic() - t_match) * 1000

        if match is not None:
            inp.ensure_focused()
            time.sleep(0.05)
            inp.click(match.x, match.y, window=win)
            total_ms = (time.monotonic() - t_start) * 1000
            log.info(
                "Clicked %s at (%d,%d) conf=%.2f  (polls=%d cap=%.0fms match=%.0fms total=%.0fms)",
                template_name,
                match.x,
                match.y,
                match.confidence,
                polls,
                cap_ms,
                match_ms,
                total_ms,
            )
            return (match.x, match.y)

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
