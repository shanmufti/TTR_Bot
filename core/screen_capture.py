"""macOS screen capture using Quartz CGWindowListCreateImage."""

from __future__ import annotations

import numpy as np
import Quartz
from Quartz import (
    CGRectNull,
    CGWindowListCreateImage,
    kCGWindowImageBoundsIgnoreFraming,
    kCGWindowImageDefault,
    kCGWindowListOptionIncludingWindow,
)

from core.window_manager import find_ttr_window, WindowInfo
from utils.logger import log


def _cgimage_to_numpy(cg_image) -> np.ndarray | None:
    """Convert a CGImage to a numpy BGR array (OpenCV format)."""
    if cg_image is None:
        return None

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)

    color_space = Quartz.CGColorSpaceCreateDeviceRGB()
    bytes_per_row = 4 * width
    buffer_size = bytes_per_row * height

    # Create a bitmap context and draw the image into it
    context = Quartz.CGBitmapContextCreate(
        None,
        width,
        height,
        8,  # bits per component
        bytes_per_row,
        color_space,
        Quartz.kCGImageAlphaPremultipliedFirst | Quartz.kCGBitmapByteOrder32Little,
    )
    if context is None:
        return None

    Quartz.CGContextDrawImage(context, Quartz.CGRectMake(0, 0, width, height), cg_image)

    # Extract pixel data from context
    data = Quartz.CGBitmapContextGetData(context)
    if data is None:
        return None

    # Data is BGRA (due to kCGBitmapByteOrder32Little + PremultipliedFirst)
    buf = (Quartz.c_void_p * 1)()  # noqa – not needed; use ctypes approach below
    import ctypes
    buf_ptr = ctypes.cast(int(data), ctypes.POINTER(ctypes.c_uint8 * buffer_size))
    arr = np.frombuffer(buf_ptr.contents, dtype=np.uint8).reshape((height, width, 4))

    # Drop alpha channel → BGR (OpenCV native)
    return arr[:, :, :3].copy()


def capture_window(window_info: WindowInfo | None = None) -> np.ndarray | None:
    """Capture the TTR game window as a numpy BGR array.

    If *window_info* is None, finds the window automatically.
    Returns None if the window is not found or capture fails.
    """
    if window_info is None:
        window_info = find_ttr_window()
    if window_info is None:
        log.warning("capture_window: TTR window not found")
        return None

    cg_image = CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        window_info.window_id,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageDefault,
    )
    if cg_image is None:
        log.warning("capture_window: CGWindowListCreateImage returned None")
        return None

    frame = _cgimage_to_numpy(cg_image)
    if frame is None:
        log.warning("capture_window: failed to convert CGImage to numpy")
    return frame


def capture_region(window_info: WindowInfo, x: int, y: int, w: int, h: int) -> np.ndarray | None:
    """Capture a sub-region of the game window.

    Coordinates are relative to the window's top-left corner.
    """
    full = capture_window(window_info)
    if full is None:
        return None
    return full[y : y + h, x : x + w].copy()
