"""Cast calibration — fully automatic drag-vector learning.

The bot casts 3 times with known drag vectors, detects where the bobber
lands via frame differencing, and fits a linear transform that maps
(shadow_offset in retina px) → (drag_vector in screen px).
"""

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
    (0, 80),  # short straight
    (-60, 120),  # medium left
    (60, 120),  # medium right
]


class CalibrationSample(NamedTuple):
    """One calibration cast: known drag vector paired with observed landing."""

    drag_dx: float
    drag_dy: float
    land_dx: float
    land_dy: float


def detect_bobber(
    before: np.ndarray,
    after: np.ndarray,
    pond_x: int,
    pond_y: int,
    pond_w: int,
    pond_h: int,
    *,
    drag_label: str = "",
) -> tuple[int, int] | None:
    """Detect the bobber landing position via frame differencing.

    Compares before-cast and after-cast frames within the pond region.
    The bobber is the largest bright new blob in the diff.
    Returns (cx, cy) in full-frame retina coordinates, or None.
    """
    from ttr_bot.utils import debug_frames as dbg

    if before.shape != after.shape:
        log.warning("detect_bobber: frame shape mismatch")
        return None

    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)

    y1, y2 = pond_y, pond_y + pond_h
    x1, x2 = pond_x, pond_x + pond_w
    h, w = gray_before.shape
    y1, y2 = max(0, y1), min(h, y2)
    x1, x2 = max(0, x1), min(w, x2)

    roi_before = gray_before[y1:y2, x1:x2]
    roi_after = gray_after[y1:y2, x1:x2]

    diff = cv2.absdiff(roi_after, roi_before)
    diff = cv2.GaussianBlur(diff, (7, 7), 0)
    _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    thresh = cv2.dilate(thresh, kernel, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if dbg.is_enabled():
        dbg.save(
            before,
            f"cal_{drag_label}_before",
            annotations=[
                {
                    "type": "rect",
                    "pt1": (x1, y1),
                    "pt2": (x2, y2),
                    "color": (0, 255, 0),
                    "thickness": 1,
                },
            ],
        )
        dbg.save(
            after,
            f"cal_{drag_label}_after",
            annotations=[
                {
                    "type": "rect",
                    "pt1": (x1, y1),
                    "pt2": (x2, y2),
                    "color": (0, 255, 0),
                    "thickness": 1,
                },
            ],
        )
        diff_vis = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        full_diff = np.zeros_like(before)
        full_diff[y1:y2, x1:x2] = diff_vis
        diff_anns: list[dict] = [
            {
                "type": "rect",
                "pt1": (x1, y1),
                "pt2": (x2, y2),
                "color": (0, 255, 0),
                "thickness": 1,
            },
        ]
        for c in contours:
            area_c = cv2.contourArea(c)
            m = cv2.moments(c)
            if m["m00"] > 0:
                bx = int(m["m10"] / m["m00"]) + x1
                by = int(m["m01"] / m["m00"]) + y1
                diff_anns.append(
                    {"type": "circle", "center": (bx, by), "radius": 8, "color": (0, 255, 255)}
                )
                diff_anns.append(
                    {
                        "type": "text",
                        "pos": (bx + 10, by),
                        "text": f"a={area_c}",
                        "color": (0, 255, 255),
                        "thickness": 1,
                    }
                )
        dbg.save(full_diff, f"cal_{drag_label}_diff", annotations=diff_anns)

    if not contours:
        log.warning("detect_bobber: no changed blobs found in pond region")
        return None

    _BOBBER_MIN_AREA = 50
    _BOBBER_MAX_AREA = 5000

    valid = [c for c in contours if _BOBBER_MIN_AREA <= cv2.contourArea(c) <= _BOBBER_MAX_AREA]
    if not valid:
        areas = sorted([int(cv2.contourArea(c)) for c in contours], reverse=True)[:5]
        log.warning(
            "detect_bobber: no blobs in area range %d-%d (top areas: %s)",
            _BOBBER_MIN_AREA,
            _BOBBER_MAX_AREA,
            areas,
        )
        return None

    best = max(valid, key=cv2.contourArea)
    area = cv2.contourArea(best)

    M = cv2.moments(best)
    if M["m00"] == 0:
        return None
    cx = int(M["m10"] / M["m00"]) + x1
    cy = int(M["m01"] / M["m00"]) + y1

    if dbg.is_enabled():
        dbg.save(
            after,
            f"cal_{drag_label}_landing",
            annotations=[
                {
                    "type": "circle",
                    "center": (cx, cy),
                    "radius": 15,
                    "color": (0, 0, 255),
                    "thickness": 3,
                },
                {
                    "type": "text",
                    "pos": (cx + 18, cy),
                    "text": f"bobber ({cx},{cy}) area={area}",
                    "color": (0, 0, 255),
                    "thickness": 2,
                },
            ],
        )

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
            sample.drag_dx,
            sample.drag_dy,
            sample.land_dx,
            sample.land_dy,
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
        return round(drag[0]), round(drag[1])

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

    def load_default(self) -> None:
        """Apply a reasonable default transform.

        The casting mechanic: drag DOWN = more power (casts further forward),
        drag LEFT/RIGHT = aim direction.  Shadow offsets are in retina coords
        (2x screen), and shadow-above-button means negative dy, but we need
        positive drag_dy (down) to cast forward.  So Y is flipped and scaled.
        """
        if self.is_calibrated:
            return
        self._matrix = np.array(
            [
                [0.3, 0.0],
                [0.0, -0.3],
            ]
        )
        log.info("Cast calibration: using default transform (0.3x, Y-flip)")


# Global instance
cast_calibration = CastCalibration()
