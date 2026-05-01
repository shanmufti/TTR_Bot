# TTR Bot (macOS)

A macOS automation bot for Toontown Rewritten, inspired by [primetime43's Windows bot](https://github.com/primetime43/Toontown-Rewritten-Bot). Uses computer vision (OpenCV, template matching) to automate fishing, gardening, and golfing.

## Features

- **Auto-fishing** with fish shadow and bubble detection via OpenCV
- **Gardening** with automated planting, watering, picking, and routine playback
- **Golfing** with per-course action replay from JSON files
- **Template matching** for UI button recognition
- **Configurable** cast count, sell rounds, variance, bite timeout
- **Live overlay** showing stats (fish caught, cast count)
- **Sell cycles** with automated walk-to-fisherman sequences

## Download (pre-built app)

Apple Silicon builds are published as **`TTR-Bot-macos-arm64.zip`** on [**GitHub Releases**](https://github.com/shanmufti/TTR_Bot/releases). Unzip and drag **TTR Bot.app** into Applications.

Grant **Screen Recording** and **Accessibility** to **TTR Bot** (the app itself), not only Terminal, under **System Settings → Privacy & Security**.

Intel Macs are not built in CI yet; use **Setup** below or build locally with `./scripts/build_mac_app.sh`.

### Cutting a release (maintainers)

Push a version tag (the workflow attaches the zip to that GitHub Release):

```bash
git tag v0.2.1
git push origin v0.2.1
```

You can also run **Actions → Release (macOS app) → Run workflow** to produce a downloadable artifact without tagging.

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Toontown Rewritten installed and running
- Tesseract OCR (`brew install tesseract`) for golf course detection

## Setup

```bash
git clone https://github.com/shanmufti/TTR_Bot.git
cd TTR_Bot

# Install dependencies and create virtual environment
uv sync
```

## macOS Permissions

You **must** grant two permissions in **System Settings > Privacy & Security**:

1. **Screen Recording** — grant to Terminal (or whichever app runs the bot). Without this, screenshots will only capture the desktop wallpaper.
2. **Accessibility** — grant to Terminal. Without this, pyautogui cannot move the mouse or send clicks.

After granting permissions, restart your terminal.

## Usage

```bash
# Launch the bot GUI
uv run ttr-bot

# Alternative
uv run python -m ttr_bot
```

1. Launch Toontown Rewritten and log in.
2. Walk your toon to a fishing dock, garden, or golf course.
3. In the bot GUI, select the appropriate tab and configure settings.
4. Click **Start**.
5. Press **Stop** or close the window to halt.

## Template Capture

The first time you run the bot, you'll need to capture UI templates:

```bash
uv run python tools/capture_templates.py
```

These are saved in `data/templates/` and reused across sessions.

To refresh the **general calibration** image (bottom-right Schticker Book on the dock), run:

```bash
uv run python tools/snapshot_game_state.py --promote-template
```

while the game is visible. That overwrites `data/templates/Hud_BottomRight_Icon.png`, which **Calibrate** tries first (same dock icon in golf, streets, estate, etc.).

**Calibrate** also falls back to golf, fishing, and garden templates if the HUD image is missing or a poor match; noisy matches may still lock with a relaxed-accept warning in the log.

## Project Structure

```
TTR_Bot/
  pyproject.toml                — Package config and dependencies
  src/ttr_bot/                  — Installable Python package
    __main__.py                 — Entry point (uv run ttr-bot)
    config/settings.py          — Thresholds, delays, paths
    core/                       — Window management, screen capture, input
    fishing/                    — Fishing bot loop, sell sequences
    gardening/                  — Garden bot, navigator, routine runner
    golf/                       — Golf bot, course detection, action replay
    ui/                         — tkinter GUI, tabs, overlay
    utils/                      — Logging
    vision/                     — Template matching, fish/pond detection
  data/                         — Runtime assets
    templates/                  — Captured UI element PNGs
    gardening_routines/         — Recorded garden routines (JSON)
    golf_actions/               — Per-course golf actions (JSON)
    sell_paths/                 — Sell walk sequences (JSON)
  tools/                        — Standalone utility scripts
  tests/                        — Test scripts
```

## Credits

- Fishing detection logic ported from [primetime43/Toontown-Rewritten-Bot](https://github.com/primetime43/Toontown-Rewritten-Bot) (C#/Windows)
- Golf action JSON format compatible with the same project
- Adapted for macOS using Quartz APIs and Python
