"""Sweep interaction: bed interaction and walk-and-scan logic.

Extracted from GardenSweeper so the scan/interaction steps can be
tested and composed independently.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2

from ttr_bot.config import settings
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.gardening.bed_ui import BED_BUTTON_NAMES, BedState, classify_bed_state
from ttr_bot.vision import template_matcher as tm

if TYPE_CHECKING:
    from ttr_bot.gardening.garden_sweeper import SweepResult
    from ttr_bot.gardening.gardening_bot import GardenBot


@dataclass(slots=True)
class ScanCallbacks:
    """Callbacks injected by the sweeper for the walk-and-scan loop."""

    detect_bed_fn: Callable[[], str | None]
    key_burst_fn: Callable[[list[str], float], None]
    status_fn: Callable[[str], None] | None = None
    grab_frame_fn: Callable[[], object] | None = None
    debug_save_fn: Callable | None = None


@dataclass(slots=True)
class BedActionContext:
    """Shared state for a single bed interaction."""

    flower_name: str
    bean_sequence: str
    result: SweepResult
    bot: GardenBot
    status_fn: Callable[[str], None] | None = None
    debug_save_fn: Callable | None = None


def walk_and_scan(
    keys: list[str],
    leg_duration: float,
    stop_event,
    cb: ScanCallbacks,
) -> str:
    """Walk for *leg_duration*, polling for beds.

    Returns ``"bed_found"``, ``"leg_complete"``, or ``"stopped"``.
    """
    check_interval = settings.SWEEP_CHECK_INTERVAL_S
    elapsed = 0.0

    while elapsed < leg_duration:
        if stop_event.is_set():
            return "stopped"

        burst = min(check_interval, leg_duration - elapsed)
        cb.key_burst_fn(keys, burst)
        elapsed += burst

        bed_btn = cb.detect_bed_fn()
        if bed_btn is not None and _confirm_bed(bed_btn, cb):
            return "bed_found"

    return "leg_complete"


def _confirm_bed(initial_btn: str, cb: ScanCallbacks) -> bool:
    """Double-check that a bed is really present (debounce false positives)."""
    if cb.grab_frame_fn is not None and cb.debug_save_fn is not None:
        detect_frame = cb.grab_frame_fn()
        if detect_frame is not None:
            cb.debug_save_fn(detect_frame, f"bed_detect_{initial_btn}")

    time.sleep(0.3)
    if cb.detect_bed_fn() is not None:
        if cb.status_fn:
            cb.status_fn(f"Bed detected via {initial_btn}")
        return True

    cb.key_burst_fn(["down"], 0.6)
    time.sleep(0.3)
    if cb.detect_bed_fn() is not None:
        if cb.status_fn:
            cb.status_fn("Bed confirmed after backtrack")
        return True

    return False


def interact_at_bed(ctx: BedActionContext) -> None:
    """Classify the bed state, annotate a debug frame, and act."""
    ctx.result.beds_visited += 1
    bed_num = ctx.result.beds_visited
    if ctx.status_fn:
        ctx.status_fn(f"Bed #{bed_num}: checking state…")

    win = find_ttr_window()
    if win is None:
        return
    frame = capture_window(win)
    if frame is None:
        return

    state = classify_bed_state(frame)
    _save_bed_debug(frame, state, bed_num, ctx.debug_save_fn)
    _execute_bed_action(state, bed_num, ctx, frame)
    time.sleep(0.5)


def _save_bed_debug(frame, state: BedState, bed_num: int, debug_save_fn) -> None:
    """Annotate and save a debug frame for bed classification."""
    debug_frame = frame.copy()
    cv2.putText(
        debug_frame,
        f"STATE: {state.value}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 255, 255),
        3,
    )
    y_off = 80
    for btn_name in BED_BUTTON_NAMES:
        m = tm.find_template(frame, btn_name)
        label = f"{btn_name}: {m.confidence:.3f} @({m.x},{m.y})" if m else f"{btn_name}: ---"
        cv2.putText(
            debug_frame, label, (20, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
        )
        y_off += 30
    if debug_save_fn:
        debug_save_fn(debug_frame, f"bed{bed_num}_state_{state.value}")


def _execute_bed_action(state: BedState, bed_num: int, ctx: BedActionContext, frame) -> None:
    """Execute the appropriate action for the detected bed state."""
    if state == BedState.PICK:
        _do_pick_and_plant(bed_num, ctx, frame)
    elif state == BedState.PLANT:
        if ctx.status_fn:
            ctx.status_fn(f"Bed #{bed_num}: planting {ctx.flower_name}")
        if ctx.bot.plant_flower(ctx.flower_name, ctx.bean_sequence):
            ctx.result.beds_planted += 1
    elif ctx.status_fn:
        ctx.status_fn(f"Bed #{bed_num}: state={state.value} — skipping")


def _do_pick_and_plant(bed_num: int, ctx: BedActionContext, frame) -> None:
    """Pick an existing flower and plant a new one."""
    if ctx.status_fn:
        ctx.status_fn(f"Bed #{bed_num}: picking grown flower")
    if ctx.bot.pick_flower(hint_frame=frame):
        ctx.result.beds_picked += 1
        time.sleep(1.0)
        if ctx.status_fn:
            ctx.status_fn(f"Bed #{bed_num}: planting {ctx.flower_name}")
        if ctx.bot.plant_flower_no_pick(ctx.flower_name, ctx.bean_sequence):
            ctx.result.beds_planted += 1
