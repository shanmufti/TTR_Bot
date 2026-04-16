"""Input simulation for TTR on macOS using pyautogui."""

import time

import pyautogui

from ttr_bot.config import settings
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window, focus_window
from ttr_bot.utils.logger import log

pyautogui.PAUSE = settings.PYAUTOGUI_PAUSE
pyautogui.FAILSAFE = settings.PYAUTOGUI_FAILSAFE


def _detect_retina_scale() -> int:
    """Return the macOS backing scale factor (2 on Retina, 1 otherwise)."""
    try:
        from AppKit import NSScreen

        main = NSScreen.mainScreen()
        if main is not None:
            return int(main.backingScaleFactor())
    except Exception:
        log.debug("Could not detect Retina scale, using default")
    return settings.RETINA_SCALE


_RETINA_SCALE = _detect_retina_scale()
_DRAG_HOLD_S = settings.CAST_DRAG_HOLD_MS / 1000.0


def to_screen(win: WindowInfo, wx: int, wy: int) -> tuple[int, int]:
    """Convert window-relative coordinates to absolute screen coordinates.

    Template matching runs on Retina-resolution captures (2x), while
    pyautogui and CGWindowBounds use logical (1x) coordinates.
    """
    return win.x + wx // _RETINA_SCALE, win.y + wy // _RETINA_SCALE


def execute_drag(
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
    sx, sy = to_screen(win, x, y)
    pyautogui.moveTo(sx, sy)


def click(x: int, y: int, *, window: WindowInfo | None = None) -> None:
    """Click at window-relative (x, y)."""
    win = window or find_ttr_window()
    if win is None:
        log.warning("click: TTR window not found")
        return
    sx, sy = to_screen(win, x, y)
    pyautogui.click(sx, sy)


def click_screen(sx: int, sy: int) -> None:
    """Click at absolute screen coordinates."""
    pyautogui.click(sx, sy)


def press_key(key: str, duration: float = 0.0) -> None:
    """Press a keyboard key. If *duration* > 0, hold it that long."""
    if duration > 0:
        pyautogui.keyDown(key)
        time.sleep(duration)
        pyautogui.keyUp(key)
    else:
        pyautogui.press(key)


def ensure_focused() -> bool:
    """Focus the TTR window, return True if successful."""
    return focus_window()
