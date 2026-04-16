"""Save annotated debug frames for vision pipeline inspection.

Enable by setting the env var ``TTR_DEBUG_FRAMES=1`` or calling
``enable()``.  Frames are written to ``data/_debug/fishing/`` with
timestamps so they can be reviewed after a session.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log

_lock = threading.Lock()
_enabled = os.environ.get("TTR_DEBUG_FRAMES", "0") == "1"
_debug_dir = Path(settings.DATA_DIR) / "_debug" / "fishing"
_session_dir: Path | None = None


def enable() -> None:
    """Turn on debug-frame saving for the current process."""
    global _enabled
    with _lock:
        _enabled = True


def disable() -> None:
    """Turn off debug-frame saving."""
    global _enabled
    with _lock:
        _enabled = False


def is_enabled() -> bool:
    """Return True if debug-frame saving is active."""
    return _enabled


def _get_session_dir() -> Path:
    global _session_dir
    if _session_dir is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        _session_dir = _debug_dir / ts
        _session_dir.mkdir(parents=True, exist_ok=True)
        log.info("Debug frames → %s", _session_dir)
    return _session_dir


_frame_counter = 0


def save(
    frame: np.ndarray,
    label: str,
    *,
    annotations: list[dict] | None = None,
) -> Path | None:
    """Save an annotated copy of *frame*.

    *label* becomes part of the filename (e.g. ``"001_pond"``).

    *annotations* is an optional list of drawing commands:
      - ``{"type": "circle", "center": (x,y), "radius": r, "color": (B,G,R)}``
      - ``{"type": "rect", "pt1": (x1,y1), "pt2": (x2,y2), "color": (B,G,R)}``
      - ``{"type": "text", "pos": (x,y), "text": "...", "color": (B,G,R)}``
      - ``{"type": "line", "pt1": (x,y), "pt2": (x,y), "color": (B,G,R)}``
    """
    if not _enabled:
        return None

    global _frame_counter
    _frame_counter += 1

    out = frame.copy()

    for ann in annotations or []:
        t = ann.get("type")
        color = ann.get("color", (0, 255, 0))
        thickness = ann.get("thickness", 2)
        if t == "circle":
            cv2.circle(out, ann["center"], ann.get("radius", 8), color, thickness)
        elif t == "rect":
            cv2.rectangle(out, ann["pt1"], ann["pt2"], color, thickness)
        elif t == "text":
            cv2.putText(
                out,
                ann["text"],
                ann["pos"],
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                thickness,
            )
        elif t == "line":
            cv2.line(out, ann["pt1"], ann["pt2"], color, thickness)

    d = _get_session_dir()
    fname = f"{_frame_counter:03d}_{label}.png"
    path = d / fname
    cv2.imwrite(str(path), out)
    log.debug("debug frame saved: %s", path)
    return path
