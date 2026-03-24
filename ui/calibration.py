"""Calibration — detect and lock TTR window bounds."""

from __future__ import annotations

from typing import NamedTuple



class CalibrationResult(NamedTuple):
    x: int
    y: int
    width: int
    height: int
