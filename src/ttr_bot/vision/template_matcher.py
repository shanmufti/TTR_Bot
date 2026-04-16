"""OpenCV template matching for UI button detection.

Ported from ImageTemplateMatcher.cs / UIElementManager.cs in the reference bot.
"""

from __future__ import annotations

import os
import threading
import time
from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log


class MatchResult(NamedTuple):
    x: int  # center x of the match (window-relative)
    y: int  # center y of the match (window-relative)
    confidence: float
    width: int
    height: int


_COARSE_SCALE_RANGE = np.arange(0.8, 1.3, 0.1)
_FINE_STEP = 0.04
_FIND_SCALE_OFFSETS = np.array([0.0, -0.04, 0.04])

_MIN_CALIBRATION_CONF = 0.60
_MIN_CALIBRATION_CONF_RELAXED = 0.48

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
    # Calibration
    # ------------------------------------------------------------------

    @staticmethod
    def _match_at_scale(frame_bgr: np.ndarray, tmpl: np.ndarray, scale: float) -> float:
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

    def calibrate_scale(self, frame_bgr: np.ndarray) -> float:
        """Determine the window scale by matching a known template across scales."""
        with self._lock:
            return self._calibrate_scale_locked(frame_bgr)

    def _calibrate_scale_locked(self, frame_bgr: np.ndarray) -> float:
        self._scaled_template_cache.clear()

        t_cal = time.monotonic()
        fh, fw = frame_bgr.shape[:2]
        self._downsample_factor = 2 if fw >= 1800 else 1
        log.info("calibrate_scale: frame=%dx%d downsample=%dx", fw, fh, self._downsample_factor)

        overall_best_val = -1.0
        overall_best_scale = 1.0
        best_anchor = ""

        for anchor in _CALIBRATION_ANCHORS:
            tmpl = self._load_template(anchor)
            if tmpl is None:
                continue

            t_anchor = time.monotonic()
            anchor_best = -1.0
            anchor_scale = 1.0
            for scale in _COARSE_SCALE_RANGE:
                val = self._match_at_scale(frame_bgr, tmpl, scale)
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
            self._global_scale = None
            return -1.0

        t_fine = time.monotonic()
        tmpl = self._load_template(best_anchor)
        if tmpl is not None:
            fine_range = np.arange(
                overall_best_scale - 0.08,
                overall_best_scale + 0.08 + _FINE_STEP,
                _FINE_STEP,
            )
            for scale in fine_range:
                val = self._match_at_scale(frame_bgr, tmpl, scale)
                if val > overall_best_val:
                    overall_best_val = val
                    overall_best_scale = scale
        log.info("calibrate fine-tune: %.0fms", (time.monotonic() - t_fine) * 1000)

        if overall_best_val < _MIN_CALIBRATION_CONF_RELAXED:
            log.warning(
                "calibrate_scale FAILED: best conf=%.3f (need %.2f). "
                "Recapture HUD with tools/snapshot_game_state.py --promote-template",
                overall_best_val,
                _MIN_CALIBRATION_CONF_RELAXED,
            )
            self._global_scale = None
            return -1.0

        self._global_scale = overall_best_scale
        cal_ms = (time.monotonic() - t_cal) * 1000
        if overall_best_val < _MIN_CALIBRATION_CONF:
            log.warning(
                "calibrate_scale: relaxed accept anchor=%s scale=%.2f (conf=%.3f) %.0fms",
                best_anchor,
                overall_best_scale,
                overall_best_val,
                cal_ms,
            )
        else:
            log.info(
                "calibrate_scale: anchor=%s scale=%.2f (conf=%.3f) — locked (%.0fms)",
                best_anchor,
                overall_best_scale,
                overall_best_val,
                cal_ms,
            )
        return overall_best_scale

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
        if abs(scale - 1.0) > 0.01:
            new_w = int(tmpl.shape[1] * scale)
            new_h = int(tmpl.shape[0] * scale)
            tmpl = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        self._scaled_template_cache[name] = tmpl
        return tmpl

    def _get_offset_scaled(self, name: str, offset: float) -> np.ndarray | None:
        if abs(offset) < 1e-9:
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
        if new_w < 10 or new_h < 10:
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
    _default.clear_cache()


def calibrate_scale(frame_bgr: np.ndarray) -> float:
    return _default.calibrate_scale(frame_bgr)


def find_template(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> MatchResult | None:
    return _default.find_template(frame_bgr, template_name, threshold)


def find_all_templates(
    frame_bgr: np.ndarray,
    template_name: str,
    threshold: float = settings.TEMPLATE_MATCH_THRESHOLD,
) -> list[MatchResult]:
    return _default.find_all_templates(frame_bgr, template_name, threshold)


def is_element_visible(frame_bgr: np.ndarray, template_name: str) -> bool:
    return _default.is_element_visible(frame_bgr, template_name)


def save_template(name: str, image: np.ndarray) -> str:
    return _default.save_template(name, image)
