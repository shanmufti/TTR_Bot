"""Golf action data model and summary helpers."""

import json
from dataclasses import dataclass
from typing import Self

from ttr_bot.core.errors import GolfActionFileError


@dataclass(slots=True)
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


@dataclass(slots=True)
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
