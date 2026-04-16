"""macOS Quartz-based window manager for Toontown Rewritten."""

import threading
from typing import NamedTuple

import Quartz
from Cocoa import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

from ttr_bot.config.settings import GAME_WINDOW_TITLE
from ttr_bot.utils.logger import log


class WindowInfo(NamedTuple):
    """Snapshot of a macOS window's position and size."""

    window_id: int
    pid: int
    x: int
    y: int
    width: int
    height: int


class _CalibrationState:
    """Thread-safe container for calibrated window bounds."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bounds: dict | None = None


_cal = _CalibrationState()


def set_calibrated_bounds(win: WindowInfo) -> None:
    """Lock the window bounds to a calibrated snapshot.

    Subsequent ``find_ttr_window`` calls will prefer the window with
    this ID, avoiding confusion when multiple game windows are open.
    """
    with _cal.lock:
        _cal.bounds = win._asdict()
    log.info(
        "Window bounds locked: %dx%d at (%d,%d)  wid=%s pid=%s",
        win.width,
        win.height,
        win.x,
        win.y,
        win.window_id,
        win.pid,
    )


def clear_calibrated_bounds() -> None:
    """Remove calibrated bounds, revert to auto-detection."""
    with _cal.lock:
        _cal.bounds = None


def find_ttr_window() -> WindowInfo | None:
    """Find the Toontown Rewritten window via CGWindowListCopyWindowInfo.

    When calibrated bounds include a *window_id*, returns that specific window
    so multiple open game windows don't cause the bot to flip between them.
    """
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    if window_list is None:
        return None

    cal = _cal.bounds
    locked_wid = (cal or {}).get("window_id")

    fallback = None
    for win in window_list:
        owner = win.get(Quartz.kCGWindowOwnerName, "")
        name = win.get(Quartz.kCGWindowName, "")
        if GAME_WINDOW_TITLE not in (owner, name):
            continue

        wid = int(win[Quartz.kCGWindowNumber])
        pid = int(win[Quartz.kCGWindowOwnerPID])
        bounds = win.get(Quartz.kCGWindowBounds, {})

        if cal:
            info = WindowInfo(
                window_id=wid,
                pid=pid,
                x=cal["x"],
                y=cal["y"],
                width=cal["width"],
                height=cal["height"],
            )
        else:
            info = WindowInfo(
                window_id=wid,
                pid=pid,
                x=int(bounds.get("X", 0)),
                y=int(bounds.get("Y", 0)),
                width=int(bounds.get("Width", 0)),
                height=int(bounds.get("Height", 0)),
            )

        if locked_wid is not None and wid == locked_wid:
            return info

        if fallback is None:
            fallback = info

    return fallback


def is_window_available() -> bool:
    """Return True if the TTR game window is currently visible."""
    return find_ttr_window() is not None


def focus_window() -> bool:
    """Bring the TTR window to the foreground.

    Returns True on success, False if the window/process is not found.
    """
    info = find_ttr_window()
    if info is None:
        log.warning("Cannot focus: TTR window not found")
        return False

    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(info.pid)
    if app is not None:
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        return True

    log.warning("TTR process found but could not activate (PID %d)", info.pid)
    return False
