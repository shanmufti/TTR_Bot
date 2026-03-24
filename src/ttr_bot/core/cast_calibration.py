"""Cast calibration — fully automatic drag-vector learning.

The bot casts 3 times with known drag vectors, detects where the bobber
lands via frame differencing, and fits a linear transform that maps
(shadow_offset in retina px) → (drag_vector in screen px).
"""

from __future__ import annotations

import json
import os
from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.utils.logger import log

_CALIBRATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "cast_calibration.json"
)

# Drag vectors (screen px) used during calibration casts
CALIBRATION_DRAGS = [
    (0, 80),       # short straight
    (-60, 120),    # medium left
    (60, 120),     # medium right
]


class CalibrationSample(NamedTuple):
    drag_dx: float    # known drag x (screen px)
    drag_dy: float    # known drag y (screen px)
    land_dx: float    # detected bobber x offset from button (retina frame px)
    land_dy: float    # detected bobber y offset from button (retina frame px)


def detect_bobber(
    before: np.ndarray,
    after: np.ndarray,
    pond_x: int,
    pond_y: int,
    pond_w: int,
    pond_h: int,
) -> tuple[int, int] | None:
    """Detect the bobber landing position via frame differencing.

    Compares before-cast and after-cast frames within the pond region.
    The bobber is the largest bright new blob in the diff.
    Returns (cx, cy) in full-frame retina coordinates, or None.
    """
    if before.shape != after.shape:
        log.warning("detect_bobber: frame shape mismatch")
        return None

    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)

    # Crop to pond region
    y1, y2 = pond_y, pond_y + pond_h
    x1, x2 = pond_x, pond_x + pond_w
    h, w = gray_before.shape
    y1, y2 = max(0, y1), min(h, y2)
    x1, x2 = max(0, x1), min(w, x2)

    roi_before = gray_before[y1:y2, x1:x2]
    roi_after = gray_after[y1:y2, x1:x2]

    diff = cv2.absdiff(roi_after, roi_before)

    # Blur to suppress noise, then threshold for bright changes
    diff = cv2.GaussianBlur(diff, (7, 7), 0)
    _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

    # Clean up with morphological ops
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    thresh = cv2.dilate(thresh, kernel, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        log.warning("detect_bobber: no changed blobs found in pond region")
        return None

    # Pick the largest blob (bobber + splash are the dominant change)
    best = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(best)
    if area < 20:
        log.warning("detect_bobber: largest blob too small (area=%d)", area)
        return None

    M = cv2.moments(best)
    if M["m00"] == 0:
        return None
    cx = int(M["m10"] / M["m00"]) + x1
    cy = int(M["m01"] / M["m00"]) + y1

    log.info("detect_bobber: landing at (%d,%d) blob_area=%d", cx, cy, area)
    return cx, cy


class CastCalibration:
    """Stores and applies a learned drag transform.

    Calibration records: drag_vector → landing_offset (from button).
    For casting we need the inverse: target_offset → drag_vector.
    """

    def __init__(self) -> None:
        self._samples: list[CalibrationSample] = []
        self._matrix: np.ndarray | None = None  # 2x2: target_offset → drag

    @property
    def is_calibrated(self) -> bool:
        return self._matrix is not None

    def reset(self) -> None:
        self._samples.clear()
        self._matrix = None

    def add_sample(self, sample: CalibrationSample) -> None:
        self._samples.append(sample)
        log.info(
            "Cast cal sample: drag=(%+.0f,%+.0f) → landing_offset=(%+.0f,%+.0f)",
            sample.drag_dx, sample.drag_dy, sample.land_dx, sample.land_dy,
        )

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def fit(self) -> bool:
        """Fit the transform from collected samples.

        We know: landing_offset = M_fwd @ drag  (forward mapping).
        We need: drag = M_inv @ target_offset    (inverse mapping).
        """
        if len(self._samples) < 2:
            log.warning("Need at least 2 calibration samples, have %d", len(self._samples))
            return False

        # A = drag vectors, B = landing offsets
        A = np.array([[s.drag_dx, s.drag_dy] for s in self._samples])
        B = np.array([[s.land_dx, s.land_dy] for s in self._samples])

        # Solve for M_fwd: B = A @ M_fwd^T  →  M_fwd^T = lstsq(A, B)
        result, *_ = np.linalg.lstsq(A, B, rcond=None)
        m_fwd = result.T  # 2x2: landing = M_fwd @ drag

        # Invert to get: drag = M_inv @ target_offset
        try:
            self._matrix = np.linalg.inv(m_fwd)
        except np.linalg.LinAlgError:
            log.warning("Cast calibration: forward matrix is singular, cannot invert")
            return False

        log.info("Cast calibration fitted:\n  M_fwd=\n%s\n  M_inv=\n%s", m_fwd, self._matrix)
        return True

    def compute_drag(self, target_dx: float, target_dy: float) -> tuple[int, int]:
        """Map a target offset (shadow - button, retina px) to a drag vector (screen px)."""
        if self._matrix is None:
            raise RuntimeError("Cast calibration not fitted")
        offset = np.array([target_dx, target_dy])
        drag = self._matrix @ offset
        return int(round(drag[0])), int(round(drag[1]))

    def save(self) -> None:
        os.makedirs(os.path.dirname(_CALIBRATION_FILE), exist_ok=True)
        if self._matrix is None:
            return
        data = {
            "matrix": self._matrix.tolist(),
            "samples": [s._asdict() for s in self._samples],
        }
        with open(_CALIBRATION_FILE, "w") as f:
            json.dump(data, f, indent=2)
        log.info("Cast calibration saved to %s", _CALIBRATION_FILE)

    def load(self) -> bool:
        if not os.path.isfile(_CALIBRATION_FILE):
            return False
        try:
            with open(_CALIBRATION_FILE) as f:
                data = json.load(f)
            self._matrix = np.array(data["matrix"])
            self._samples = [CalibrationSample(**s) for s in data.get("samples", [])]
            log.info("Cast calibration loaded: matrix=\n%s", self._matrix)
            return True
        except Exception:
            log.exception("Failed to load cast calibration")
            return False


# Global instance
cast_calibration = CastCalibration()
