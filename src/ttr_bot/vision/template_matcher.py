"""OpenCV template matching for UI button detection.

Ported from ImageTemplateMatcher.cs / UIElementManager.cs in the reference bot.
"""

from __future__ import annotations

import os
import time
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
_offset_scaled_cache: dict[tuple[str, float], np.ndarray] = {}


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
    global _global_scale, _downsample_factor, _downsampled_frame_cache
    _template_cache.clear()
    _scaled_template_cache.clear()
    _offset_scaled_cache.clear()
    _global_scale = None
    _downsample_factor = 1
    _downsampled_frame_cache = None


_COARSE_SCALE_RANGE = np.arange(0.8, 1.3, 0.1)
_FINE_STEP = 0.04
_global_scale: float | None = None
_scaled_template_cache: dict[str, np.ndarray] = {}


_MIN_CALIBRATION_CONF = 0.60
# Dock/HUD can pick up grass/UI tint; still usable for scale when strict match fails.
_MIN_CALIBRATION_CONF_RELAXED = 0.48


# hud_bottom_right_icon first: visible in almost all states (golf, estate, streets).
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

    Uses a two-pass approach: coarse sweep (0.1 steps over 0.6-1.5) then a
    fine sweep (0.02 steps around the best coarse hit).

    Also detects Retina (2x) frames and sets the downsample factor so that
    subsequent find_template calls run on a half-res frame for speed.
    """
    global _global_scale, _downsample_factor
    _scaled_template_cache.clear()

    t_cal = time.monotonic()
    fh, fw = frame_bgr.shape[:2]
    _downsample_factor = 2 if fw >= 1800 else 1
    log.info("calibrate_scale: frame=%dx%d downsample=%dx", fw, fh, _downsample_factor)

    overall_best_val = -1.0
    overall_best_scale = 1.0
    best_anchor = ""

    for anchor in _CALIBRATION_ANCHORS:
        tmpl = _load_template(anchor)
        if tmpl is None:
            continue

        t_anchor = time.monotonic()
        anchor_best = -1.0
        anchor_scale = 1.0
        for scale in _COARSE_SCALE_RANGE:
            val = _match_at_scale(frame_bgr, tmpl, scale)
            if val > anchor_best:
                anchor_best = val
                anchor_scale = scale

        log.info("calibrate coarse: %-24s best=%.3f @ scale=%.2f (%.0fms)",
                 anchor, anchor_best, anchor_scale,
                 (time.monotonic() - t_anchor) * 1000)

        if anchor_best > overall_best_val:
            overall_best_val = anchor_best
            overall_best_scale = anchor_scale
            best_anchor = anchor

        if overall_best_val >= _MIN_CALIBRATION_CONF:
            break

    if overall_best_val < 0.30:
        log.warning(
            "calibrate_scale FAILED: best conf=%.3f (no usable match). "
            "Run: uv run python tools/snapshot_game_state.py --promote-template",
            overall_best_val,
        )
        _global_scale = None
        return -1.0

    # Pass 2: fine-tune around the best coarse scale (±0.08 in _FINE_STEP increments)
    t_fine = time.monotonic()
    tmpl = _load_template(best_anchor)
    if tmpl is not None:
        fine_range = np.arange(
            overall_best_scale - 0.08, overall_best_scale + 0.08 + _FINE_STEP, _FINE_STEP
        )
        for scale in fine_range:
            val = _match_at_scale(frame_bgr, tmpl, scale)
            if val > overall_best_val:
                overall_best_val = val
                overall_best_scale = scale
    log.info("calibrate fine-tune: %.0fms", (time.monotonic() - t_fine) * 1000)

    if overall_best_val < _MIN_CALIBRATION_CONF_RELAXED:
        log.warning(
            "calibrate_scale FAILED: best conf=%.3f (need %.2f). "
            "Recapture HUD with tools/snapshot_game_state.py --promote-template",
            overall_best_val, _MIN_CALIBRATION_CONF_RELAXED,
        )
        _global_scale = None
        return -1.0

    _global_scale = overall_best_scale
    cal_ms = (time.monotonic() - t_cal) * 1000
    if overall_best_val < _MIN_CALIBRATION_CONF:
        log.warning(
            "calibrate_scale: relaxed accept anchor=%s scale=%.2f (conf=%.3f) %.0fms",
            best_anchor, overall_best_scale, overall_best_val, cal_ms,
        )
    else:
        log.info(
            "calibrate_scale: anchor=%s scale=%.2f (conf=%.3f) — locked (%.0fms)",
            best_anchor, overall_best_scale, overall_best_val, cal_ms,
        )
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


_FIND_SCALE_OFFSETS = np.array([0.0, -0.04, 0.04])

# Retina displays produce 2x frames (e.g. 2416×1582 for a 1208×791 window).
# Downsampling before matchTemplate cuts cost ~75%.  We detect Retina at
# calibration time and store the factor here so find_template can apply it.
_downsample_factor: int = 1
_downsampled_frame_cache: tuple[int, np.ndarray] | None = None  # (id(frame), small)


def _get_offset_scaled(name: str, offset: float) -> np.ndarray | None:
    """Return a template scaled to (_global_scale + offset), with caching."""
    if abs(offset) < 1e-9:
        return _get_scaled_template(name)

    key = (name, offset)
    if key in _offset_scaled_cache:
        return _offset_scaled_cache[key]

    raw = _load_template(name)
    if raw is None or _global_scale is None:
        return None

    scale = _global_scale + offset
    new_w = int(raw.shape[1] * scale)
    new_h = int(raw.shape[0] * scale)
    if new_w < 10 or new_h < 10:
        return None

    scaled = cv2.resize(raw, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    _offset_scaled_cache[key] = scaled
    return scaled


def _get_small_frame(frame_bgr: np.ndarray) -> np.ndarray:
    """Return a downsampled frame, caching per frame identity."""
    global _downsampled_frame_cache
    if _downsample_factor <= 1:
        return frame_bgr
    fid = id(frame_bgr)
    if _downsampled_frame_cache is not None and _downsampled_frame_cache[0] == fid:
        return _downsampled_frame_cache[1]
    small = cv2.resize(
        frame_bgr,
        (frame_bgr.shape[1] // _downsample_factor,
         frame_bgr.shape[0] // _downsample_factor),
        interpolation=cv2.INTER_AREA,
    )
    _downsampled_frame_cache = (fid, small)
    return small


def find_template(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> MatchResult | None:
    """Find a template in the frame around the calibrated scale.

    Tries the locked scale first, then probes +/-0.04 and +/-0.08 as fallbacks.
    Uses a downsampled frame on Retina displays for speed; coordinates are
    mapped back to full-resolution.
    """
    if _global_scale is None:
        log.warning("find_template called before calibration")
        return None

    t_start = time.monotonic()
    ds = _downsample_factor
    small = _get_small_frame(frame_bgr)
    fh, fw = small.shape[:2]
    scales_tried = 0

    for offset in _FIND_SCALE_OFFSETS:
        tmpl = _get_offset_scaled(template_name, offset)
        if tmpl is None:
            continue

        # Scale template down to match the downsampled frame
        if ds > 1:
            th_ds = tmpl.shape[0] // ds
            tw_ds = tmpl.shape[1] // ds
            if th_ds < 8 or tw_ds < 8:
                continue
            tmpl_small = cv2.resize(tmpl, (tw_ds, th_ds), interpolation=cv2.INTER_AREA)
        else:
            tmpl_small = tmpl
            th_ds, tw_ds = tmpl.shape[:2]

        if tw_ds > fw or th_ds > fh:
            continue

        scales_tried += 1
        t_cv = time.monotonic()
        result = cv2.matchTemplate(small, tmpl_small, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        cv_ms = (time.monotonic() - t_cv) * 1000

        if max_val >= threshold:
            cx = (max_loc[0] + tw_ds // 2) * ds
            cy = (max_loc[1] + th_ds // 2) * ds
            total_ms = (time.monotonic() - t_start) * 1000
            log.debug("[TM] %-28s HIT  offset=%.2f conf=%.3f  "
                      "cv=%.0fms scales=%d total=%.0fms frame=%dx%d",
                      template_name, offset, max_val,
                      cv_ms, scales_tried, total_ms, fw, fh)
            return MatchResult(cx, cy, float(max_val),
                               tmpl.shape[1], tmpl.shape[0])

    total_ms = (time.monotonic() - t_start) * 1000
    log.debug("[TM] %-28s MISS scales=%d total=%.0fms frame=%dx%d",
              template_name, scales_tried, total_ms, fw, fh)
    return None


def find_all_templates(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """Find all occurrences of a template above the threshold."""
    tmpl = _get_scaled_template(template_name)
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
