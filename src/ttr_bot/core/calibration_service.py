"""Consolidated calibration: find window, lock bounds, capture, scale."""

from dataclasses import dataclass

from ttr_bot.utils.logger import log


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    success: bool
    scale: float
    width: int
    height: int
    error: str = ""


class CalibrationService:
    """Single entry-point for the find-window → capture → scale calibration flow."""

    def __init__(self) -> None:
        self._scale: float | None = None

    def calibrate(self) -> CalibrationResult:
        """Find TTR window, lock bounds, capture frame, calibrate scale."""
        from ttr_bot.core.screen_capture import capture_window
        from ttr_bot.core.window_manager import find_ttr_window, set_calibrated_bounds
        from ttr_bot.vision.template_matcher import calibrate_scale, clear_cache

        win = find_ttr_window()
        if win is None:
            return CalibrationResult(
                success=False, scale=-1, width=0, height=0, error="TTR window not found"
            )

        set_calibrated_bounds(win)
        log.info("Window locked: %dx%d at (%d,%d)", win.width, win.height, win.x, win.y)

        frame = capture_window(win)
        if frame is None:
            return CalibrationResult(
                success=False, scale=-1, width=win.width, height=win.height, error="Capture failed"
            )

        clear_cache()
        scale = calibrate_scale(frame)
        if scale < 0:
            return CalibrationResult(
                success=False,
                scale=scale,
                width=win.width,
                height=win.height,
                error="Calibration failed — no anchor template found",
            )

        self._scale = scale
        return CalibrationResult(success=True, scale=scale, width=win.width, height=win.height)

    @property
    def is_calibrated(self) -> bool:
        from ttr_bot.vision.template_matcher import _default

        return _default.scale is not None

    @property
    def scale(self) -> float | None:
        return self._scale
