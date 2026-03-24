"""All configurable thresholds, delays, and defaults for the TTR bot."""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
GARDENING_ROUTINES_DIR = os.path.join(DATA_DIR, "gardening_routines")
GOLF_ACTIONS_DIR = os.path.join(DATA_DIR, "golf_actions")
SELL_PATHS_DIR = os.path.join(DATA_DIR, "sell_paths")

# ---------------------------------------------------------------------------
# Game window
# ---------------------------------------------------------------------------
GAME_WINDOW_TITLE = "Toontown Rewritten"

# ---------------------------------------------------------------------------
# Fishing – general
# ---------------------------------------------------------------------------
DEFAULT_CASTS = 20
DEFAULT_SELL_ROUNDS = 3
DEFAULT_VARIANCE = 15  # pixels of random left/right when casting
CAST_DRAG_DISTANCE = 150  # base pixels to drag downward (logical)
CAST_DRAG_HOLD_MS = 500  # hold time during drag (ms)
BITE_TIMEOUT_S = 12  # max seconds to wait before recasting
BITE_POLL_INTERVAL_S = 0.10  # seconds between bite-check polls
POST_CAST_DELAY_S = 1.0  # wait after cast before polling for bite
POST_CAST_DELAY_QUICK_S = 0.2  # shorter delay when quick-casting
POST_CATCH_DELAY_S = 0.3  # wait after catch before closing popup
BETWEEN_CAST_DELAY_S = (
    0.2  # wait between successive casts (game needs time to reset rod)
)
SELL_WALK_DELAY_S = 2.0  # settle time after returning from sell trip

# ---------------------------------------------------------------------------
# Fishing – fish detection
# ---------------------------------------------------------------------------
FISH_WAIT_BEFORE_CAST = False  # wait for shadow before casting
FISH_WAIT_TIMEOUT_S = 20  # max seconds to wait for a shadow
FISH_WAIT_SCAN_DELAY_S = 2.0  # delay between detection scans

# ---------------------------------------------------------------------------
# Vision – water / pond
# ---------------------------------------------------------------------------
WATER_HUE_RANGE = (80, 140)  # H range in HSV (teal/cyan)
WATER_SAT_MIN = 40  # minimum saturation
WATER_VAL_MIN = 50  # minimum value/brightness
POND_SCAN_STEP = 5  # pixel step when scanning for water
POND_TOP_MARGIN = 80  # skip top UI region
POND_BOTTOM_MARGIN = 250  # skip bottom dock region
POND_SIDE_MARGIN = 80  # skip left/right edges
POND_MIN_WATER_PIXELS = 50  # minimum water pixels to accept pond
POND_PADDING = 15  # padding around detected pond area

# ---------------------------------------------------------------------------
# Vision – fish shadow detection
# ---------------------------------------------------------------------------
SHADOW_SCAN_STEP = 3  # pixel step when scanning for shadows
SHADOW_BLOB_MAX_DISTANCE = 12  # max pixel distance to cluster blobs
SHADOW_MIN_ASPECT = 0.3  # minimum blob aspect ratio
SHADOW_MAX_ASPECT = 3.0  # maximum blob aspect ratio
SHADOW_MIN_FILL = 0.2  # minimum fill ratio of bounding box
SHADOW_MIN_SIZE = 15  # minimum blob dimension (px)
SHADOW_WATER_CHECK_RADIUS = 30  # radius for water-surrounding check
SHADOW_WATER_MIN_RATIO = 0.35  # min fraction of surrounding ring that is water

# Shadow color: darker than water, still has blue/green tint
SHADOW_BRIGHTNESS_MAX = 120  # max average brightness for shadow pixel
SHADOW_BLUE_GREEN_BIAS = 15  # (G+B)/2 must exceed R by at least this

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

# ---------------------------------------------------------------------------
# Fishing locations (for sell-walk sequences)
# ---------------------------------------------------------------------------
FISHING_LOCATIONS = [
    "Donalds Dreamland",
    "Fish Anywhere",
    "Estate (Left Dock)",
    "TTC Punchline Place",
    "DD Lighthouse Lane",
    "DG Elm Street",
    "MM Tenor Terrace",
    "Brrrgh Polar Place",
    "Brrrgh Walrus Way",
    "Brrrgh Sleet Street",
    "DDL Lullaby Lane",
]

# ---------------------------------------------------------------------------
# Gardening
# ---------------------------------------------------------------------------
GARDEN_POST_BEAN_DELAY_S = 0.1  # wait after clicking each jellybean
GARDEN_POST_PLANT_DELAY_S = 6.0  # wait after clicking the Plant button
GARDEN_POST_CONFIRM_DELAY_S = 1.0  # wait after clicking OK confirmation
GARDEN_POST_WATER_DELAY_S = 3.0  # wait between watering can clicks
GARDEN_POST_PICK_DELAY_S = 4.0  # wait after picking a flower (bed becomes empty)
GARDEN_WATERS_AFTER_PLANT = 1  # times to water after planting
GARDEN_FIND_TIMEOUT_S = 10.0  # max seconds to poll for a template

# ---------------------------------------------------------------------------
# Gardening – demo recording
# ---------------------------------------------------------------------------
DEMO_FRAME_INTERVAL_MS = 200  # capture every 200ms (~5 FPS)
DEMO_SAVE_DIR = os.path.join(GARDENING_ROUTINES_DIR, "demos")

# ---------------------------------------------------------------------------
# Gardening – SIFT localization
# ---------------------------------------------------------------------------
SIFT_NFEATURES = 500  # max SIFT keypoints per frame (speed vs accuracy)
SIFT_MATCH_RATIO = 0.7  # Lowe's ratio test threshold
LOCALIZATION_MIN_MATCHES = 10  # minimum good matches to accept a localization

# ---------------------------------------------------------------------------
# Gardening – navigation (demo replay warm-start)
# ---------------------------------------------------------------------------
NAV_REPLAY_DRIFT_THRESHOLD = 0.4  # localization conf below this = drifting
NAV_REPLAY_CLOSE_RANGE = 0.7  # conf above this near target = arrived

# ---------------------------------------------------------------------------
# Gardening – navigation (SIFT correction)
# ---------------------------------------------------------------------------
NAV_MAX_WALK_TIME_PER_BED = 30  # seconds before giving up on a bed
NAV_KEY_BURST_MS = 200  # duration of each key press burst
NAV_RECHECK_INTERVAL_MS = 250  # re-localize every N ms
NAV_HEADING_SMOOTHING = 4  # rolling average window for heading

# ---------------------------------------------------------------------------
# Gardening – stuck detection
# ---------------------------------------------------------------------------
NAV_STUCK_THRESHOLD = 500  # min frame diff sum to consider "moving"
NAV_STUCK_TIMEOUT_S = 1.5  # seconds of no movement before stuck
NAV_MAX_RECOVERY_ATTEMPTS = 3  # per bed, then skip

# ---------------------------------------------------------------------------
# Gardening – camera
# ---------------------------------------------------------------------------
CAMERA_TAB_COUNT = 2  # Tab presses to reach zoomed-out chase cam

# ---------------------------------------------------------------------------
# Golf (Custom Golf Actions JSON — same format as Toontown-Rewritten-Bot)
# ---------------------------------------------------------------------------
GOLF_SCAN_INTERVAL_S = 2.0
GOLF_PRE_SWING_DELAY_S = 1.5
GOLF_BETWEEN_HOLES_DELAY_S = 3.0
