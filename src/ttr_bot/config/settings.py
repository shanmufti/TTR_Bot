"""All configurable thresholds, delays, and defaults for the TTR bot.

Values can be overridden by placing a ``config.toml`` file next to
this package (i.e. at ``<project>/data/config.toml``).  Only the keys
present in the TOML file are patched; everything else keeps the
defaults defined below.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
GOLF_ACTIONS_DIR = os.path.join(DATA_DIR, "golf_actions")
SELL_PATHS_DIR = os.path.join(DATA_DIR, "sell_paths")

# ---------------------------------------------------------------------------
# Game window
# ---------------------------------------------------------------------------
GAME_WINDOW_TITLE = "Toontown Rewritten"

# ---------------------------------------------------------------------------
# Fishing
# ---------------------------------------------------------------------------
DEFAULT_CASTS = 20
CAST_DRAG_DISTANCE = 150  # base pixels to drag downward (random-cast fallback)
CAST_DRAG_HOLD_MS = 300  # hold time during drag (ms)
BITE_TIMEOUT_S = 12  # max seconds to wait before recasting
BITE_POLL_INTERVAL_S = 0.10  # seconds between bite-check polls
POST_CAST_DELAY_S = 1.0  # wait after cast before polling for bite
BETWEEN_CAST_DELAY_S = 0.2  # wait between successive casts (rod reset animation)

# ---------------------------------------------------------------------------
# Vision – water / pond
# ---------------------------------------------------------------------------
WATER_HUE_RANGE = (60, 140)  # H range in HSV (green through cyan/blue)
WATER_SAT_MIN = 40  # minimum saturation
WATER_VAL_MIN = 50  # minimum value/brightness
POND_TOP_MARGIN = 80  # skip top UI region
POND_BOTTOM_MARGIN = 250  # skip bottom dock region
POND_SIDE_MARGIN = 80  # skip left/right edges
POND_MIN_WATER_PIXELS = 50  # minimum water pixels to accept pond
POND_PADDING = 15  # padding around detected pond area

# ---------------------------------------------------------------------------
# Vision – fish shadow detection
# ---------------------------------------------------------------------------
SHADOW_MIN_ASPECT = 0.3  # minimum blob aspect ratio
SHADOW_MAX_ASPECT = 2.5  # maximum blob aspect ratio
SHADOW_MIN_FILL = 0.3  # minimum fill ratio of bounding box
SHADOW_MIN_SIZE = 15  # minimum blob dimension (px)
SHADOW_WATER_CHECK_RADIUS = 30  # radius for water-surrounding check
SHADOW_WATER_MIN_RATIO = 0.35  # min fraction of surrounding ring that is water

# Shadow color: darker than water, still has blue/green tint
SHADOW_BRIGHTNESS_MAX = 120  # max average brightness for shadow pixel
SHADOW_BLUE_GREEN_BIAS = 15  # (G+B)/2 must exceed R by at least this
SHADOW_MIN_AREA = 50  # blob area range for fish candidates
SHADOW_MAX_AREA = 15000
SHADOW_MAX_DIM = 200  # max blob width or height (px)
FISH_NEAR_THRESHOLD = 60  # px: skip fish this close to last-miss target
FISH_BUBBLE_SCORE_BOOST = 0.5  # ranking bonus for shadows with bubbles

# ---------------------------------------------------------------------------
# Vision – bubble detection
# ---------------------------------------------------------------------------
BUBBLE_SCAN_WIDTH = 60  # px width of scan area above shadow
BUBBLE_SCAN_HEIGHT = 80  # px height of scan area above shadow
BUBBLE_MIN_PIXELS = 3  # minimum bright pixels to confirm bubbles
BUBBLE_BRIGHTNESS_OFFSET = 40  # bubble threshold = avg_water_brightness + this
BUBBLE_BRIGHTNESS_MIN = 150  # absolute minimum brightness for bubble pixel
BUBBLE_MAX_COLOR_DIFF = 50  # max channel spread (R vs G vs B)
BUBBLE_SCAN_STEP = 3  # pixel step when scanning for bubbles

# ---------------------------------------------------------------------------
# Vision – template matching
# ---------------------------------------------------------------------------
TEMPLATE_MATCH_THRESHOLD = 0.65  # minimum confidence for a template match
TEMPLATE_NAMES = {
    # General HUD — always visible bottom-right (Schticker Book); best default calibration anchor
    "hud_bottom_right_icon": "Hud_BottomRight_Icon.png",
    # Fishing
    "red_fishing_button": "Red_Fishing_Button.png",
    "sell_all_button": "Blue_Sell_All_Button.png",
    "exit_fishing_button": "Exit_Fishing_Button.png",
    "fish_popup_close": "FishPopupCloseButton.png",
    "bucket_full_popup": "FishBucketFullPopup.png",
    "ok_button": "Blue_Ok_Button.png",
    "jellybean_exit": "JellybeanExitButton.png",
    # Gardening
    "plant_flower_button": "Plant_Flower_Button.png",
    "red_jellybean_button": "Red_Jellybean_Button.png",
    "green_jellybean_button": "Green_Jellybean_Button.png",
    "orange_jellybean_button": "Orange_Jellybean_Button.png",
    "purple_jellybean_button": "Purple_Jellybean_Button.png",
    "blue_jellybean_button": "Blue_Jellybean_Button.png",
    "pink_jellybean_button": "Pink_Jellybean_Button.png",
    "yellow_jellybean_button": "Yellow_Jellybean_Button.png",
    "cyan_jellybean_button": "Cyan_Jellybean_Button.png",
    "silver_jellybean_button": "Silver_Jellybean_Button.png",
    "blue_plant_button": "Blue_Plant_Button.png",
    "watering_can_button": "Watering_Can_Button.png",
    "pick_flower_button": "Pick_Flower_Button.png",
    "remove_button": "Remove_Button.png",
    # Golf (optional — add PNGs under templates/)
    "golf_pencil_button": "Golf_Pencil_Button.png",
    "golf_close_button": "Golf_Close_Button.png",
    "golf_turn_timer": "Golf_Turn_Timer.png",
}

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
PYAUTOGUI_PAUSE = 0.05  # global pyautogui pause between actions
PYAUTOGUI_FAILSAFE = True  # move mouse to corner to abort
RETINA_SCALE = 2  # macOS HiDPI factor (captures are 2x screen coords)

# ---------------------------------------------------------------------------
# Gardening
# ---------------------------------------------------------------------------
GARDEN_POST_BEAN_DELAY_S = 0.05  # wait after clicking each jellybean
GARDEN_POST_PLANT_DELAY_S = 3.5  # wait after clicking Plant (animation); OK poll handles the rest
GARDEN_POST_CONFIRM_DELAY_S = 0.3  # wait after clicking OK confirmation
GARDEN_POST_WATER_DELAY_S = 1.5  # wait between watering can clicks
GARDEN_POST_PICK_DELAY_S = 2.0  # wait after picking a flower (bed becomes empty)
GARDEN_WATERS_AFTER_PLANT = 1  # times to water after planting
GARDEN_FIND_TIMEOUT_S = 10.0  # max seconds to poll for a template

# ---------------------------------------------------------------------------
# Gardening – sweep navigation
# ---------------------------------------------------------------------------
SWEEP_CHECK_INTERVAL_S = 0.3  # seconds of walking between bed-detection polls
SWEEP_WALK_BURST_S = 0.8  # walk+curve duration per step (up, or up+left/right)
SWEEP_TURN_BURST_S = 0.2  # base turn duration (scaled by magnitude 0-1)
SWEEP_SCAN_ROTATE_S = 0.18  # rotation duration when scanning for flowers
SWEEP_TARGET_BEDS = 10  # expected flower beds per estate garden
SWEEP_MAX_LAPS = 3  # perimeter laps before giving up
SWEEP_POST_INTERACT_WALK_S = 0.6  # walk-away time after interacting with a bed

# ---------------------------------------------------------------------------
# Golf (Custom Golf Actions JSON — same format as Toontown-Rewritten-Bot)
# ---------------------------------------------------------------------------
GOLF_SCAN_INTERVAL_S = 2.0
GOLF_PRE_SWING_DELAY_S = 1.5
GOLF_BETWEEN_HOLES_DELAY_S = 3.0

# ---------------------------------------------------------------------------
# Optional user overrides from config.toml
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(DATA_DIR, "config.toml")


def _collect_overrides(user_cfg: dict) -> list[tuple[str, object]]:
    """Return a flat list of ``(UPPER_KEY, value)`` pairs from the TOML dict."""
    pairs: list[tuple[str, object]] = []
    for key, value in user_cfg.items():
        if isinstance(value, dict):
            pairs.extend((k.upper(), v) for k, v in value.items())
        else:
            pairs.append((key.upper(), value))
    return pairs


def _apply_toml_overrides() -> None:
    """Patch module globals from ``data/config.toml`` if it exists."""
    if not os.path.isfile(_CONFIG_PATH):
        return

    import tomllib

    with open(_CONFIG_PATH, "rb") as f:
        user_cfg = tomllib.load(f)

    this_module = globals()
    applied = 0
    for upper_key, value in _collect_overrides(user_cfg):
        if upper_key not in this_module:
            continue
        this_module[upper_key] = type(this_module[upper_key])(value)
        applied += 1

    if applied:
        import logging

        logging.getLogger("ttr_bot").info(
            "Applied %d setting override(s) from %s", applied, _CONFIG_PATH
        )


_apply_toml_overrides()
