"""OpenCV template matching for UI button detection.

Ported from ImageTemplateMatcher.cs / UIElementManager.cs in the reference bot.
"""

from __future__ import annotations

import os
from typing import NamedTuple

import cv2
import numpy as np

from config import settings
from utils.logger import log


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
    _template_cache.clear()


def find_template(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> MatchResult | None:
    """Find a template in the frame using matchTemplate (TM_CCOEFF_NORMED).

    Returns a MatchResult with the center coordinates and confidence,
    or None if confidence < threshold.
    """
    tmpl = _load_template(template_name)
    if tmpl is None:
        return None

    th, tw = tmpl.shape[:2]
    fh, fw = frame_bgr.shape[:2]
    if tw > fw or th > fh:
        return None

    result = cv2.matchTemplate(frame_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return None

    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2

    return MatchResult(cx, cy, float(max_val), tw, th)


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
