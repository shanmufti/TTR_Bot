"""Calibration — detect and lock TTR window bounds."""

from typing import NamedTuple


class CalibrationResult(NamedTuple):
    """Window bounds returned after a successful calibration."""

    x: int
    y: int
    width: int
    height: int
