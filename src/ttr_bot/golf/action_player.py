"""Load and execute Custom Golf Actions JSON (compatible with the C# bot format)."""

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Self

import pyautogui

from ttr_bot.core import input_controller as inp
from ttr_bot.core.errors import GolfActionFileError
from ttr_bot.utils.logger import log

# Action name -> pyautogui key name (macOS Control for swing power).
_ACTION_KEYS: dict[str, str] = {
    "SWING POWER": "ctrl",
    "TURN LEFT": "left",
    "TURN RIGHT": "right",
    "AIM STRAIGHT": "up",
    "MOVE TO LEFT TEE SPOT": "left",
    "MOVE TO RIGHT TEE SPOT": "right",
}

_SKIPPED = frozenset({"MOVE TO LEFT TEE SPOT", "MOVE TO RIGHT TEE SPOT"})


@dataclass
class GolfActionCommand:
    """One step in a custom golf action sequence."""

    action: str
    duration: int
    command: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        return cls(
            action=str(d.get("Action", d.get("action", ""))),
            duration=int(d.get("Duration", d.get("duration", 0))),
            command=str(d.get("Command", d.get("command", ""))),
        )


@dataclass
class GolfShotSummary:
    """Human-readable summary derived from a sequence of golf actions."""

    position: str = "Center"
    aim: str = "Straight"
    power: int = 0
    delay_seconds: int = 0

    @property
    def requires_position_change(self) -> bool:
        return self.position != "Center"

    def describe(self) -> str:
        lines = [
            "━━━ YOU (before start) ━━━",
        ]
        if self.requires_position_change:
            lines.append(f"Move to the {self.position.upper()} tee position.")
        else:
            lines.append("Stay on the CENTER tee position.")
        lines.extend(
            [
                "",
                "━━━ BOT ━━━",
                f"Aim: {self.aim}",
                f"Power: ~{self.power}%",
                "",
                f"You have {self.delay_seconds}s after start to focus TTR.",
            ]
        )
        return "\n".join(lines)


def load_actions(path: str) -> list[GolfActionCommand]:
    """Load a custom golf-action JSON file into a list of commands."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise GolfActionFileError
    return [GolfActionCommand.from_dict(x) for x in raw]


def shot_summary(actions: list[GolfActionCommand]) -> GolfShotSummary:
    """Derive a display summary from actions (same heuristics as the C# bot)."""
    s = GolfShotSummary()
    for a in actions:
        match a.action:
            case "MOVE TO LEFT TEE SPOT":
                s.position = "Left"
            case "MOVE TO RIGHT TEE SPOT":
                s.position = "Right"
            case "TURN LEFT":
                taps = max(1, a.duration // 22)
                s.aim = f"{taps} left"
            case "TURN RIGHT":
                taps = max(1, a.duration // 22)
                s.aim = f"{taps} right"
            case "AIM STRAIGHT":
                s.aim = "Straight (up)"
            case "SWING POWER":
                s.power = max(0, a.duration // 25)
            case "DELAY TIME":
                s.delay_seconds = a.duration // 1000
    return s


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

        t_step = perf_counter()
        log.info(
            "Golf [replay] — step %d/%d %s duration_ms=%d (next: %s, +%.2fs in replay)",
            step_i,
            total,
            cmd.action,
            cmd.duration,
            next_label,
            t_step - t_replay,
        )

        if cmd.action == "DELAY TIME":
            if _interruptible_delay(cmd.duration / 1000.0, stop_event):
                return
            log.info("Golf [replay] — DELAY TIME done in %.2fs", perf_counter() - t_step)
            continue

        key = _ACTION_KEYS.get(cmd.action)
        if key is None:
            log.error("Unsupported golf action: %s", cmd.action)
            return

        if _hold_key(key, cmd.duration / 1000.0, stop_event):
            return
        log.info(
            "Golf [replay] — key %s held %.2fs (step wall %.2fs)",
            key,
            cmd.duration / 1000.0,
            perf_counter() - t_step,
        )

    log.info("Golf [replay] — completed %s in %.1fs", file_path, perf_counter() - t_replay)
