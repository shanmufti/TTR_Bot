"""Shared fixtures for TTR Bot tests."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture()
def blue_water_frame() -> np.ndarray:
    """800x600 BGR frame filled with teal/cyan water-like color.

    HSV roughly (90, 180, 160) which falls within default water detection range.
    BGR: B=200, G=160, R=60
    """
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    frame[:, :] = (200, 160, 60)  # BGR
    return frame


@pytest.fixture()
def dark_frame() -> np.ndarray:
    """800x600 near-black frame with no water."""
    return np.full((600, 800, 3), 20, dtype=np.uint8)


@pytest.fixture()
def pond_scene_frame() -> np.ndarray:
    """800x600 synthetic pond scene with water band in the middle.

    Top 20%: sky (light blue, high value)
    Middle 40%: water (teal, in HSV detection range)
    Bottom 40%: dock/ground (brown)
    """
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    # Sky (top 120px) - light blue, high brightness
    frame[:120, :] = (230, 200, 180)  # BGR
    # Water (120-360) - teal in water HSV range
    frame[120:360, :] = (200, 160, 60)  # BGR
    # Ground (360-600) - brown
    frame[360:, :] = (40, 60, 100)  # BGR
    return frame
