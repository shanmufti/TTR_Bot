"""macOS Quartz-based window manager for Toontown Rewritten."""

from __future__ import annotations

from typing import NamedTuple

import Quartz
from Cocoa import NSRunningApplication, NSApplicationActivateIgnoringOtherApps

from config.settings import GAME_WINDOW_TITLE
from utils.logger import log


class WindowInfo(NamedTuple):
    window_id: int
    pid: int
    x: int
    y: int
    width: int
    height: int


def find_ttr_window() -> WindowInfo | None:
    """Find the Toontown Rewritten window via CGWindowListCopyWindowInfo.

    Returns WindowInfo with the window ID, PID, and screen-space bounds,
    or None if the game window is not found.
    """
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    if window_list is None:
        return None

    for win in window_list:
        owner = win.get(Quartz.kCGWindowOwnerName, "")
        name = win.get(Quartz.kCGWindowName, "")
        if owner == GAME_WINDOW_TITLE or name == GAME_WINDOW_TITLE:
            bounds = win.get(Quartz.kCGWindowBounds, {})
            return WindowInfo(
                window_id=int(win[Quartz.kCGWindowNumber]),
                pid=int(win[Quartz.kCGWindowOwnerPID]),
                x=int(bounds.get("X", 0)),
                y=int(bounds.get("Y", 0)),
                width=int(bounds.get("Width", 0)),
                height=int(bounds.get("Height", 0)),
            )
    return None


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

    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("")
    for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(""):
        if app.processIdentifier() == info.pid:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            return True

    # Fallback: iterate all running apps
    workspace = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
    )
    for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(""):
        pass  # bundle ID unknown; try by PID below

    running = NSRunningApplication.runningApplicationsWithBundleIdentifier_("")
    # Use a broader approach: get all apps and match PID
    from AppKit import NSWorkspace
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.processIdentifier() == info.pid:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            return True

    log.warning("TTR process found but could not activate (PID %d)", info.pid)
    return False
