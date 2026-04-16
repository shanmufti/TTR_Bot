"""Garden bed sidebar UI: single implementation for sweeper, watcher, and tools.

All bed detection and state classification goes through here so template
matching and thresholds stay consistent.
"""

from __future__ import annotations

import time

from ttr_bot.vision import template_matcher as tm
from ttr_bot.utils.logger import log

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
    plant_ms = (time.monotonic() - t0) * 1000
    if plant is not None:
        log.info("  classify: plant=%.3f(%.0fms) → plant", plant.confidence, plant_ms)
        return "plant"

    t1 = time.monotonic()
    pick = tm.find_template(frame, "pick_flower_button", threshold=_CLASSIFY_THRESHOLD)
    pick_ms = (time.monotonic() - t1) * 1000
    if pick is not None:
        log.info("  classify: plant=none(%.0fms) pick=%.3f(%.0fms) → pick",
                 plant_ms, pick.confidence, pick_ms)
        return "pick"

    t2 = time.monotonic()
    remove = tm.find_template(frame, "remove_button", threshold=_CLASSIFY_THRESHOLD)
    remove_ms = (time.monotonic() - t2) * 1000
    if remove is not None:
        log.info("  classify: plant=none(%.0fms) pick=none(%.0fms) "
                 "remove=%.3f(%.0fms) → pick",
                 plant_ms, pick_ms, remove.confidence, remove_ms)
        return "pick"

    # If no primary button matched at the strict threshold, check whether the
    # sidebar is visible at all via the watering-can (always present when near
    # a bed).  If it is, retry the plant button at the default (looser)
    # threshold — sometimes the plant template only scores ~0.79.
    t3 = time.monotonic()
    water = tm.find_template(frame, "watering_can_button")
    water_ms = (time.monotonic() - t3) * 1000
    if water is not None:
        plant_retry = tm.find_template(frame, "plant_flower_button")
        if plant_retry is not None:
            log.info("  classify: plant=%.3f(retry) water=%.3f(%.0fms) → plant",
                     plant_retry.confidence, water.confidence, water_ms)
            return "plant"
        log.info("  classify: all=none water=%.3f(%.0fms) → unknown (sidebar visible)",
                 water.confidence, water_ms)

    log.info("  classify: plant=none(%.0fms) pick=none(%.0fms) "
             "remove=none(%.0fms) water=none(%.0fms) → unknown",
             plant_ms, pick_ms, remove_ms, water_ms)
    return "unknown"
