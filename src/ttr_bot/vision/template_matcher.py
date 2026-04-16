"""OpenCV template matching for UI button detection.

Ported from ImageTemplateMatcher.cs / UIElementManager.cs in the reference bot.
"""

import os
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log
from ttr_bot.vision.template_calibration import (
    _CALIBRATION_ANCHORS as _CALIBRATION_ANCHORS,
)


@dataclass(frozen=True, slots=True)
class MatchResult:
    """A single template match: position, confidence, and size."""

    x: int
    y: int
    confidence: float
    width: int
    height: int


_FIND_SCALE_OFFSETS = np.array([0.0, -0.04, 0.04])

_MIN_TEMPLATE_DIM = 10
_MIN_TEMPLATE_DIM_DS = 8
_SCALE_IDENTITY_EPSILON = 0.01
_OFFSET_ZERO_EPSILON = 1e-9


class TemplateMatcher:
    """Thread-safe OpenCV template matcher with scale calibration.

    All mutable state is protected by an internal lock so concurrent
    callers (fishing thread, garden watcher, UI poll) don't corrupt
    caches or the calibrated scale.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._template_cache: dict[str, np.ndarray] = {}
        self._scaled_template_cache: dict[str, np.ndarray] = {}
        self._offset_scaled_cache: dict[tuple[str, float], np.ndarray] = {}
        self._global_scale: float | None = None
        self._downsample_factor: int = 1
        self._downsampled_frame_cache: tuple[int, np.ndarray] | None = None

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------

    def _load_template(self, name: str) -> np.ndarray | None:
        if name in self._template_cache:
            return self._template_cache[name]

        filename = settings.TEMPLATE_NAMES.get(name, name)
        path = os.path.join(settings.TEMPLATES_DIR, filename)

        if not os.path.isfile(path):
            log.warning("Template not found: %s", path)
            return None

        tmpl = cv2.imread(path, cv2.IMREAD_COLOR)
        if tmpl is None:
            log.warning("Failed to load template: %s", path)
            return None

        self._template_cache[name] = tmpl
        log.debug("Loaded template '%s' (%dx%d)", name, tmpl.shape[1], tmpl.shape[0])
        return tmpl

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        with self._lock:
            self._template_cache.clear()
            self._scaled_template_cache.clear()
            self._offset_scaled_cache.clear()
            self._global_scale = None
            self._downsample_factor = 1
            self._downsampled_frame_cache = None

    @property
    def scale(self) -> float | None:
        return self._global_scale

    # ------------------------------------------------------------------
    # Public accessors for calibration module
    # ------------------------------------------------------------------

    def load_template(self, name: str) -> np.ndarray | None:
        """Public wrapper around :meth:`_load_template`."""
        return self._load_template(name)

    def set_calibrated_scale(self, scale: float | None, downsample_factor: int = 1) -> None:
        """Apply a calibrated *scale* and reset caches."""
        self._global_scale = scale
        self._downsample_factor = downsample_factor
        self._scaled_template_cache.clear()

    # ------------------------------------------------------------------
    # Scaled template helpers
    # ------------------------------------------------------------------

    def _get_scaled_template(self, name: str) -> np.ndarray | None:
        if name in self._scaled_template_cache:
            return self._scaled_template_cache[name]

        tmpl = self._load_template(name)
        if tmpl is None:
            return None

        scale = self._global_scale if self._global_scale is not None else 1.0
        if abs(scale - 1.0) > _SCALE_IDENTITY_EPSILON:
            new_w = int(tmpl.shape[1] * scale)
            new_h = int(tmpl.shape[0] * scale)
            tmpl = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        self._scaled_template_cache[name] = tmpl
        return tmpl

    def _get_offset_scaled(self, name: str, offset: float) -> np.ndarray | None:
        if abs(offset) < _OFFSET_ZERO_EPSILON:
            return self._get_scaled_template(name)

        key = (name, offset)
        if key in self._offset_scaled_cache:
            return self._offset_scaled_cache[key]

        raw = self._load_template(name)
        if raw is None or self._global_scale is None:
            return None

        scale = self._global_scale + offset
        new_w = int(raw.shape[1] * scale)
        new_h = int(raw.shape[0] * scale)
        if new_w < _MIN_TEMPLATE_DIM or new_h < _MIN_TEMPLATE_DIM:
            return None

        scaled = cv2.resize(raw, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        self._offset_scaled_cache[key] = scaled
        return scaled

    def _get_small_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        ds = self._downsample_factor
        if ds <= 1:
            return frame_bgr
        fid = id(frame_bgr)
        if self._downsampled_frame_cache is not None and self._downsampled_frame_cache[0] == fid:
            return self._downsampled_frame_cache[1]
        small = cv2.resize(
            frame_bgr,
            (frame_bgr.shape[1] // ds, frame_bgr.shape[0] // ds),
            interpolation=cv2.INTER_AREA,
        )
        self._downsampled_frame_cache = (fid, small)
        return small

    # ------------------------------------------------------------------
    # Template finding
    # ------------------------------------------------------------------

    def find_template(
        self,
        frame_bgr: np.ndarray,
        template_name: str,
        threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
    ) -> MatchResult | None:
        with self._lock:
            return self._find_template_locked(frame_bgr, template_name, threshold)

    def _find_template_locked(
        self,
        frame_bgr: np.ndarray,
        template_name: str,
        threshold: float,
    ) -> MatchResult | None:
        if self._global_scale is None:
            log.warning("find_template called before calibration")
            return None

        t_start = time.monotonic()
        ds = self._downsample_factor
        small = self._get_small_frame(frame_bgr)
        fh, fw = small.shape[:2]
        scales_tried = 0

        for offset in _FIND_SCALE_OFFSETS:
            tmpl = self._get_offset_scaled(template_name, offset)
            if tmpl is None:
                continue

            if ds > 1:
                th_ds = tmpl.shape[0] // ds
                tw_ds = tmpl.shape[1] // ds
                if th_ds < _MIN_TEMPLATE_DIM_DS or tw_ds < _MIN_TEMPLATE_DIM_DS:
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
                log.debug(
                    "[TM] %-28s HIT  offset=%.2f conf=%.3f  "
                    "cv=%.0fms scales=%d total=%.0fms frame=%dx%d",
                    template_name,
                    offset,
                    max_val,
                    cv_ms,
                    scales_tried,
                    total_ms,
                    fw,
                    fh,
                )
                return MatchResult(cx, cy, float(max_val), tmpl.shape[1], tmpl.shape[0])

        total_ms = (time.monotonic() - t_start) * 1000
        log.debug(
            "[TM] %-28s MISS scales=%d total=%.0fms frame=%dx%d",
            template_name,
            scales_tried,
            total_ms,
            fw,
            fh,
        )
        return None

    def find_all_templates(
        self,
        frame_bgr: np.ndarray,
        template_name: str,
        threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
    ) -> list[MatchResult]:
        with self._lock:
            return self._find_all_locked(frame_bgr, template_name, threshold)

    def _find_all_locked(
        self,
        frame_bgr: np.ndarray,
        template_name: str,
        threshold: float,
    ) -> list[MatchResult]:
        tmpl = self._get_scaled_template(template_name)
        if tmpl is None:
            return []

        th, tw = tmpl.shape[:2]
        fh, fw = frame_bgr.shape[:2]
        if tw > fw or th > fh:
            return []

        result = cv2.matchTemplate(frame_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)

        matches: list[MatchResult] = []
        for pt_y, pt_x in zip(*locations, strict=False):
            cx = int(pt_x) + tw // 2
            cy = int(pt_y) + th // 2
            conf = float(result[pt_y, pt_x])
            matches.append(MatchResult(cx, cy, conf, tw, th))

        return _nms(matches, tw, th)

    def is_element_visible(self, frame_bgr: np.ndarray, template_name: str) -> bool:
        return self.find_template(frame_bgr, template_name) is not None

    def save_template(self, name: str, image: np.ndarray) -> str:
        os.makedirs(settings.TEMPLATES_DIR, exist_ok=True)
        filename = settings.TEMPLATE_NAMES.get(name, f"{name}.png")
        path = os.path.join(settings.TEMPLATES_DIR, filename)
        cv2.imwrite(path, image)
        log.info("Saved template '%s' → %s", name, path)
        self.clear_cache()
        return path


def _nms(matches: list[MatchResult], tw: int, th: int) -> list[MatchResult]:
    """Non-maximum suppression for overlapping detections."""
    if not matches:
        return []

    matches_sorted = sorted(matches, key=lambda m: m.confidence, reverse=True)
    kept: list[MatchResult] = []
    suppressed: set[int] = set()

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


# ------------------------------------------------------------------
# Default global instance and module-level convenience functions
# ------------------------------------------------------------------

_default = TemplateMatcher()


def clear_cache() -> None:
    """Flush the template image cache in the default matcher."""
    _default.clear_cache()


def calibrate_scale(frame_bgr: np.ndarray) -> float:
    """Auto-detect the UI scale from a game screenshot."""
    from ttr_bot.vision.template_calibration import calibrate_scale as _cal

    return _cal(_default, frame_bgr)


def find_template(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> MatchResult | None:
    """Return the best match for *template_name*, or ``None`` if below *threshold*."""
    return _default.find_template(frame_bgr, template_name, threshold)


def find_all_templates(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """Return all non-overlapping matches for *template_name* above *threshold*."""
    return _default.find_all_templates(frame_bgr, template_name, threshold)


def is_element_visible(frame_bgr: np.ndarray, template_name: str) -> bool:
    """Quick boolean check: is *template_name* visible in the frame?"""
    return _default.is_element_visible(frame_bgr, template_name)


def save_template(name: str, image: np.ndarray) -> str:
    """Write *image* as a new template PNG and return the file path."""
    return _default.save_template(name, image)
