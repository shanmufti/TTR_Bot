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


def _to_screen(win: WindowInfo, wx: int, wy: int) -> tuple[int, int]:
    """Convert window-relative coordinates to absolute screen coordinates."""
    return win.x + wx, win.y + wy


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
    """Perform a fishing cast: mouseDown on the red button, drag down, mouseUp.

    Coordinates are window-relative. *variance* adds random pixel offset.
    Replicates the reference bot's DoFishingClick: press → hold 500ms →
    drag 150px down → hold 500ms → release.
    """
    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast: TTR window not found")
        return

    rand_x = random.randint(-variance, variance) if variance else 0
    rand_y = random.randint(-variance, variance) if variance else 0

    start_sx, start_sy = _to_screen(win, button_x + rand_x, button_y + rand_y)
    end_sy = start_sy + settings.CAST_DRAG_DISTANCE

    log.debug("fishing_cast: (%d,%d) → drag to (%d,%d)", start_sx, start_sy, start_sx, end_sy)

    pyautogui.moveTo(start_sx, start_sy)
    pyautogui.mouseDown()
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.moveTo(start_sx, end_sy, duration=0.1)
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
    """Cast toward a specific target (for auto-detect aiming).

    Coordinates are window-relative.
    """
    win = window or find_ttr_window()
    if win is None:
        log.warning("fishing_cast_at: TTR window not found")
        return

    btn_sx, btn_sy = _to_screen(win, button_x, button_y)
    tgt_sx, tgt_sy = _to_screen(win, target_x, target_y)

    log.debug("fishing_cast_at: button(%d,%d) → target(%d,%d)", btn_sx, btn_sy, tgt_sx, tgt_sy)

    pyautogui.moveTo(btn_sx, btn_sy)
    pyautogui.mouseDown()
    time.sleep(settings.CAST_DRAG_HOLD_MS / 1000.0)
    pyautogui.moveTo(tgt_sx, tgt_sy, duration=0.1)
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
