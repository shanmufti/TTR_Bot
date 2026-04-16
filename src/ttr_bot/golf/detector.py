"""Golf course detection and 'ready to swing' — templates + optional OCR + color heuristics."""

from __future__ import annotations

import time
from collections.abc import Callable
from time import perf_counter

import numpy as np

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.golf.courses import match_course_name
from ttr_bot.golf.ocr_text import read_text_from_bgr
from ttr_bot.utils.logger import log
from ttr_bot.vision import template_matcher as tm


def list_action_stems() -> list[str]:
    """Basenames of *.json files in the golf actions directory."""
    import os

    d = settings.GOLF_ACTIONS_DIR
    if not d or not os.path.isdir(d):
        return []

    names = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".json"):
            names.append(os.path.splitext(name)[0])
    return names


def action_file_exists(stem: str) -> bool:
    """Return True if a JSON action file for *stem* exists on disk."""
    import os

    path = os.path.join(settings.GOLF_ACTIONS_DIR, f"{stem}.json")
    return os.path.isfile(path)


def path_for_stem(stem: str) -> str:
    """Return the full filesystem path for a golf action *stem*."""
    import os

    return os.path.join(settings.GOLF_ACTIONS_DIR, f"{stem}.json")


def _frame_or_none() -> np.ndarray | None:
    win = find_ttr_window()
    if win is None:
        return None
    return capture_window(win)


def detect_course_from_frame(frame: np.ndarray) -> str | None:
    """Try OCR on HUD regions and match to a known course file stem."""
    h, w = frame.shape[:2]

    # (y0, x0, width, height) — same layout ideas as the C# GolfCourseDetector
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

    # Scoreboard-style center header
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


def is_scoreboard_open(frame: np.ndarray) -> bool:
    """Heuristic: cream/yellow panel in the center (same idea as the C# bot)."""
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    points = [
        (cx, cy),
        (cx - 50, cy),
        (cx + 50, cy),
        (cx, cy - 30),
        (cx, cy + 30),
    ]
    hits = 0
    for px, py in points:
        if px < 0 or py < 0 or px >= w or py >= h:
            continue
        b, g, r = frame[py, px].astype(int)
        if r > 180 and g > 160 and b > 100 and r >= g >= b:
            hits += 1
    return hits >= 3


def detect_turn_timer_by_color(frame: np.ndarray) -> bool:
    """Orange/gold countdown in the top-right."""
    h, w = frame.shape[:2]
    cx = w - max(8, int(w * 0.05))
    cy = max(8, int(h * 0.07))
    radius = max(12, min(w, h) // 15)
    orange = 0
    total = 0
    for dx in range(-radius, radius + 1, 3):
        for dy in range(-radius, radius + 1, 3):
            x, y = cx + dx, cy + dy
            if x < 0 or y < 0 or x >= w or y >= h:
                continue
            total += 1
            b, g, r = frame[y, x].astype(int)
            is_orange = r > 200 and 100 < g < 200 and b < 100
            is_gold = r > 200 and g > 150 and b < 80
            if is_orange or is_gold:
                orange += 1
    ratio = orange / total if total else 0.0
    return ratio > 0.20


def is_ready_to_swing(frame: np.ndarray) -> bool:
    """Return True if the golf swing power-meter UI is on screen."""
    from ttr_bot.vision.template_matcher import _default as tm_instance
    from ttr_bot.vision.template_matcher import find_template

    if tm_instance.scale is None:
        return detect_turn_timer_by_color(frame)
    t = find_template(frame, "golf_turn_timer", threshold=0.70)
    if t is not None:
        return True
    return detect_turn_timer_by_color(frame)


def _click_window_center(win: WindowInfo, x: int, y: int) -> None:
    inp.click(x, y, window=win)


def click_template_or_none(template_name: str, threshold: float = 0.75) -> bool:
    """Click a template if visible; return True on success."""
    win = find_ttr_window()
    if win is None:
        return False
    frame = capture_window(win)
    if frame is None:
        return False
    m = tm.find_template(frame, template_name, threshold=threshold)
    if m is None:
        return False
    _click_window_center(win, m.x, m.y)
    return True


def close_scoreboard_if_open() -> None:
    """Try template match for close button, then fallback clicks."""
    win = find_ttr_window()
    if win is None:
        return
    frame = capture_window(win)
    if frame is None or not is_scoreboard_open(frame):
        return

    if click_template_or_none("golf_close_button", threshold=0.70):
        time.sleep(0.5)
        return

    # Fallback: bottom-center of captured frame (matches Retina template coords)
    fh, fw = frame.shape[:2]
    for frac_y in (0.68, 0.65, 0.66):
        _click_window_center(win, fw // 2, int(fh * frac_y))
        time.sleep(0.4)
        f2 = capture_window(win)
        if f2 is not None and not is_scoreboard_open(f2):
            return


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


def wait_until_ready_to_swing(
    stop_event: Callable[[], bool],
    interval_s: float = 0.5,
    *,
    phase: str = "",
) -> None:
    """Poll until turn timer visible. Logs every ~3s with elapsed time."""
    t0 = perf_counter()
    polls = 0
    last_log = t0
    phase_tag = f" {phase}" if phase else ""

    while not stop_event():
        polls += 1
        frame = _frame_or_none()
        if frame is not None and is_ready_to_swing(frame):
            log.info(
                "Golf [wait_ready%s] — ready after %.1fs (%d polls, interval=%.2fs)",
                phase_tag,
                perf_counter() - t0,
                polls,
                interval_s,
            )
            return
        now = perf_counter()
        if now - last_log >= 3.0:
            last_log = now
            reason = "no TTR frame" if frame is None else "turn timer template/color not detected"
            log.info(
                "Golf [wait_ready%s] — still waiting %.1fs (%d polls, %s)",
                phase_tag,
                now - t0,
                polls,
                reason,
            )
        time.sleep(interval_s)


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
