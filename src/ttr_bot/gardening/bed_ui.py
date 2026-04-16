"""Garden bed sidebar UI: single implementation for sweeper, watcher, and tools.

All bed detection and state classification goes through here so template
matching and thresholds stay consistent.
"""

import time

from ttr_bot.utils.logger import log
from ttr_bot.vision import template_matcher as tm

# Order matters for debugging labels; detection tries each until one matches.
BED_BUTTON_NAMES = (
    "remove_button",
    "pick_flower_button",
    "plant_flower_button",
    "watering_can_button",
)

# Higher threshold for classify to reject cross-matches between the very
# similar pick/plant/remove templates.  Real matches are >0.85; the
# pick-vs-plant false positive is ~0.675.
_CLASSIFY_THRESHOLD = 0.75


def detect_bed_button(frame) -> str | None:
    """Return which bed sidebar button template matched, or None if no bed UI."""
    for btn in BED_BUTTON_NAMES:
        if tm.find_template(frame, btn) is not None:
            return btn
    return None


def classify_bed_state(frame) -> str:
    """Return ``pick``, ``plant``, or ``unknown``.

    Uses a stricter confidence threshold than general template matching to
    avoid cross-matches between the visually similar pick/plant/remove icons.

    Checks are ordered for fastest early exit:
      1. plant_flower_button → ``plant`` (empty bed)
      2. pick_flower_button  → ``pick``  (grown flower)
      3. remove_button       → ``pick``  (cross-matches pick slot)
      4. watering_can_button → ``plant`` (sidebar visible but main buttons
         didn't match — assume plantable bed as a safe fallback)
      5. nothing             → ``unknown``
    """
    t0 = time.monotonic()

    plant = tm.find_template(frame, "plant_flower_button", threshold=_CLASSIFY_THRESHOLD)
    if plant is not None:
        log.info("  classify → plant (conf=%.3f, %.0fms)", plant.confidence, _ms(t0))
        return "plant"

    pick = tm.find_template(frame, "pick_flower_button", threshold=_CLASSIFY_THRESHOLD)
    if pick is not None:
        log.info("  classify → pick (conf=%.3f, %.0fms)", pick.confidence, _ms(t0))
        return "pick"

    remove = tm.find_template(frame, "remove_button", threshold=_CLASSIFY_THRESHOLD)
    if remove is not None:
        log.info("  classify → pick via remove (conf=%.3f, %.0fms)", remove.confidence, _ms(t0))
        return "pick"

    water = tm.find_template(frame, "watering_can_button")
    if water is not None:
        plant_retry = tm.find_template(frame, "plant_flower_button")
        if plant_retry is not None:
            log.info(
                "  classify → plant (retry conf=%.3f, %.0fms)", plant_retry.confidence, _ms(t0)
            )
            return "plant"
        log.info("  classify → unknown (sidebar visible, %.0fms)", _ms(t0))
        return "unknown"

    log.info("  classify → unknown (%.0fms)", _ms(t0))
    return "unknown"


def _ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000
