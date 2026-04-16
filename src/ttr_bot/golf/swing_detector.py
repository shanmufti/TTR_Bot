"""Swing readiness and UI-state detection — templates + color heuristics."""

import time

import numpy as np

from ttr_bot.core import input_controller as inp
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.utils.logger import log
from ttr_bot.vision import template_matcher as tm

_SCOREBOARD_R_MIN = 180
_SCOREBOARD_G_MIN = 160
_SCOREBOARD_B_MIN = 100
_SCOREBOARD_MIN_HITS = 3

_TIMER_R_MIN = 200
_TIMER_ORANGE_G_RANGE = (100, 200)
_TIMER_ORANGE_B_MAX = 100
_TIMER_GOLD_G_MIN = 150
_TIMER_GOLD_B_MAX = 80
_TIMER_MIN_RATIO = 0.20
_TIMER_EDGE_PX = 8
_TIMER_MIN_RADIUS = 12

_WAIT_LOG_INTERVAL_S = 3.0


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
        if (
            r > _SCOREBOARD_R_MIN
            and g > _SCOREBOARD_G_MIN
            and b > _SCOREBOARD_B_MIN
            and r >= g >= b
        ):
            hits += 1
    return hits >= _SCOREBOARD_MIN_HITS


def detect_turn_timer_by_color(frame: np.ndarray) -> bool:
    """Orange/gold countdown in the top-right."""
    h, w = frame.shape[:2]
    cx = w - max(_TIMER_EDGE_PX, int(w * 0.05))
    cy = max(_TIMER_EDGE_PX, int(h * 0.07))
    radius = max(_TIMER_MIN_RADIUS, min(w, h) // 15)
    orange = 0
    total = 0
    for dx in range(-radius, radius + 1, 3):
        for dy in range(-radius, radius + 1, 3):
            x, y = cx + dx, cy + dy
            if x < 0 or y < 0 or x >= w or y >= h:
                continue
            total += 1
            b, g, r = frame[y, x].astype(int)
            g_lo, g_hi = _TIMER_ORANGE_G_RANGE
            is_orange = r > _TIMER_R_MIN and g_lo < g < g_hi and b < _TIMER_ORANGE_B_MAX
            is_gold = r > _TIMER_R_MIN and g > _TIMER_GOLD_G_MIN and b < _TIMER_GOLD_B_MAX
            if is_orange or is_gold:
                orange += 1
    ratio = orange / total if total else 0.0
    return ratio > _TIMER_MIN_RATIO


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

    fh, fw = frame.shape[:2]
    for frac_y in (0.68, 0.65, 0.66):
        _click_window_center(win, fw // 2, int(fh * frac_y))
        time.sleep(0.4)
        f2 = capture_window(win)
        if f2 is not None and not is_scoreboard_open(f2):
            return


def wait_until_ready_to_swing(
    stop_event,
    interval_s: float = 0.5,
    *,
    phase: str = "",
) -> None:
    """Poll until turn timer visible. Logs every ~3s with elapsed time."""
    from time import perf_counter

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
        if now - last_log >= _WAIT_LOG_INTERVAL_S:
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


def _frame_or_none() -> np.ndarray | None:
    win = find_ttr_window()
    if win is None:
        return None
    return capture_window(win)
