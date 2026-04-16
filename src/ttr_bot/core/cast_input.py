"""Fishing-specific cast math: power/aim geometry and drag execution."""

import math

from ttr_bot.core.input_controller import _RETINA_SCALE, execute_drag, to_screen
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.utils.logger import log

_DEFAULT_POWER_BASE = 6.8
_DEFAULT_AIM_BASE = 3.0
_MIN_POWER = 40
_MAX_POWER = 200


class _CastState:
    """Mutable container for loaded cast parameters."""

    def __init__(self) -> None:
        self.power_base: float = _DEFAULT_POWER_BASE
        self.aim_base_left: float = _DEFAULT_AIM_BASE
        self.aim_base_right: float = _DEFAULT_AIM_BASE
        self.aim_offset: float = 0.0


_cast = _CastState()


def reload_cast_params() -> None:
    """Load fitted cast params from disk, falling back to defaults."""
    from ttr_bot.core.cast_params import CastParams

    params = CastParams.load()
    if params is not None:
        _cast.power_base = params.power_base
        _cast.aim_base_left = params.aim_base
        _cast.aim_base_right = params.aim_base_right or params.aim_base
        _cast.aim_offset = params.aim_offset or 0.0
    else:
        _cast.power_base = _DEFAULT_POWER_BASE
        _cast.aim_base_left = _DEFAULT_AIM_BASE
        _cast.aim_base_right = _DEFAULT_AIM_BASE
        _cast.aim_offset = 0.0
    log.info(
        "Cast params: power=%.2f aim_left=%.2f aim_right=%.2f offset=%.1f",
        _cast.power_base,
        _cast.aim_base_left,
        _cast.aim_base_right,
        _cast.aim_offset,
    )


def fishing_cast_raw(
    button_x: int,
    button_y: int,
    drag_dx: int,
    drag_dy: int,
    *,
    window: WindowInfo | None = None,
) -> None:
    """Cast with an explicit drag vector (screen px) from the button position.

    Used by auto-calibration to cast with known drag values.
    """
    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast_raw: TTR window not found")
        return
    btn_sx, btn_sy = to_screen(win, button_x, button_y)
    end_sx = btn_sx + drag_dx
    end_sy = btn_sy + drag_dy
    log.info(
        "fishing_cast_raw: (%d,%d)→(%d,%d) drag=(%+d,%+d)",
        btn_sx,
        btn_sy,
        end_sx,
        end_sy,
        drag_dx,
        drag_dy,
    )
    execute_drag(btn_sx, btn_sy, end_sx, end_sy)


def fishing_cast_at(
    button_x: int,
    button_y: int,
    target_x: int,
    target_y: int,
    *,
    window: WindowInfo | None = None,
) -> None:
    """Cast toward a specific fish shadow using sqrt-scaled geometry.

    All coordinates are in retina frame pixels (window-relative).
    TTR casting: drag DOWN from button = power, LEFT/RIGHT = aim.
    The game amplifies power non-linearly, so we use sqrt to compensate.
    """
    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast_at: TTR window not found")
        return

    btn_sx, btn_sy = to_screen(win, button_x, button_y)

    offset_x = (target_x - button_x) / _RETINA_SCALE + _cast.aim_offset
    offset_y = (target_y - button_y) / _RETINA_SCALE

    if offset_x > 0:
        sign_x = -1
        aim_coeff = _cast.aim_base_right
    else:
        sign_x = 1
        aim_coeff = _cast.aim_base_left
    drag_dx = int(sign_x * aim_coeff * math.sqrt(abs(offset_x)))

    distance = abs(offset_y)
    desired_mag = max(_MIN_POWER, min(_cast.power_base * math.sqrt(distance), _MAX_POWER))

    dx_sq = drag_dx * drag_dx
    mag_sq = desired_mag * desired_mag
    drag_dy = int(math.sqrt(mag_sq - dx_sq)) if mag_sq > dx_sq else _MIN_POWER

    end_sx = btn_sx + drag_dx
    end_sy = btn_sy + drag_dy

    log.info(
        "fishing_cast_at: offset_scr=(%+.0f,%+.0f) drag=(%+d,+%d) mag=%.0f screen(%d,%d)->(%d,%d)",
        offset_x,
        offset_y,
        drag_dx,
        drag_dy,
        desired_mag,
        btn_sx,
        btn_sy,
        end_sx,
        end_sy,
    )
    execute_drag(btn_sx, btn_sy, end_sx, end_sy)
