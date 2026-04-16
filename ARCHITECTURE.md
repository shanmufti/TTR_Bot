# Architecture

This document describes the module structure, data flow, and key design
decisions in TTR Bot.

## High-Level Overview

```
┌─────────────────────────────────────────────┐
│                   UI (tkinter)              │
│  FishingTab  │  GardeningTab  │  GolfingTab │
└──────┬───────┴───────┬────────┴──────┬──────┘
       │               │               │
       ▼               ▼               ▼
┌─────────────┐ ┌─────────────┐ ┌────────────┐
│ FishingBot  │ │ GardenBot   │ │  GolfBot   │
│ CastRecorder│ │ Sweeper     │ │ ActionPlayer│
│             │ │ Watcher     │ │ Detector   │
└──────┬──────┘ └──────┬──────┘ └─────┬──────┘
       │               │              │
       ▼               ▼              ▼
┌─────────────────────────────────────────────┐
│              Vision Layer                   │
│  TemplateMatcher  ColorMatcher  FishDetector│
│  PondDetector  FlowerDetector  BubbleDetect │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│              Core Layer                     │
│  WindowManager  ScreenCapture  InputControl │
│  CastCalibration  CastParams  Errors        │
└─────────────────────────────────────────────┘
```

Dependencies flow **downward**: UI → domain bots → vision → core. No upward
or circular imports.

## Module Guide

### `core/` — Platform Abstraction

| Module              | Responsibility |
|---------------------|----------------|
| `window_manager`    | Find the TTR window via Quartz, read bounds, bring to front. Thread-safe calibrated-bounds cache. |
| `screen_capture`    | Grab a BGR numpy frame of the game window using `CGWindowListCreateImage`. |
| `input_controller`  | Click, drag, key-press via pyautogui with Retina-scale correction. Fishing cast vector math. |
| `cast_calibration`  | Auto-calibration: cast 3 known drags, detect bobber via frame-diff, fit a linear transform. |
| `cast_params`       | Dataclass + JSON persistence for tuned power/aim curve constants. |
| `errors`            | Exception hierarchy: `TTRBotError` → `WindowNotFoundError`, `CalibrationError`, etc. |

### `vision/` — Computer Vision

| Module             | Responsibility |
|--------------------|----------------|
| `template_matcher` | Multi-scale OpenCV `matchTemplate` with caching and auto-scale calibration. Thread-safe `TemplateMatcher` class; module-level functions delegate to a default instance. |
| `color_matcher`    | HSV/BGR pixel classification: water, shadow, bubble colours. Builds binary masks and computes average water brightness. |
| `fish_detector`    | Blob analysis on the shadow mask inside the pond ROI. Scores candidates by size, shape, bubble proximity. |
| `pond_detector`    | Finds the pond bounding box from a water mask using contour analysis. |
| `flower_detector`  | Detects garden flowers as red-near-green colour blobs for the sweeper's navigation. |
| `bubble_detector`  | Detects fish bubbles (small bright spots in the pond) to boost shadow scores. |

### `fishing/` — Fishing Automation

| Module          | Responsibility |
|-----------------|----------------|
| `fishing_bot`   | Main loop: find button → detect shadow → cast → wait for bite → repeat. Runs in a daemon thread. |
| `cast_recorder` | Passive mode: watches the user fish manually, records drag vectors and landing positions, then fits cast params. |
| `sell_controller`| Walk-to-fisherman sell sequences loaded from JSON. |

### `gardening/` — Garden Automation

| Module           | Responsibility |
|------------------|----------------|
| `gardening_bot`  | Core plant/water/pick logic. Drives the bean-colour input sequence for a chosen flower. |
| `flowers`        | Static flower database: names, bean sequences, jellybean costs. |
| `bed_ui`         | Detect and classify garden-bed UI buttons (Pick / Plant / Water / Remove). |
| `garden_sweeper` | Vision-guided navigation: scan for flowers on screen, steer toward them, interact with beds. |
| `garden_watcher` | Passive poller: the user walks manually; the watcher auto-acts when bed buttons appear. |
| `routine_runner` | Orchestrates a full sweep routine in a background thread with progress callbacks. |

### `golf/` — Golf Automation

| Module          | Responsibility |
|-----------------|----------------|
| `golf_bot`      | Round loop: detect course → load actions → replay shots → repeat. |
| `action_player` | Execute a list of `GolfActionCommand` (key presses with durations). |
| `detector`      | Course detection via OCR + template matching; swing-readiness check. |
| `courses`       | Course name normalization and alias matching. |
| `ocr_text`      | Tesseract OCR wrapper for reading scoreboard text. |

### `ui/` — GUI

| Module          | Responsibility |
|-----------------|----------------|
| `app`           | Main `tk.Tk` window — thin shell that hosts a `ttk.Notebook` with three tabs. Polls window status. |
| `fishing_tab`   | All fishing controls, state variables, and the stats overlay window. |
| `gardening_tab` | Flower selection, sweep/watcher modes, routine progress display. |
| `golfing_tab`   | Action-file picker, shot summary, auto-round toggle. |
| `calibration`   | `CalibrationResult` NamedTuple shared across tabs. |
| `overlay`       | Transparent always-on-top stats window (macOS `NSPanel`). |
| `theme`         | Shared colour constants (`BG`, `FG`, `ACCENT`, `ENTRY_BG`). |

### `config/`

| Module     | Responsibility |
|------------|----------------|
| `settings` | All tuneable constants (thresholds, delays, paths, magic numbers). Supports optional `data/config.toml` overrides at import time. |

### `utils/`

| Module        | Responsibility |
|---------------|----------------|
| `logger`      | Singleton rotating-file + console logger. |
| `debug_frames`| Save annotated vision-pipeline frames to disk for post-session review. |

## Threading Model

```
Main Thread (tkinter event loop)
  ├── FishingBot._thread   (daemon)
  ├── CastRecorder._thread (daemon)
  ├── GardenBot._thread    (daemon)
  ├── GolfBot._thread      (daemon)
  └── RoutineRunner._thread(daemon)
```

Each bot runs its loop in a daemon thread and communicates with the UI via
`root.after(0, callback)` to marshal onto the main thread. Shared state
(template cache, calibrated bounds, debug-frame toggle) is protected by
`threading.Lock`.

Stop signals use `threading.Event`: the UI sets the event, the bot thread
checks it each iteration and exits cleanly.

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

Scale calibration runs once per session: it searches a range of scales against
known anchor templates (HUD icons, buttons) and locks the best-fit scale.
Subsequent `find_template` calls use only the locked scale ± a small offset
for speed.
