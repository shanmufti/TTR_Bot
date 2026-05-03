"""Garden bed sidebar UI: single implementation for sweeper, watcher, and tools.

All bed detection and state classification goes through here so template
matching and thresholds stay consistent.
"""

import enum
import time

from ttr_bot.utils.logger import log
from ttr_bot.vision import template_matcher as tm


class BedState(enum.Enum):
    """Possible states of a garden flower bed."""

    PICK = "pick"
    PLANT = "plant"
    UNKNOWN = "unknown"


# Order matters for debugging labels; detection tries each until one matches.
BED_BUTTON_NAMES = (
    "remove_button",
    "pick_flower_button",
    "plant_flower_button",
    "watering_can_button",
)

# Higher threshold for classify to reject cross-matches between the very
# similar pick/plant/remove templates.  Real matches are >0.85; the
# pick-vs-plant false positive is ~0.675.  Click polling uses the default
# (lower) global threshold so matches stay recoverable frame-to-frame.
BED_CLASSIFY_THRESHOLD = 0.75


def detect_bed_button(frame) -> str | None:
    """Return which bed sidebar button template matched, or None if no bed UI."""
    for btn in BED_BUTTON_NAMES:
        if tm.find_template(frame, btn) is not None:
            return btn
    return None


def classify_bed_state(frame, *, log_matches: bool = True) -> BedState:  # noqa: C901, PLR0911
    """Classify the current garden bed UI state.

    Uses a stricter confidence threshold than general template matching to
    avoid cross-matches between the visually similar pick/plant/remove icons.

    Set *log_matches* to False when polling rapidly (e.g. waiting between beds)
    so INFO logs are not flooded — the sidebar often shows Pick after planting.
    """
    t0 = time.monotonic()

    def _log(msg: str, *args: object) -> None:
        if log_matches:
            log.info(msg, *args)

    plant = tm.find_template(frame, "plant_flower_button", threshold=BED_CLASSIFY_THRESHOLD)
    if plant is not None:
        _log("  classify → plant (conf=%.3f, %.0fms)", plant.confidence, _ms(t0))
        return BedState.PLANT

    pick = tm.find_template(frame, "pick_flower_button", threshold=BED_CLASSIFY_THRESHOLD)
    if pick is not None:
        _log("  classify → pick (conf=%.3f, %.0fms)", pick.confidence, _ms(t0))
        return BedState.PICK

    remove = tm.find_template(frame, "remove_button", threshold=BED_CLASSIFY_THRESHOLD)
    if remove is not None:
        _log("  classify → pick via remove (conf=%.3f, %.0fms)", remove.confidence, _ms(t0))
        return BedState.PICK

    water = tm.find_template(frame, "watering_can_button")
    if water is not None:
        plant_retry = tm.find_template(
            frame, "plant_flower_button", threshold=BED_CLASSIFY_THRESHOLD
        )
        if plant_retry is not None:
            _log("  classify → plant (retry conf=%.3f, %.0fms)", plant_retry.confidence, _ms(t0))
            return BedState.PLANT
        pick_retry = tm.find_template(
            frame, "pick_flower_button", threshold=BED_CLASSIFY_THRESHOLD
        )
        if pick_retry is not None:
            _log(
                "  classify → pick (with watering can, conf=%.3f, %.0fms)",
                pick_retry.confidence,
                _ms(t0),
            )
            return BedState.PICK
        remove_retry = tm.find_template(frame, "remove_button", threshold=BED_CLASSIFY_THRESHOLD)
        if remove_retry is not None:
            _log(
                "  classify → pick via remove (with watering can, conf=%.3f, %.0fms)",
                remove_retry.confidence,
                _ms(t0),
            )
            return BedState.PICK
        _log("  classify → unknown (sidebar visible, %.0fms)", _ms(t0))
        return BedState.UNKNOWN

    _log("  classify → unknown (%.0fms)", _ms(t0))
    return BedState.UNKNOWN


def _ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000
