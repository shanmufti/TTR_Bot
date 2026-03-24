"""Input simulation for TTR on macOS using pyautogui."""

from __future__ import annotations

import random
import time

import pyautogui

from ttr_bot.config import settings
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window, focus_window
from ttr_bot.utils.logger import log

pyautogui.PAUSE = settings.PYAUTOGUI_PAUSE
pyautogui.FAILSAFE = settings.PYAUTOGUI_FAILSAFE


_RETINA_SCALE = 2


def _to_screen(win: WindowInfo, wx: int, wy: int) -> tuple[int, int]:
    """Convert window-relative coordinates to absolute screen coordinates.

    Template matching runs on Retina-resolution captures (2x), while
    pyautogui and CGWindowBounds use logical (1x) coordinates.
    """
    return win.x + wx // _RETINA_SCALE, win.y + wy // _RETINA_SCALE


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


def fishing_cast(
    button_x: int,
    button_y: int,
    *,
    variance: int = 0,
    window: WindowInfo | None = None,
) -> None:
    """Perform a fishing cast with random direction: mouseDown → drag → mouseUp.

    Coordinates are window-relative (Retina). *variance* adds random offset.
    Drag direction = LEFT/RIGHT sets cast direction, DOWN sets cast distance.
    """
    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast: TTR window not found")
        return

    start_sx, start_sy = _to_screen(win, button_x, button_y)
    rand_x = random.randint(-variance, variance) if variance else 0
    end_sx = start_sx + rand_x
    end_sy = start_sy + settings.CAST_DRAG_DISTANCE

    log.info("fishing_cast: (%d,%d)→(%d,%d) drag=(%+d,%+d)", start_sx, start_sy, end_sx, end_sy, rand_x, settings.CAST_DRAG_DISTANCE)

    pyautogui.moveTo(start_sx, start_sy)
    pyautogui.mouseDown()
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.moveTo(end_sx, end_sy, duration=0.15)
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.mouseUp()


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
    log.info("fishing_cast_raw: (%d,%d)→(%d,%d) drag=(%+d,%+d)",
             btn_sx, btn_sy, end_sx, end_sy, drag_dx, drag_dy)
    pyautogui.moveTo(btn_sx, btn_sy)
    pyautogui.mouseDown()
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.moveTo(end_sx, end_sy, duration=0.15)
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.mouseUp()


def fishing_cast_at(
    button_x: int,
    button_y: int,
    target_x: int,
    target_y: int,
    *,
    window: WindowInfo | None = None,
) -> None:
    """Cast toward a specific fish shadow using the calibrated drag transform.

    All coordinates are in retina frame pixels (window-relative).
    The calibration maps the offset (target - button) to a screen-pixel
    drag vector.  Call ``core.cast_calibration.cast_calibration.load()``
    or run interactive calibration before using this.
    """
    from ttr_bot.core.cast_calibration import cast_calibration

    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast_at: TTR window not found")
        return

    if not cast_calibration.is_calibrated:
        log.warning("fishing_cast_at: no cast calibration — run Calibrate Cast first")
        return

    btn_sx, btn_sy = _to_screen(win, button_x, button_y)
    target_dx = float(target_x - button_x)
    target_dy = float(target_y - button_y)

    drag_dx, drag_dy = cast_calibration.compute_drag(target_dx, target_dy)

    end_sx = btn_sx + drag_dx
    end_sy = btn_sy + drag_dy

    log.info(
        "fishing_cast_at: offset=(%+.0f,%+.0f) → drag=(%+d,%+d) screen(%d,%d)→(%d,%d)",
        target_dx, target_dy, drag_dx, drag_dy, btn_sx, btn_sy, end_sx, end_sy,
    )

    pyautogui.moveTo(btn_sx, btn_sy)
    pyautogui.mouseDown()
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.moveTo(end_sx, end_sy, duration=0.15)
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.mouseUp()


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
