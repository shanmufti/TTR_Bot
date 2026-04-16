"""Golf course detection — templates + optional OCR."""

import time
from collections.abc import Callable
from time import perf_counter

import numpy as np

from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.golf.action_files import list_action_stems
from ttr_bot.golf.courses import match_course_name
from ttr_bot.golf.ocr_text import read_text_from_bgr
from ttr_bot.golf.swing_detector import click_template_or_none, close_scoreboard_if_open
from ttr_bot.utils.logger import log


def _frame_or_none() -> np.ndarray | None:
    win = find_ttr_window()
    if win is None:
        return None
    return capture_window(win)


def detect_course_from_frame(frame: np.ndarray) -> str | None:
    """Try OCR on HUD regions and match to a known course file stem."""
    h, w = frame.shape[:2]

    regions = [
        (0, w // 4, w // 2, h // 6),
        (0, 0, w, h // 8),
        (h // 10, w // 4, w // 2, h // 8),
    ]
    for y0, x0, rw, rh in regions:
        y1, x1 = min(h, y0 + rh), min(w, x0 + rw)
        crop = frame[y0:y1, x0:x1]
        text = read_text_from_bgr(crop)
        m = match_course_name(text)
        if m:
            return m

    cy0, cx0 = h // 4, w // 4
    ch, cw = h // 6, w // 2
    crop = frame[cy0 : cy0 + ch, cx0 : cx0 + cw]
    text = read_text_from_bgr(crop)
    lower = text.lower()
    if "walk" in lower or "par" in lower or "hole" in lower:
        m = match_course_name(text)
        if m:
            return m

    return None


def _ocr_debug_snippet(frame: np.ndarray, max_chars: int = 200) -> str:
    """Short OCR sample from HUD regions for logs when course match fails."""
    h, w = frame.shape[:2]
    regions = [
        (0, w // 4, w // 2, h // 6),
        (0, 0, w, h // 8),
        (h // 10, w // 4, w // 2, h // 8),
    ]
    parts: list[str] = []
    for y0, x0, rw, rh in regions:
        y1, x1 = min(h, y0 + rh), min(w, x0 + rw)
        crop = frame[y0:y1, x0:x1]
        text = read_text_from_bgr(crop)
        if text.strip():
            parts.append(text.strip().replace("\n", " "))
    s = " | ".join(parts)[:max_chars]
    return repr(s) if s else "(empty OCR)"


def detect_course_via_scoreboard() -> str | None:
    """Open scoreboard with pencil, OCR course, close."""
    t0 = perf_counter()
    if not click_template_or_none("golf_pencil_button", threshold=0.78):
        log.warning(
            "Golf [scoreboard] — pencil click failed in %.2fs — capture "
            "data/templates/Golf_Pencil_Button.png (tools/capture_templates.py --golf)",
            perf_counter() - t0,
        )
        return None

    log.debug("Golf [scoreboard] — pencil clicked, sleeping 0.6s for UI")
    time.sleep(0.6)
    frame = _frame_or_none()
    if frame is None:
        log.warning("Golf [scoreboard] — no frame after pencil (%.2fs)", perf_counter() - t0)
        return None

    course = detect_course_from_frame(frame)
    if course is None:
        log.info(
            "Golf [scoreboard] — OCR no course match in %.2fs — sample %s",
            perf_counter() - t0,
            _ocr_debug_snippet(frame),
        )
    else:
        log.info(
            "Golf [scoreboard] — OCR matched %r in %.2fs",
            course,
            perf_counter() - t0,
        )
    close_scoreboard_if_open()
    return course


def wait_for_course_detection(
    stop_event: Callable[[], bool],
    scan_interval_s: float = 2.0,
    max_scoreboard_attempts: int = 3,
    on_need_manual: Callable[[list[str]], str | None] | None = None,
) -> str | None:
    """Poll until a course is identified or cancelled."""
    attempts = 0
    cycle = 0
    t_round = perf_counter()
    while not stop_event():
        cycle += 1
        if attempts < max_scoreboard_attempts:
            log.info(
                "Golf [course_detect] — cycle %d attempt %d/%d (+%.1fs)",
                cycle,
                attempts + 1,
                max_scoreboard_attempts,
                perf_counter() - t_round,
            )
            course = detect_course_via_scoreboard()
            if course is not None:
                log.info(
                    "Golf [course_detect] — stem %r total %.1fs",
                    course,
                    perf_counter() - t_round,
                )
                return course
            attempts += 1
            log.debug(
                "Golf [course_detect] — sleep %.1fs before retry",
                scan_interval_s,
            )
            _sleep_interruptible(scan_interval_s, stop_event)
        else:
            log.warning(
                "Golf [course_detect] - %d scoreboard attempts failed;"
                " manual pick or retry (+%.1fs)",
                max_scoreboard_attempts,
                perf_counter() - t_round,
            )
            options = list_action_stems()
            if on_need_manual and options:
                picked = on_need_manual(options)
                if picked:
                    log.info("Golf [course_detect] — manual stem %r", picked)
                    return picked
            attempts = 0
            _sleep_interruptible(scan_interval_s, stop_event)
    return None


def _sleep_interruptible(seconds: float, stop_event: Callable[[], bool]) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop_event():
            return
        time.sleep(min(0.1, end - time.monotonic()))
