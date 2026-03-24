"""OpenCV template matching for UI button detection.

Ported from ImageTemplateMatcher.cs / UIElementManager.cs in the reference bot.
"""

from __future__ import annotations

import os
from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log


class MatchResult(NamedTuple):
    x: int          # center x of the match (window-relative)
    y: int          # center y of the match (window-relative)
    confidence: float
    width: int
    height: int


_template_cache: dict[str, np.ndarray] = {}


def _load_template(name: str) -> np.ndarray | None:
    """Load a template image from the templates directory, with caching."""
    if name in _template_cache:
        return _template_cache[name]

    filename = settings.TEMPLATE_NAMES.get(name, name)
    path = os.path.join(settings.TEMPLATES_DIR, filename)

    if not os.path.isfile(path):
        log.warning("Template not found: %s", path)
        return None

    tmpl = cv2.imread(path, cv2.IMREAD_COLOR)
    if tmpl is None:
        log.warning("Failed to load template: %s", path)
        return None

    _template_cache[name] = tmpl
    log.debug("Loaded template '%s' (%dx%d)", name, tmpl.shape[1], tmpl.shape[0])
    return tmpl


def clear_cache() -> None:
    """Clear the template image cache (e.g., after recapturing templates)."""
    global _global_scale
    _template_cache.clear()
    _scaled_template_cache.clear()
    _global_scale = None


_COARSE_SCALE_RANGE = np.arange(0.3, 2.1, 0.1)
_FINE_STEP = 0.02
_global_scale: float | None = None
_scaled_template_cache: dict[str, np.ndarray] = {}


_MIN_CALIBRATION_CONF = 0.60


_CALIBRATION_ANCHORS = [
    "red_fishing_button",
    "exit_fishing_button",
    "plant_flower_button",
    "pick_flower_button",
    "watering_can_button",
]


def _match_at_scale(
    frame_bgr: np.ndarray, tmpl: np.ndarray, scale: float
) -> float:
    """Return the match confidence of *tmpl* at *scale* against *frame_bgr*."""
    fh, fw = frame_bgr.shape[:2]
    th, tw = tmpl.shape[:2]
    new_w = int(tw * scale)
    new_h = int(th * scale)
    if new_w < 10 or new_h < 10 or new_w > fw or new_h > fh:
        return -1.0
    scaled = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    result = cv2.matchTemplate(frame_bgr, scaled, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return float(max_val)


def calibrate_scale(frame_bgr: np.ndarray) -> float:
    """Determine the window scale by matching a known template across scales.

    Uses a two-pass approach: coarse sweep (0.1 steps over 0.3-2.0) then a
    fine sweep (0.02 steps around the best coarse hit). This finds the precise
    scale even when the window is resized significantly from when templates
    were captured.

    Tries multiple anchor templates so calibration works at the fishing dock
    or at the garden.  Returns the best scale, or -1.0 if calibration failed.
    """
    global _global_scale
    _scaled_template_cache.clear()

    overall_best_val = -1.0
    overall_best_scale = 1.0
    best_anchor = ""

    for anchor in _CALIBRATION_ANCHORS:
        tmpl = _load_template(anchor)
        if tmpl is None:
            continue

        # Pass 1: coarse
        for scale in _COARSE_SCALE_RANGE:
            val = _match_at_scale(frame_bgr, tmpl, scale)
            if val > overall_best_val:
                overall_best_val = val
                overall_best_scale = scale
                best_anchor = anchor

        if overall_best_val >= _MIN_CALIBRATION_CONF:
            break

    if overall_best_val < 0.30:
        log.warning(
            "calibrate_scale FAILED: best conf=%.3f (need %.2f). "
            "Make sure a known UI button is visible, then recalibrate.",
            overall_best_val, _MIN_CALIBRATION_CONF,
        )
        _global_scale = None
        return -1.0

    # Pass 2: fine-tune around the best coarse scale
    tmpl = _load_template(best_anchor)
    if tmpl is not None:
        fine_range = np.arange(
            overall_best_scale - 0.1, overall_best_scale + 0.1 + _FINE_STEP, _FINE_STEP
        )
        for scale in fine_range:
            val = _match_at_scale(frame_bgr, tmpl, scale)
            if val > overall_best_val:
                overall_best_val = val
                overall_best_scale = scale

    if overall_best_val < _MIN_CALIBRATION_CONF:
        log.warning(
            "calibrate_scale FAILED: best conf=%.3f (need %.2f) after fine pass. "
            "Make sure a known UI button is visible, then recalibrate.",
            overall_best_val, _MIN_CALIBRATION_CONF,
        )
        _global_scale = None
        return -1.0

    _global_scale = overall_best_scale
    log.info("calibrate_scale: anchor=%s scale=%.2f (conf=%.3f) — locked",
             best_anchor, overall_best_scale, overall_best_val)
    return overall_best_scale


def _get_scaled_template(name: str) -> np.ndarray | None:
    """Return the template pre-scaled to the global window scale."""
    if name in _scaled_template_cache:
        return _scaled_template_cache[name]

    tmpl = _load_template(name)
    if tmpl is None:
        return None

    scale = _global_scale if _global_scale is not None else 1.0
    if abs(scale - 1.0) > 0.01:
        new_w = int(tmpl.shape[1] * scale)
        new_h = int(tmpl.shape[0] * scale)
        tmpl = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    _scaled_template_cache[name] = tmpl
    return tmpl


_FIND_SCALE_OFFSETS = np.array([0.0, -0.04, 0.04, -0.08, 0.08])


def find_template(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> MatchResult | None:
    """Find a template in the frame around the calibrated scale.

    Tries the locked scale first, then probes ±0.04 and ±0.08 as fallbacks.
    This handles templates captured at slightly different window sizes.
    """
    if _global_scale is None:
        log.warning("find_template called before calibration")
        return None

    raw_tmpl = _load_template(template_name)
    if raw_tmpl is None:
        return None

    fh, fw = frame_bgr.shape[:2]

    for offset in _FIND_SCALE_OFFSETS:
        scale = _global_scale + offset
        new_w = int(raw_tmpl.shape[1] * scale)
        new_h = int(raw_tmpl.shape[0] * scale)
        if new_w < 10 or new_h < 10 or new_w > fw or new_h > fh:
            continue

        if abs(offset) < 1e-9:
            tmpl = _get_scaled_template(template_name)
        else:
            tmpl = cv2.resize(raw_tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        if tmpl is None:
            continue

        th, tw = tmpl.shape[:2]
        result = cv2.matchTemplate(frame_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            cx = max_loc[0] + tw // 2
            cy = max_loc[1] + th // 2
            return MatchResult(cx, cy, float(max_val), tw, th)

    return None


def find_all_templates(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """Find all occurrences of a template above the threshold."""
    tmpl = _load_template(template_name)
    if tmpl is None:
        return []

    th, tw = tmpl.shape[:2]
    fh, fw = frame_bgr.shape[:2]
    if tw > fw or th > fh:
        return []

    result = cv2.matchTemplate(frame_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
    locations = np.where(result >= threshold)

    matches: list[MatchResult] = []
    for pt_y, pt_x in zip(*locations):
        cx = int(pt_x) + tw // 2
        cy = int(pt_y) + th // 2
        conf = float(result[pt_y, pt_x])
        matches.append(MatchResult(cx, cy, conf, tw, th))

    # Deduplicate overlapping detections (non-maximum suppression)
    return _nms(matches, tw, th)


def _nms(matches: list[MatchResult], tw: int, th: int) -> list[MatchResult]:
    """Simple non-maximum suppression: keep the highest-confidence
    match within each cluster of overlapping detections."""
    if not matches:
        return []

    matches_sorted = sorted(matches, key=lambda m: m.confidence, reverse=True)
    kept: list[MatchResult] = []
    suppressed = set()

    for i, m in enumerate(matches_sorted):
        if i in suppressed:
            continue
        kept.append(m)
        for j in range(i + 1, len(matches_sorted)):
            if j in suppressed:
                continue
            other = matches_sorted[j]
            if abs(m.x - other.x) < tw // 2 and abs(m.y - other.y) < th // 2:
                suppressed.add(j)

    return kept


def is_element_visible(frame_bgr: np.ndarray, template_name: str) -> bool:
    """Quick check: is the given UI element currently visible?"""
    return find_template(frame_bgr, template_name) is not None


def save_template(name: str, image: np.ndarray) -> str:
    """Save a captured template image to the templates directory.

    Returns the file path.
    """
    os.makedirs(settings.TEMPLATES_DIR, exist_ok=True)
    filename = settings.TEMPLATE_NAMES.get(name, f"{name}.png")
    path = os.path.join(settings.TEMPLATES_DIR, filename)
    cv2.imwrite(path, image)
    log.info("Saved template '%s' → %s", name, path)
    clear_cache()
    return path
