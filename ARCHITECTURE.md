# Architecture

This document describes the module structure, data flow, and key design
decisions in TTR Bot.

## High-Level Overview

```
┌─────────────────────────────────────────────────────┐
│                    UI (tkinter)                     │
│  FishingTab  │  GardeningTab  │  GolfingTab        │
│              │                │  GolfCourseDialog   │
│  LogHandler  │                │                     │
└──────┬───────┴───────┬────────┴──────┬──────────────┘
       │               │               │
       ▼               ▼               ▼
┌─────────────┐ ┌──────────────┐ ┌────────────┐
│ FishingBot  │ │ GardenBot    │ │  GolfBot   │
│ CastRecorder│ │ Sweeper      │ │ ActionPlayer│
│ BiteDetect  │ │ Watcher      │ │ CourseDetect│
│ CastFitter  │ │ PlantSequence│ │ SwingDetect│
│ FishDebug   │ │ SweepInteract│ │ ActionFiles│
│             │ │ UIHelpers    │ │ ShotSummary│
└──────┬──────┘ └──────┬───────┘ └─────┬──────┘
       │   ╲            │            ╱  │
       │    ╲───────────┼───────────╱   │
       │      BotBase ABC (shared)      │
       │      CalibrationService        │
       │               │                │
       ▼               ▼                ▼
┌─────────────────────────────────────────────────────┐
│                   Vision Layer                      │
│  TemplateMatcher  TemplateCalibration  ColorMatcher │
│  FishDetector  PondDetector  FlowerDetector         │
│  BubbleDetector                                     │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│                    Core Layer                       │
│  WindowManager  ScreenCapture  InputController      │
│  CastInput  BobberDetector  CastCalibration         │
│  CastParams  Errors  BotBase  CalibrationService    │
└─────────────────────────────────────────────────────┘
```

Dependencies flow **downward**: UI → domain bots → vision → core. No upward
or circular imports.

## Architecture Patterns

### Bot Framework (`BotBase`)

All domain bots inherit from `core.bot_base.BotBase`, which provides:
- Thread lifecycle (start/stop via `_start_thread`, daemon threads)
- Stop signaling (`_stop_event`, `should_stop`)
- Pause/resume (`toggle_pause`, `_wait_if_paused`)
- Status/ended callbacks (`on_status_update`, `on_ended`)
- Helper methods (`_status`, `_finish`)

Subclasses implement their specific work loop and call `_start_thread(target)`
to begin.

### Calibration Service

`core.calibration_service.CalibrationService` is the single authority for the
find-window → lock-bounds → capture → scale-calibrate flow. All 4 call sites
(fishing tab, gardening bot, cast recorder, app) delegate to this service
instead of reimplementing the sequence.

### Data Types

- **Frozen dataclasses** (`@dataclass(frozen=True, slots=True)`) for immutable
  value objects: `MatchResult`, `FishCandidate`, `FlowerBlob`, `SteeringHint`,
  `CalibrationSample`, `CalibrationResult`.
- **Mutable dataclasses** (`@dataclass(slots=True)`) for counters and config:
  `FishingStats`, `FishingConfig`, `GardeningStats`, `CastParams`, etc.
- **Enums** for finite states: `BiteResult`, `CastOutcome`, `BedState`.

## Module Guide

### `core/` — Platform Abstraction & Framework

| Module               | Responsibility |
|----------------------|----------------|
| `bot_base`           | Abstract base class for threaded bots: lifecycle, pause, callbacks. |
| `calibration_service`| Single calibration entry point: find window, lock bounds, capture, scale. |
| `window_manager`     | Find the TTR window via Quartz, read bounds, bring to front. Thread-safe calibrated-bounds cache. |
| `screen_capture`     | Grab a BGR numpy frame of the game window using `CGWindowListCreateImage`. |
| `input_controller`   | Click, drag, key-press via pyautogui with Retina-scale correction. |
| `cast_input`         | Fishing-specific cast vector math (power/aim curves). |
| `bobber_detector`    | Frame-differencing to locate bobber landing position. |
| `cast_calibration`   | Auto-calibration: cast known drags, fit linear transform from bobber landings. |
| `cast_params`        | Dataclass + JSON persistence for tuned power/aim curve constants. |
| `errors`             | Exception hierarchy: `TTRBotError` → `WindowNotFoundError`, `CalibrationError`, etc. |

### `vision/` — Computer Vision

| Module                | Responsibility |
|-----------------------|----------------|
| `template_matcher`    | Multi-scale OpenCV `matchTemplate` with caching. Thread-safe `TemplateMatcher` class; module-level functions delegate to a default instance. |
| `template_calibration`| Scale calibration logic: coarse anchor scan + fine-tune. Operates on a `TemplateMatcher` instance. |
| `color_matcher`       | HSV/BGR pixel classification: water, shadow, bubble colours. Builds binary masks. |
| `fish_detector`       | Blob analysis on the shadow mask inside the pond ROI. Scores candidates by size, shape, bubble proximity. |
| `pond_detector`       | Finds the pond bounding box from a water mask using contour analysis. |
| `flower_detector`     | Detects garden flowers as red-near-green colour blobs. Provides `SteeringHint` for navigation. |
| `bubble_detector`     | Detects fish bubbles (small bright spots in the pond) to boost shadow scores. |

### `fishing/` — Fishing Automation

| Module           | Responsibility |
|------------------|----------------|
| `fishing_bot`    | Main loop: find button → detect shadow → cast → wait for bite → repeat. Inherits `BotBase`. |
| `bite_detector`  | Stateless functions: wait for bite, dismiss dialogs, find cast button. Defines `BiteResult`/`CastOutcome` enums. |
| `fishing_debug`  | Save annotated vision-pipeline frames for post-session review. |
| `cast_fitter`    | Curve fitting from recorded cast samples to derive cast params. |
| `cast_recorder`  | Passive mode: watch user fish, record drag vectors and landings. Inherits `BotBase`. |
| `sell_controller`| Walk-to-fisherman sell sequences loaded from JSON. |

### `gardening/` — Garden Automation

| Module              | Responsibility |
|---------------------|----------------|
| `gardening_bot`     | Core plant/water/pick orchestration. Inherits `BotBase`. |
| `plant_sequence`    | Multi-step planting procedure: click plant → select beans → confirm. |
| `garden_ui_helpers` | Template polling + click helpers, calibration helper. |
| `sweep_interaction` | Bed interaction and walk-and-scan logic during sweeps. |
| `flowers`           | Static flower database: names, bean sequences, jellybean costs. |
| `bed_ui`            | Detect and classify garden-bed UI buttons. Defines `BedState` enum. |
| `garden_sweeper`    | Vision-guided navigation: scan for flowers, steer, interact with beds. |
| `garden_watcher`    | Passive poller: auto-acts when bed buttons appear. |
| `routine_runner`    | Orchestrates sweep/watch routines in a background thread. |

### `golf/` — Golf Automation

| Module           | Responsibility |
|------------------|----------------|
| `golf_bot`       | Round loop: detect course → load actions → replay shots → repeat. Inherits `BotBase`. |
| `action_player`  | Execute a list of `GolfActionCommand` (key presses with durations). |
| `course_detector`| Course detection via OCR + template matching. |
| `swing_detector` | Swing readiness, scoreboard detection, turn timer by colour. |
| `action_files`   | Filesystem helpers for action JSON file discovery. |
| `shot_summary`   | Action data model (`GolfActionCommand`, `GolfShotSummary`) and display. |
| `courses`        | Course name normalization and alias matching. |
| `ocr_text`       | Tesseract OCR wrapper for reading scoreboard text. |

### `ui/` — GUI

| Module               | Responsibility |
|----------------------|----------------|
| `app`                | Main `tk.Tk` window — thin shell that hosts a `ttk.Notebook` with three tabs. |
| `fishing_tab`        | All fishing controls, state variables, and the stats overlay window. |
| `gardening_tab`      | Flower selection, sweep/watcher modes, routine progress display. |
| `golfing_tab`        | Action-file picker, shot summary, auto-round toggle. |
| `golf_course_dialog` | Modal dialog for manual course selection. |
| `log_handler`        | Tkinter `logging.Handler` that writes to a `ScrolledText` widget. |
| `calibration`        | Shared calibration result type. |
| `overlay`            | Transparent always-on-top stats window (macOS `NSPanel`). |
| `theme`              | Shared colour constants (`BG`, `FG`, `ACCENT`, `ENTRY_BG`). |

### `config/`

| Module     | Responsibility |
|------------|----------------|
| `settings` | All tuneable constants (thresholds, delays, paths). Supports optional `data/config.toml` overrides at import time. |

### `utils/`

| Module        | Responsibility |
|---------------|----------------|
| `logger`      | Singleton rotating-file + console logger. |
| `debug_frames`| Save annotated vision-pipeline frames to disk for post-session review. |

## Threading Model

```
Main Thread (tkinter event loop)
  ├── FishingBot._thread    (daemon, via BotBase)
  ├── CastRecorder._thread  (daemon, via BotBase)
  ├── GardenBot._thread     (daemon, via BotBase)
  ├── GolfBot._thread       (daemon, via BotBase)
  └── RoutineRunner._thread (daemon, via BotBase)
```

All bots inherit `BotBase` which manages the daemon thread lifecycle.
Bots communicate with the UI via `root.after(0, callback)` to marshal
onto the main thread. Shared state (template cache, calibrated bounds,
debug-frame toggle) is protected by `threading.Lock`.

Stop signals use `threading.Event` (owned by `BotBase`): the UI calls
`bot.stop()`, the bot thread checks `should_stop` each iteration and
exits cleanly.

## Configuration Flow

1. `config/settings.py` defines all constants as module-level variables.
2. At import time, `_apply_toml_overrides()` checks for `data/config.toml`
   and patches any matching variable names (preserving types).
3. Domain modules import from `settings` — never hardcode thresholds.
4. `CastParams` (power/aim curves) are persisted separately in
   `config/cast_params.json` because they're learned, not hand-tuned.

## Vision Pipeline (Fishing)

```
capture_window()
  → detect_pond()          (water mask → largest contour → PondArea)
  → detect_fish_shadows()  (shadow mask → blob analysis → FishCandidate[])
  → find_best_fish()       (score + rank → target (cx, cy))
  → compute_drag()         (calibration transform → drag vector)
  → fishing_cast_at()      (pyautogui mouse drag)
```

## Template Matching

`TemplateMatcher` loads PNG templates from `data/templates/`, caches them in
memory, and runs multi-scale `cv2.matchTemplate` with `TM_CCOEFF_NORMED`.

Scale calibration (in `template_calibration`) runs once per session: it
searches a range of scales against known anchor templates (HUD icons, buttons)
and locks the best-fit scale. Subsequent `find_template` calls use only the
locked scale ± a small offset for speed.
