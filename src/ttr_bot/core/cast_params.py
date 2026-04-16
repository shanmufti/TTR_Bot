"""Persistent cast tuning parameters (power / aim curves).

Shared by core.input_controller (consumer) and fishing.cast_recorder
(producer) to avoid a core -> fishing dependency cycle.
"""

import json
import os
from dataclasses import asdict, dataclass

from ttr_bot.utils.logger import log

_PARAMS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "cast_params.json"
)


@dataclass(slots=True)
class CastParams:
    """Tuned power/aim curve constants persisted to JSON between sessions."""

    power_base: float = 6.8
    aim_base: float = 3.0
    aim_base_right: float | None = None
    aim_offset: float | None = None

    def save(self) -> None:
        os.makedirs(os.path.dirname(_PARAMS_FILE), exist_ok=True)
        with open(_PARAMS_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)
        log.info("Cast params saved to %s", _PARAMS_FILE)

    @staticmethod
    def load() -> "CastParams | None":
        if not os.path.isfile(_PARAMS_FILE):
            return None
        try:
            with open(_PARAMS_FILE) as f:
                data = json.load(f)
            params = CastParams(
                power_base=data.get("power_base", 6.8),
                aim_base=data.get("aim_base", 3.0),
                aim_base_right=data.get("aim_base_right"),
                aim_offset=data.get("aim_offset"),
            )
            log.info(
                "Cast params loaded: power=%.2f aim_left=%.2f aim_right=%.2f offset=%.1f",
                params.power_base,
                params.aim_base,
                params.aim_base_right or params.aim_base,
                params.aim_offset or 0.0,
            )
        except Exception:
            log.exception("Failed to load cast params")
            return None
        else:
            return params
