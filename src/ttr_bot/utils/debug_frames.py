"""Save annotated debug frames for vision pipeline inspection.

Enable by setting the env var ``TTR_DEBUG_FRAMES=1`` or calling
``enable()``.  Frames are written under ``DEBUG_OUTPUT_BASE_DIR/fishing/`` with
timestamps so they can be reviewed after a session.
"""

import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log

_DEBUG_DIR = Path(settings.DEBUG_OUTPUT_BASE_DIR) / "fishing"


class _DebugState:
    """Mutable singleton holding debug-frame configuration."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.enabled = os.environ.get("TTR_DEBUG_FRAMES", "0") == "1"
        self.session_dir: Path | None = None
        self.frame_counter = 0


_state = _DebugState()


def enable() -> None:
    """Turn on debug-frame saving for the current process."""
    with _state.lock:
        _state.enabled = True


def disable() -> None:
    """Turn off debug-frame saving."""
    with _state.lock:
        _state.enabled = False


def is_enabled() -> bool:
    """Return True if debug-frame saving is active."""
    return _state.enabled


def clear_pngs(directory: str | Path) -> None:
    """Remove all ``*.png`` files from *directory*."""
    d = Path(directory)
    if not d.is_dir():
        return
    for p in d.glob("*.png"):
        p.unlink(missing_ok=True)


def _get_session_dir() -> Path:
    if _state.session_dir is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        _state.session_dir = _DEBUG_DIR / ts
        _state.session_dir.mkdir(parents=True, exist_ok=True)
        log.info("Debug frames → %s", _state.session_dir)
    return _state.session_dir


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
    if not _state.enabled:
        return None

    _state.frame_counter += 1

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
    fname = f"{_state.frame_counter:03d}_{label}.png"
    path = d / fname
    cv2.imwrite(str(path), out)
    log.debug("debug frame saved: %s", path)
    return path
