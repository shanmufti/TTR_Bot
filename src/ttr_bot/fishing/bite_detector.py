"""Bite detection and dialog dismissal — pure functions with no class dependency.

Extracted from FishingBot so they can be tested and reused independently.
"""

import enum
import threading
import time

import numpy as np

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo
from ttr_bot.utils.logger import log
from ttr_bot.vision.fish_detector import has_catch_popup
from ttr_bot.vision.template_matcher import MatchResult, find_template


class BiteResult(enum.Enum):
    CAUGHT = "caught"
    JELLYBEAN = "jellybean"
    BUCKET_FULL = "bucket_full"
    TIMEOUT = "timeout"


class CastOutcome(enum.Enum):
    CAST = "cast"
    SKIPPED = "skipped"
    NO_BEANS = "no_beans"
    BUCKET_FULL = "bucket_full"


def wait_for_bite(
    win: WindowInfo,
    bite_timeout: float,
    stop_event: threading.Event,
) -> BiteResult:
    """Poll until a popup appears or timeout.

    The cheap HSV check runs every poll; the more expensive template
    matches only run every 3rd poll.
    """

    deadline = time.monotonic() + bite_timeout
    poll = 0
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return BiteResult.TIMEOUT

        frame = capture_window(win)
        if frame is None:
            time.sleep(0.05)
            continue

        if has_catch_popup(frame):
            return BiteResult.CAUGHT

        if poll % 3 == 0:
            if find_template(frame, "jellybean_exit") is not None:
                return BiteResult.JELLYBEAN
            if find_template(frame, "ok_button") is not None:
                return BiteResult.BUCKET_FULL

        poll += 1
        time.sleep(settings.BITE_POLL_INTERVAL_S)
    return BiteResult.TIMEOUT


def dismiss_blocking_dialog(win: WindowInfo) -> None:
    """Click away any blocking dialog (jellybean / bucket-full / catch popup).

    Tries up to 3 times, looking for known dismiss buttons.
    """
    for _ in range(3):
        frame = capture_window(win)
        if frame is None:
            time.sleep(0.2)
            continue

        target = (
            find_template(frame, "jellybean_exit", threshold=0.75)
            or find_template(frame, "ok_button", threshold=0.75)
            or find_template(frame, "fish_popup_close", threshold=0.75)
        )
        if target is None:
            return

        log.info("Dismissing dialog: clicking (%d,%d)", target.x, target.y)
        inp.ensure_focused()
        time.sleep(0.1)
        inp.click(target.x, target.y, window=win)
        time.sleep(1.0)


def find_cast_button(
    win: WindowInfo,
    stop_event: threading.Event,
) -> tuple[MatchResult | None, np.ndarray | None]:
    """Poll for the red fishing button.

    Returns ``(MatchResult, frame)`` or ``(None, None)``.
    """

    for _ in range(30):
        if stop_event.is_set():
            return None, None
        frame = capture_window(win)
        if frame is not None:
            btn = find_template(frame, "red_fishing_button", threshold=0.55)
            if btn is not None:
                return btn, frame
        time.sleep(0.1)

    log.warning("Cast button not found after 30 attempts")
    return None, None
