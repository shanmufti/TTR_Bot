"""Input simulation for TTR on macOS using pyautogui."""

from __future__ import annotations

import random
import time

import pyautogui

from config import settings
from core.window_manager import WindowInfo, find_ttr_window, focus_window
from utils.logger import log

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

    log.debug("fishing_cast: (%d,%d) → (%d,%d)", start_sx, start_sy, end_sx, end_sy)

    pyautogui.moveTo(start_sx, start_sy)
    pyautogui.mouseDown()
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.moveTo(end_sx, end_sy, duration=0.15)
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.mouseUp()


_MIN_DRAG_DOWN = 80
_MAX_DRAG_DOWN = 160
_MAX_DRAG_HORIZ = 150


def fishing_cast_at(
    button_x: int,
    button_y: int,
    target_x: int,
    target_y: int,
    pond_x: int,
    pond_y: int,
    pond_w: int,
    pond_h: int,
    *,
    window: WindowInfo | None = None,
) -> None:
    """Cast toward a specific fish shadow using pond-relative positioning.

    *frac_forward*: 0 = shadow at pond bottom (near toon), 1 = far edge.
    *frac_horiz*:  -1 = far left, 0 = center, +1 = far right.
    These fractions are mapped to drag distance and direction
    regardless of window size.
    """
    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast_at: TTR window not found")
        return

    btn_sx, btn_sy = _to_screen(win, button_x, button_y)

    frac_forward = 1.0 - (target_y - pond_y) / max(1, pond_h)
    frac_forward = max(0.0, min(1.0, frac_forward))

    pond_cx = pond_x + pond_w // 2
    frac_horiz = (target_x - pond_cx) / max(1, pond_w // 2)
    frac_horiz = max(-1.0, min(1.0, frac_horiz))

    drag_down = int(_MIN_DRAG_DOWN + frac_forward * (_MAX_DRAG_DOWN - _MIN_DRAG_DOWN))
    drag_right = int(-frac_horiz * _MAX_DRAG_HORIZ)

    end_sx = btn_sx + drag_right
    end_sy = btn_sy + drag_down

    log.debug(
        "fishing_cast_at: fwd=%.2f horiz=%.2f → drag(%+d,%+d)",
        frac_forward, frac_horiz, drag_right, drag_down,
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
