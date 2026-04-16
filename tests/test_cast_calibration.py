"""Tests for the cast calibration transform math."""

import numpy as np
import pytest

from ttr_bot.core.cast_calibration import CalibrationSample, CastCalibration


class TestCastCalibration:
    def test_initially_not_calibrated(self):
        cal = CastCalibration()
        assert cal.is_calibrated is False
        assert cal.sample_count == 0

    def test_add_sample(self):
        cal = CastCalibration()
        cal.add_sample(CalibrationSample(0, 80, 0, -240))
        assert cal.sample_count == 1

    def test_fit_requires_minimum_samples(self):
        cal = CastCalibration()
        cal.add_sample(CalibrationSample(0, 80, 0, -240))
        assert cal.fit() is False

    def test_fit_with_sufficient_samples(self):
        cal = CastCalibration()
        cal.add_sample(CalibrationSample(0, 80, 0, -240))
        cal.add_sample(CalibrationSample(-60, 120, 180, -360))
        cal.add_sample(CalibrationSample(60, 120, -180, -360))
        assert cal.fit() is True
        assert cal.is_calibrated is True

    def test_compute_drag_raises_when_not_fitted(self):
        cal = CastCalibration()
        with pytest.raises(RuntimeError, match="not fitted"):
            cal.compute_drag(100, -200)

    def test_compute_drag_returns_ints(self):
        cal = CastCalibration()
        cal.add_sample(CalibrationSample(0, 80, 0, -240))
        cal.add_sample(CalibrationSample(-60, 120, 180, -360))
        cal.add_sample(CalibrationSample(60, 120, -180, -360))
        cal.fit()
        dx, dy = cal.compute_drag(100.0, -200.0)
        assert isinstance(dx, (int, np.integer))
        assert isinstance(dy, (int, np.integer))

    def test_roundtrip_identity(self):
        """If we set the matrix to identity, drag == target offset."""
        cal = CastCalibration()
        cal._matrix = np.eye(2)
        dx, dy = cal.compute_drag(50, -100)
        assert dx == 50
        assert dy == -100

    def test_reset_clears_state(self):
        cal = CastCalibration()
        cal.add_sample(CalibrationSample(0, 80, 0, -240))
        cal.add_sample(CalibrationSample(-60, 120, 180, -360))
        cal.fit()
        cal.reset()
        assert cal.is_calibrated is False
        assert cal.sample_count == 0

    def test_load_default_only_when_uncalibrated(self):
        cal = CastCalibration()
        cal.add_sample(CalibrationSample(0, 80, 0, -240))
        cal.add_sample(CalibrationSample(-60, 120, 180, -360))
        cal.fit()
        matrix_before = cal._matrix.copy()
        cal.load_default()
        np.testing.assert_array_equal(cal._matrix, matrix_before)

    def test_load_default_sets_matrix(self):
        cal = CastCalibration()
        assert not cal.is_calibrated
        cal.load_default()
        assert cal.is_calibrated
