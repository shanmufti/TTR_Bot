"""Scale calibration for template matching.

Scans a set of known anchor templates at multiple scales to determine
the current UI scale factor, then fine-tunes the result.

Extracted from ``template_matcher.py`` so calibration logic can evolve
independently of the matching hot-path.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from ttr_bot.utils.logger import log

if TYPE_CHECKING:
    from ttr_bot.vision.template_matcher import TemplateMatcher

_COARSE_SCALE_RANGE = np.arange(0.4, 1.3, 0.1)
_FINE_STEP = 0.04

_MIN_CALIBRATION_CONF = 0.60
_MIN_CALIBRATION_CONF_RELAXED = 0.48
_MIN_TEMPLATE_DIM = 10
_CALIBRATION_FAIL_CONF = 0.30
_DOWNSAMPLE_WIDTH_THRESHOLD = 1800

_CALIBRATION_ANCHORS = [
    "hud_bottom_right_icon",
    "red_fishing_button",
    "exit_fishing_button",
    "plant_flower_button",
    "pick_flower_button",
    "watering_can_button",
    "golf_pencil_button",
    "golf_close_button",
    "golf_turn_timer",
]


# ------------------------------------------------------------------
# Low-level helper
# ------------------------------------------------------------------


def match_at_scale(frame_bgr: np.ndarray, tmpl: np.ndarray, scale: float) -> float:
    """Return the best match confidence for *tmpl* resized to *scale*."""
    fh, fw = frame_bgr.shape[:2]
    th, tw = tmpl.shape[:2]
    new_w = int(tw * scale)
    new_h = int(th * scale)
    if new_w < _MIN_TEMPLATE_DIM or new_h < _MIN_TEMPLATE_DIM or new_w > fw or new_h > fh:
        return -1.0
    scaled = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    result = cv2.matchTemplate(frame_bgr, scaled, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return float(max_val)


# ------------------------------------------------------------------
# Calibration entry-point
# ------------------------------------------------------------------


def calibrate_scale(matcher: TemplateMatcher, frame_bgr: np.ndarray) -> float:
    """Determine the window scale by matching known templates across scales.

    This acquires the matcher's lock internally, so the caller should
    *not* hold it.
    """
    with matcher._lock:
        return _calibrate_scale_locked(matcher, frame_bgr)


def _calibrate_scale_locked(matcher: TemplateMatcher, frame_bgr: np.ndarray) -> float:
    matcher._scaled_template_cache.clear()

    t_cal = time.monotonic()
    fh, fw = frame_bgr.shape[:2]
    downsample = 2 if fw >= _DOWNSAMPLE_WIDTH_THRESHOLD else 1
    log.info("calibrate_scale: frame=%dx%d downsample=%dx", fw, fh, downsample)

    best_anchor, best_scale, best_val = _coarse_anchor_scan(matcher, frame_bgr)

    if best_val < _CALIBRATION_FAIL_CONF:
        log.warning(
            "calibrate_scale FAILED: best conf=%.3f (no usable match). "
            "Run: uv run python tools/snapshot_game_state.py --promote-template",
            best_val,
        )
        matcher._global_scale = None
        return -1.0

    best_scale, best_val = _fine_tune(matcher, frame_bgr, best_anchor, best_scale, best_val)

    if best_val < _MIN_CALIBRATION_CONF_RELAXED:
        log.warning(
            "calibrate_scale FAILED: best conf=%.3f (need %.2f). "
            "Recapture HUD with tools/snapshot_game_state.py --promote-template",
            best_val,
            _MIN_CALIBRATION_CONF_RELAXED,
        )
        matcher._global_scale = None
        return -1.0

    matcher.set_calibrated_scale(best_scale, downsample)
    cal_ms = (time.monotonic() - t_cal) * 1000
    if best_val < _MIN_CALIBRATION_CONF:
        log.warning(
            "calibrate_scale: relaxed accept anchor=%s scale=%.2f (conf=%.3f) %.0fms",
            best_anchor,
            best_scale,
            best_val,
            cal_ms,
        )
    else:
        log.info(
            "calibrate_scale: anchor=%s scale=%.2f (conf=%.3f) — locked (%.0fms)",
            best_anchor,
            best_scale,
            best_val,
            cal_ms,
        )
    return best_scale


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _coarse_anchor_scan(
    matcher: TemplateMatcher,
    frame_bgr: np.ndarray,
) -> tuple[str, float, float]:
    """Try each anchor at coarse scales, return (anchor, scale, confidence)."""
    best_val = -1.0
    best_scale = 1.0
    best_anchor = ""

    for anchor in _CALIBRATION_ANCHORS:
        tmpl = matcher.load_template(anchor)
        if tmpl is None:
            continue

        t_anchor = time.monotonic()
        anchor_best = -1.0
        anchor_scale = 1.0
        for scale in _COARSE_SCALE_RANGE:
            val = match_at_scale(frame_bgr, tmpl, scale)
            if val > anchor_best:
                anchor_best = val
                anchor_scale = scale

        log.info(
            "calibrate coarse: %-24s best=%.3f @ scale=%.2f (%.0fms)",
            anchor,
            anchor_best,
            anchor_scale,
            (time.monotonic() - t_anchor) * 1000,
        )

        if anchor_best > best_val:
            best_val = anchor_best
            best_scale = anchor_scale
            best_anchor = anchor

        if best_val >= _MIN_CALIBRATION_CONF:
            break

    return best_anchor, best_scale, best_val


def _fine_tune(
    matcher: TemplateMatcher,
    frame_bgr: np.ndarray,
    anchor: str,
    coarse_scale: float,
    coarse_val: float,
) -> tuple[float, float]:
    """Refine the scale around *coarse_scale*. Returns (scale, confidence)."""
    t_fine = time.monotonic()
    tmpl = matcher.load_template(anchor)
    best_scale, best_val = coarse_scale, coarse_val

    if tmpl is not None:
        fine_range = np.arange(
            coarse_scale - 0.08,
            coarse_scale + 0.08 + _FINE_STEP,
            _FINE_STEP,
        )
        for scale in fine_range:
            val = match_at_scale(frame_bgr, tmpl, scale)
            if val > best_val:
                best_val = val
                best_scale = scale

    log.info("calibrate fine-tune: %.0fms", (time.monotonic() - t_fine) * 1000)
    return best_scale, best_val
