#!/usr/bin/env python3
"""Capture the TTR window for debugging or to refresh the HUD calibration template.

The bottom-right dock (Schticker Book) stays on-screen in most states, so we crop
that region and can save it as ``Hud_BottomRight_Icon.png`` for ``calibrate_scale``.

Usage:
    uv run python tools/snapshot_game_state.py
    uv run python tools/snapshot_game_state.py --promote-template
"""

import argparse
import os
import sys
from datetime import datetime

import cv2

from ttr_bot.config import settings
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window

# Fraction of window from bottom-right corner (book + small margin).
_BOTTOM_FRAC_H = 0.16
_RIGHT_FRAC_W = 0.14


def _bottom_right_roi(frame_bgr):
    h, w = frame_bgr.shape[:2]
    rw = max(48, int(w * _RIGHT_FRAC_W))
    rh = max(48, int(h * _BOTTOM_FRAC_H))
    return frame_bgr[h - rh : h, w - rw : w]


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture TTR window + bottom-right HUD ROI.")
    parser.add_argument(
        "--promote-template",
        action="store_true",
        help=f"Write ROI to {settings.TEMPLATES_DIR}/Hud_BottomRight_Icon.png (overwrites).",
    )
    parser.add_argument(
        "--debug-dir",
        default=os.path.join(settings.PROJECT_ROOT, "data", "_debug"),
        help="Directory for full snapshot + ROI previews.",
    )
    args = parser.parse_args()

    win = find_ttr_window()
    if win is None:
        print("Toontown Rewritten window not found.", file=sys.stderr)
        return 1

    frame = capture_window(win)
    if frame is None:
        print("Screen capture failed.", file=sys.stderr)
        return 1

    os.makedirs(args.debug_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_path = os.path.join(args.debug_dir, f"ttr_full_{ts}.png")
    roi_path = os.path.join(args.debug_dir, f"bottom_right_roi_{ts}.png")
    cv2.imwrite(full_path, frame)
    roi = _bottom_right_roi(frame)
    cv2.imwrite(roi_path, roi)
    print(f"Wrote {full_path}")
    print(f"Wrote {roi_path} ({roi.shape[1]}x{roi.shape[0]} px)")

    if args.promote_template:
        os.makedirs(settings.TEMPLATES_DIR, exist_ok=True)
        dest = os.path.join(settings.TEMPLATES_DIR, "Hud_BottomRight_Icon.png")
        cv2.imwrite(dest, roi)
        print(f"Promoted ROI -> {dest}")
        print("Restart the bot or click Calibrate again (template cache clears on calibrate).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
