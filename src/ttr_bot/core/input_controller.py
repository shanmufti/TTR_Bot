"""Input simulation for TTR on macOS using pyautogui."""

from __future__ import annotations

import math
import time

import pyautogui

from ttr_bot.config import settings
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window, focus_window
from ttr_bot.utils.logger import log

pyautogui.PAUSE = settings.PYAUTOGUI_PAUSE
pyautogui.FAILSAFE = settings.PYAUTOGUI_FAILSAFE


_RETINA_SCALE = 2
_DRAG_HOLD_S = settings.CAST_DRAG_HOLD_MS / 1000.0


def _to_screen(win: WindowInfo, wx: int, wy: int) -> tuple[int, int]:
    """Convert window-relative coordinates to absolute screen coordinates.

    Template matching runs on Retina-resolution captures (2x), while
    pyautogui and CGWindowBounds use logical (1x) coordinates.
    """
    return win.x + wx // _RETINA_SCALE, win.y + wy // _RETINA_SCALE


def _execute_drag(
    start_sx: int,
    start_sy: int,
    end_sx: int,
    end_sy: int,
) -> None:
    """Shared mouseDown → moveTo → mouseUp drag sequence."""
    pyautogui.moveTo(start_sx, start_sy)
    pyautogui.mouseDown()
    time.sleep(_DRAG_HOLD_S)
    pyautogui.moveTo(end_sx, end_sy, duration=0.15)
    time.sleep(_DRAG_HOLD_S)
    pyautogui.mouseUp()


def move_to(x: int, y: int, *, window: WindowInfo | None = None) -> None:
    """Move the cursor to window-relative (x, y)."""
    win = window or find_ttr_window()
    if win is None:
        log.warning("move_to: TTR window not found")
        return
    sx, sy = _to_screen(win, x, y)
    pyautogui.moveTo(sx, sy)


def click(x: int, y: int, *, window: WindowInfo | None = None) -> None:
    """Click at window-relative (x, y)."""
    win = window or find_ttr_window()
    if win is None:
        log.warning("click: TTR window not found")
        return
    sx, sy = _to_screen(win, x, y)
    pyautogui.click(sx, sy)


def click_screen(sx: int, sy: int) -> None:
    """Click at absolute screen coordinates."""
    pyautogui.click(sx, sy)


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
    btn_sx, btn_sy = _to_screen(win, button_x, button_y)
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
    _execute_drag(btn_sx, btn_sy, end_sx, end_sy)


_DEFAULT_POWER_BASE = 6.8
_DEFAULT_AIM_BASE = 3.0
_MIN_POWER = 40
_MAX_POWER = 200

_power_base: float = _DEFAULT_POWER_BASE
_aim_base_left: float = _DEFAULT_AIM_BASE
_aim_base_right: float = _DEFAULT_AIM_BASE
_aim_offset: float = 0.0


def reload_cast_params() -> None:
    """Load fitted cast params from disk, falling back to defaults."""
    global _power_base, _aim_base_left, _aim_base_right, _aim_offset
    from ttr_bot.core.cast_params import CastParams

    params = CastParams.load()
    if params is not None:
        _power_base = params.power_base
        _aim_base_left = params.aim_base
        _aim_base_right = params.aim_base_right or params.aim_base
        _aim_offset = params.aim_offset or 0.0
    else:
        _power_base = _DEFAULT_POWER_BASE
        _aim_base_left = _DEFAULT_AIM_BASE
        _aim_base_right = _DEFAULT_AIM_BASE
        _aim_offset = 0.0
    log.info(
        "Cast params: power=%.2f aim_left=%.2f aim_right=%.2f offset=%.1f",
        _power_base,
        _aim_base_left,
        _aim_base_right,
        _aim_offset,
    )


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

    btn_sx, btn_sy = _to_screen(win, button_x, button_y)

    offset_x = (target_x - button_x) / _RETINA_SCALE + _aim_offset
    offset_y = (target_y - button_y) / _RETINA_SCALE

    if offset_x > 0:
        sign_x = -1
        aim_coeff = _aim_base_right
    else:
        sign_x = 1
        aim_coeff = _aim_base_left
    drag_dx = int(sign_x * aim_coeff * math.sqrt(abs(offset_x)))

    distance = abs(offset_y)
    desired_mag = max(_MIN_POWER, min(_power_base * math.sqrt(distance), _MAX_POWER))

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
    _execute_drag(btn_sx, btn_sy, end_sx, end_sy)


def press_key(key: str, duration: float = 0.0) -> None:
    """Press a keyboard key. If *duration* > 0, hold it that long."""
    if duration > 0:
        pyautogui.keyDown(key)
        time.sleep(duration)
        pyautogui.keyUp(key)
    else:
        pyautogui.press(key)


def hold_key(key: str, seconds: float) -> None:
    """Hold a key down for *seconds*."""
    pyautogui.keyDown(key)
    time.sleep(seconds)
    pyautogui.keyUp(key)


def ensure_focused() -> bool:
    """Focus the TTR window, return True if successful."""
    return focus_window()
