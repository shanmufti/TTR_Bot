"""macOS screen capture using Quartz CGWindowListCreateImage."""

from __future__ import annotations

import numpy as np
import Quartz
import CoreFoundation
from Quartz import (
    CGRectNull,
    CGWindowListCreateImage,
    kCGWindowImageBoundsIgnoreFraming,
    kCGWindowImageDefault,
    kCGWindowListOptionIncludingWindow,
)

from ttr_bot.core.window_manager import find_ttr_window, WindowInfo
from ttr_bot.utils.logger import log


def _cgimage_to_numpy(cg_image) -> np.ndarray | None:
    """Convert a CGImage to a numpy BGR array (OpenCV format)."""
    if cg_image is None:
        return None

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)
    if width == 0 or height == 0:
        return None

    # Get raw pixel data via the image's data provider
    data_provider = Quartz.CGImageGetDataProvider(cg_image)
    if data_provider is None:
        return None

    cf_data = Quartz.CGDataProviderCopyData(data_provider)
    if cf_data is None:
        return None

    raw_bytes = CoreFoundation.CFDataGetBytes(
        cf_data, CoreFoundation.CFRangeMake(0, CoreFoundation.CFDataGetLength(cf_data)), None
    )
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)

    bpp = Quartz.CGImageGetBitsPerPixel(cg_image) // 8  # bytes per pixel
    stride = Quartz.CGImageGetBytesPerRow(cg_image)

    # Reshape using stride (may include row padding)
    if stride == width * bpp:
        arr = arr.reshape((height, width, bpp))
    else:
        arr = arr.reshape((height, stride))
        arr = arr[:, : width * bpp].reshape((height, width, bpp))

    # The default macOS bitmap order is BGRA — keep BGR, drop alpha
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
