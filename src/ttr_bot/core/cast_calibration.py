"""Cast calibration — fully automatic drag-vector learning.

The bot casts 3 times with known drag vectors, detects where the bobber
lands via frame differencing, and fits a linear transform that maps
(shadow_offset in retina px) → (drag_vector in screen px).
"""

import json
import os
from dataclasses import asdict, dataclass

import numpy as np

from ttr_bot.core.errors import CalibrationNotFittedError
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


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    """One calibration cast: known drag vector paired with observed landing."""

    drag_dx: float
    drag_dy: float
    land_dx: float
    land_dy: float


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
        min_samples = 2
        if len(self._samples) < min_samples:
            log.warning(
                "Need at least %d calibration samples, have %d",
                min_samples,
                len(self._samples),
            )
            return False

        drags = np.array([[s.drag_dx, s.drag_dy] for s in self._samples])
        landings = np.array([[s.land_dx, s.land_dy] for s in self._samples])

        # Solve for M_fwd: landings = drags @ M_fwd^T
        result, *_ = np.linalg.lstsq(drags, landings, rcond=None)
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
            raise CalibrationNotFittedError
        offset = np.array([target_dx, target_dy])
        drag = self._matrix @ offset
        return round(drag[0]), round(drag[1])

    def save(self) -> None:
        os.makedirs(os.path.dirname(_CALIBRATION_FILE), exist_ok=True)
        if self._matrix is None:
            return
        data = {
            "matrix": self._matrix.tolist(),
            "samples": [asdict(s) for s in self._samples],
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
        except Exception:
            log.exception("Failed to load cast calibration")
            return False
        else:
            return True

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
