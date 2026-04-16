"""Cast curve fitting: CastSample dataclass and fit_cast_params().

Extracted from cast_recorder so recording and fitting are decoupled.
"""

import math
from dataclasses import dataclass

import numpy as np

from ttr_bot.config import settings
from ttr_bot.core.cast_params import CastParams
from ttr_bot.utils.logger import log

_RETINA_SCALE = settings.RETINA_SCALE

_MIN_DRAG_MAGNITUDE = 30
_MIN_USABLE_SAMPLES = 2
_MIN_OFFSET_PX = 10
_DEFAULT_AIM_FALLBACK = 3.0


@dataclass(slots=True)
class CastSample:
    """Raw observation from a single user-performed cast."""

    button_x: int
    button_y: int
    target_x: int
    target_y: int
    bobber_x: int
    bobber_y: int
    drag_dx: float
    drag_dy: float


def fit_cast_params(samples: list[CastSample]) -> CastParams | None:
    """Fit power_base and aim_base from recorded cast samples.

    Model: drag_dy = power_base * sqrt(abs(offset_y))
           drag_dx = aim_base * sqrt(abs(offset_x)) * sign(offset_x)
    """
    usable = [
        s
        for s in samples
        if math.hypot(s.drag_dx, s.drag_dy) >= _MIN_DRAG_MAGNITUDE and s.drag_dy > 0
    ]
    if len(usable) < _MIN_USABLE_SAMPLES:
        log.warning(
            "Need %d+ usable samples (drag >= %dpx), have %d of %d",
            _MIN_USABLE_SAMPLES,
            _MIN_DRAG_MAGNITUDE,
            len(usable),
            len(samples),
        )
        return None

    power_estimates = []
    aim_estimates = []

    for s in usable:
        offset_y = abs(s.target_y - s.button_y) / _RETINA_SCALE
        offset_x = abs(s.target_x - s.button_x) / _RETINA_SCALE

        if offset_y > _MIN_OFFSET_PX:
            pb = abs(s.drag_dy) / math.sqrt(offset_y)
            power_estimates.append(pb)

        if offset_x > _MIN_OFFSET_PX:
            ab = abs(s.drag_dx) / math.sqrt(offset_x)
            aim_estimates.append(ab)

    if not power_estimates:
        log.warning("No valid power samples")
        return None

    power_base = float(np.median(power_estimates))
    aim_base = float(np.median(aim_estimates)) if aim_estimates else _DEFAULT_AIM_FALLBACK

    log.info(
        "Fitted cast params: power_base=%.2f (from %d samples), aim_base=%.2f (from %d samples)",
        power_base,
        len(power_estimates),
        aim_base,
        len(aim_estimates),
    )

    for i, s in enumerate(usable):
        off_x = (s.target_x - s.button_x) / _RETINA_SCALE
        off_y = (s.target_y - s.button_y) / _RETINA_SCALE
        log.info(
            "  sample %d: offset=(%+.0f,%+.0f) drag=(%+.0f,%+.0f) est_power=%.1f est_aim=%.1f",
            i,
            off_x,
            off_y,
            s.drag_dx,
            s.drag_dy,
            abs(s.drag_dy) / max(1, math.sqrt(abs(off_y))) if abs(off_y) > _MIN_OFFSET_PX else 0,
            abs(s.drag_dx) / max(1, math.sqrt(abs(off_x))) if abs(off_x) > _MIN_OFFSET_PX else 0,
        )

    params = CastParams(power_base=round(power_base, 2), aim_base=round(aim_base, 2))
    params.save()
    return params
