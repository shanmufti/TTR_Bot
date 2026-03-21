# TTR Fishing Bot (macOS)

A macOS fishing bot for Toontown Rewritten, inspired by [primetime43's Windows bot](https://github.com/primetime43/Toontown-Rewritten-Bot). Uses computer vision to detect fish shadows and bubbles, then automates the cast-wait-catch loop.

## Features

- **Auto-fishing** with fish shadow detection using OpenCV
- **Bubble detection** to confirm fish presence before casting
- **Template matching** for UI button recognition (red fishing button, popups)
- **Configurable** cast count, sell rounds, variance, bite timeout
- **Overlay** showing live stats (fish caught, cast count)
- **Sell cycles** with automated walk-to-fisherman sequences

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.11+
- Toontown Rewritten installed and running

## Setup

```bash
# Clone the repo
git clone https://github.com/shan-mufti/TTR_Bot.git
cd TTR_Bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## macOS Permissions

You **must** grant two permissions in **System Settings > Privacy & Security**:

1. **Screen Recording** — grant to Terminal (or whichever app runs the bot). Without this, screenshots will only capture the desktop wallpaper.
2. **Accessibility** — grant to Terminal. Without this, pyautogui cannot move the mouse or send clicks.

After granting permissions, restart your terminal.

## Usage

```bash
python main.py
```

1. Launch Toontown Rewritten and log in.
2. Walk your toon to a fishing dock and sit down at it.
3. In the bot GUI, configure your settings (casts, sells, variance).
4. Click **Start Fishing**.
5. Press the **Stop** button or close the window to halt.

## Template Capture

The first time you run the bot, you'll need to capture UI templates. The bot will prompt you to screenshot the red fishing button and other UI elements. These are saved in the `templates/` folder and reused across sessions.

## Project Structure

```
TTR_Bot/
  main.py               — Entry point
  config/settings.py    — Thresholds, delays, defaults
  core/                 — Window management, screen capture, input
  vision/               — Fish detection, template matching, color analysis
  fishing/              — Main bot loop, sell sequences
  templates/            — Captured UI element PNGs
  ui/                   — tkinter GUI and overlay
  utils/                — Logging
```

## Credits

- Fishing detection logic ported from [primetime43/Toontown-Rewritten-Bot](https://github.com/primetime43/Toontown-Rewritten-Bot) (C#/Windows)
- Adapted for macOS using Quartz APIs and Python
