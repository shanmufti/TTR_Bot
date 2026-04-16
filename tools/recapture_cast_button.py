#!/usr/bin/env python3
"""Recapture the red fishing cast button template from a live frame.

Finds the red circular button near the bottom-center of the dock view
using color detection, crops it, and saves as the new template.
"""

import cv2
import numpy as np

from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.config import settings


def main() -> None:
    win = find_ttr_window()
    if win is None:
        print("ERROR: TTR window not found")
        return

    frame = capture_window(win)
    if frame is None:
        print("ERROR: capture failed")
        return

    h, w = frame.shape[:2]
    print(f"Frame: {w}x{h}")

    # The cast button is a red circle in the bottom third, center area
    roi_y1 = int(h * 0.60)
    roi_y2 = int(h * 0.85)
    roi_x1 = int(w * 0.30)
    roi_x2 = int(w * 0.70)
    roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Red in HSV wraps around 0/180 — check both ranges
    mask_lo = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([10, 255, 255]))
    mask_hi = cv2.inRange(hsv, np.array([170, 100, 100]), np.array([180, 255, 255]))
    red_mask = mask_lo | mask_hi

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        print("ERROR: no red blobs found in dock area")
        return

    # Pick the largest red blob (the cast button)
    best = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(best)
    x, y, bw, bh = cv2.boundingRect(best)
    print(f"Best red blob: area={area} rect=({x},{y},{bw},{bh}) in ROI")

    # Add padding and convert to frame coordinates
    pad = 15
    abs_x1 = max(0, roi_x1 + x - pad)
    abs_y1 = max(0, roi_y1 + y - pad)
    abs_x2 = min(w, roi_x1 + x + bw + pad)
    abs_y2 = min(h, roi_y1 + y + bh + pad)

    crop = frame[abs_y1:abs_y2, abs_x1:abs_x2]
    print(f"Template crop: {crop.shape[1]}x{crop.shape[0]} at ({abs_x1},{abs_y1})")

    out_path = f"{settings.TEMPLATES_DIR}/Red_Fishing_Button.png"
    cv2.imwrite(out_path, crop)
    print(f"Saved: {out_path}")

    # Also save a debug view
    debug = frame.copy()
    cv2.rectangle(debug, (abs_x1, abs_y1), (abs_x2, abs_y2), (0, 255, 0), 3)
    debug_path = f"{settings.DATA_DIR}/_debug/cast_button_capture.png"
    cv2.imwrite(debug_path, debug)
    print(f"Debug: {debug_path}")

    # Verify: try matching the new template
    result = cv2.matchTemplate(frame, crop, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    print(f"Self-match verify: conf={max_val:.3f} at {max_loc}")


if __name__ == "__main__":
    main()
