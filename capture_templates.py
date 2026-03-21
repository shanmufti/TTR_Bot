#!/usr/bin/env python3
"""Interactive template capture utility.

Run this while at a fishing dock in TTR. It takes a screenshot, opens a
preview, and lets you click-drag to select each UI element the bot needs.

Usage:
    python capture_templates.py
"""

import os
import sys
import cv2
import numpy as np

from core.window_manager import find_ttr_window
from core.screen_capture import capture_window
from config.settings import TEMPLATES_DIR

TEMPLATES_TO_CAPTURE = [
    ("Red_Fishing_Button.png", "RED FISHING BUTTON (the cast button at bottom-center)"),
    ("Exit_Fishing_Button.png", "EXIT FISHING BUTTON (button to leave the dock)"),
    ("FishPopupCloseButton.png", "FISH CAUGHT POPUP CLOSE BUTTON (X or close on the catch popup)"),
    ("Blue_Sell_All_Button.png", "SELL ALL BUTTON (at the fisherman NPC)"),
    ("Blue_Ok_Button.png", "BLUE OK BUTTON (confirmation dialogs)"),
    ("FishBucketFullPopup.png", "BUCKET FULL POPUP (the popup when your bucket is full — skip if not visible)"),
]

selection = {"start": None, "end": None, "drawing": False}


def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        selection["start"] = (x, y)
        selection["drawing"] = True
    elif event == cv2.EVENT_MOUSEMOVE and selection["drawing"]:
        selection["end"] = (x, y)
    elif event == cv2.EVENT_LBUTTONUP:
        selection["end"] = (x, y)
        selection["drawing"] = False


def capture_one(frame: np.ndarray, filename: str, description: str) -> bool:
    """Show the screenshot and let the user select a region.

    Returns True if a template was saved, False if skipped.
    """
    display = frame.copy()
    # Scale down for display if too large
    max_w = 1400
    scale = min(1.0, max_w / display.shape[1])
    if scale < 1.0:
        display = cv2.resize(display, None, fx=scale, fy=scale)

    win_name = f"Select: {description}"
    cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(win_name, mouse_callback)

    selection["start"] = None
    selection["end"] = None
    selection["drawing"] = False

    print(f"\n>>> Draw a box around the {description}")
    print("    Press ENTER to confirm, S to skip, Q to quit")

    while True:
        shown = display.copy()

        cv2.putText(
            shown, f"Select: {description}", (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
        )
        cv2.putText(
            shown, "ENTER=save  S=skip  Q=quit", (10, 55),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
        )

        if selection["start"] and selection["end"]:
            cv2.rectangle(shown, selection["start"], selection["end"], (0, 255, 0), 2)

        cv2.imshow(win_name, shown)
        key = cv2.waitKey(30) & 0xFF

        if key == 13:  # ENTER
            if selection["start"] and selection["end"]:
                x1 = int(min(selection["start"][0], selection["end"][0]) / scale)
                y1 = int(min(selection["start"][1], selection["end"][1]) / scale)
                x2 = int(max(selection["start"][0], selection["end"][0]) / scale)
                y2 = int(max(selection["start"][1], selection["end"][1]) / scale)

                if x2 > x1 + 5 and y2 > y1 + 5:
                    crop = frame[y1:y2, x1:x2]
                    os.makedirs(TEMPLATES_DIR, exist_ok=True)
                    path = os.path.join(TEMPLATES_DIR, filename)
                    cv2.imwrite(path, crop)
                    print(f"    Saved → {path}  ({crop.shape[1]}x{crop.shape[0]})")
                    cv2.destroyWindow(win_name)
                    return True
                else:
                    print("    Selection too small, try again")
            else:
                print("    No selection drawn yet")

        elif key == ord("s"):
            print(f"    Skipped {filename}")
            cv2.destroyWindow(win_name)
            return False

        elif key == ord("q"):
            cv2.destroyAllWindows()
            sys.exit(0)

    return False


def main():
    print("=" * 60)
    print("  TTR Bot — Template Capture Tool")
    print("=" * 60)
    print()
    print("Make sure you're at a FISHING DOCK in TTR before continuing.")
    print("(The red cast button should be visible on screen.)")
    print()
    input("Press Enter when ready...")

    win = find_ttr_window()
    if win is None:
        print("ERROR: TTR window not found. Is the game running?")
        sys.exit(1)

    frame = capture_window(win)
    if frame is None:
        print("ERROR: Could not capture screenshot. Check Screen Recording permission.")
        sys.exit(1)

    print(f"\nCaptured game screenshot: {frame.shape[1]}x{frame.shape[0]}")
    print(f"Templates will be saved to: {TEMPLATES_DIR}\n")

    saved = 0
    for filename, description in TEMPLATES_TO_CAPTURE:
        existing = os.path.join(TEMPLATES_DIR, filename)
        if os.path.exists(existing):
            print(f"  Already exists: {filename} — recapturing anyway")

        if capture_one(frame, filename, description):
            saved += 1

    cv2.destroyAllWindows()
    print(f"\n{'=' * 60}")
    print(f"  Done! Captured {saved}/{len(TEMPLATES_TO_CAPTURE)} templates.")
    print(f"  Templates saved in: {TEMPLATES_DIR}")
    print(f"{'=' * 60}")

    if saved < 2:
        print("\n  WARNING: You need at least the Red Fishing Button and")
        print("  Fish Popup Close Button for the bot to work.\n")


if __name__ == "__main__":
    main()
