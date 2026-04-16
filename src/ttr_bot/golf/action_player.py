"""Load and execute Custom Golf Actions JSON (compatible with the C# bot format)."""

import os
import threading
import time
from collections.abc import Callable
from time import perf_counter

import pyautogui

from ttr_bot.core import input_controller as inp
from ttr_bot.golf.shot_summary import GolfActionCommand, load_actions
from ttr_bot.utils.logger import log

_ACTION_KEYS: dict[str, str] = {
    "SWING POWER": "ctrl",
    "TURN LEFT": "left",
    "TURN RIGHT": "right",
    "AIM STRAIGHT": "up",
    "MOVE TO LEFT TEE SPOT": "left",
    "MOVE TO RIGHT TEE SPOT": "right",
}

_SKIPPED = frozenset({"MOVE TO LEFT TEE SPOT", "MOVE TO RIGHT TEE SPOT"})


def count_executable_actions(actions: list[GolfActionCommand]) -> int:
    """Return the number of actions that will actually execute (excluding tee-spot moves)."""
    return sum(1 for a in actions if a.action not in _SKIPPED)


def _next_action_label(actions: list[GolfActionCommand], after_index: int) -> str:
    """Return the name of the next executable action, or ``"Done"``."""
    for j in range(after_index + 1, len(actions)):
        if actions[j].action not in _SKIPPED:
            return actions[j].action
    return "Done"


def _interruptible_delay(seconds: float, stop_event: threading.Event) -> bool:
    """Sleep for *seconds*, checking *stop_event*. Returns True if interrupted."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return True
        time.sleep(min(0.1, deadline - time.monotonic()))
    return False


def _hold_key(key: str, seconds: float, stop_event: threading.Event) -> bool:
    """Hold *key* for *seconds*, releasing early on stop. Returns True if interrupted."""
    pyautogui.keyDown(key)
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if stop_event.is_set():
                return True
            time.sleep(min(0.05, end - time.monotonic()))
    finally:
        pyautogui.keyUp(key)
    return False


def _execute_step(
    cmd: GolfActionCommand,
    stop_event: threading.Event,
    t_replay: float,
) -> bool:
    """Execute a single golf action. Returns True if replay should abort."""
    t_step = perf_counter()
    if cmd.action == "DELAY TIME":
        if _interruptible_delay(cmd.duration / 1000.0, stop_event):
            return True
        log.info("Golf [replay] — DELAY TIME done in %.2fs", perf_counter() - t_step)
        return False

    key = _ACTION_KEYS.get(cmd.action)
    if key is None:
        log.error("Unsupported golf action: %s", cmd.action)
        return True

    if _hold_key(key, cmd.duration / 1000.0, stop_event):
        return True
    log.info(
        "Golf [replay] — key %s held %.2fs (step wall %.2fs)",
        key,
        cmd.duration / 1000.0,
        perf_counter() - t_step,
    )
    return False


def perform_golf_actions(
    file_path: str,
    stop_event: threading.Event,
    *,
    on_step: Callable[[int, int, str, str, int], None] | None = None,
) -> None:
    """Execute all actions in *file_path*. Honors *stop_event* between steps."""
    if not os.path.isfile(file_path):
        log.error("Golf actions file not found: %s", file_path)
        return

    actions = load_actions(file_path)
    total = count_executable_actions(actions)
    step_i = 0
    t_replay = perf_counter()

    log.info("Golf [replay] — start %s (%d executable steps)", os.path.basename(file_path), total)

    inp.ensure_focused()
    time.sleep(1.0)
    log.debug("Golf [replay] — focus + 1.0s settle done in %.2fs", perf_counter() - t_replay)

    for i, cmd in enumerate(actions):
        if stop_event.is_set():
            log.info("Golf actions cancelled")
            return

        if cmd.action in _SKIPPED:
            continue

        step_i += 1
        next_label = _next_action_label(actions, i)
        if on_step:
            on_step(step_i, total, cmd.action, next_label, cmd.duration)

        log.info(
            "Golf [replay] — step %d/%d %s duration_ms=%d (next: %s, +%.2fs in replay)",
            step_i,
            total,
            cmd.action,
            cmd.duration,
            next_label,
            perf_counter() - t_replay,
        )

        if _execute_step(cmd, stop_event, t_replay):
            return

    log.info("Golf [replay] — completed %s in %.1fs", file_path, perf_counter() - t_replay)
