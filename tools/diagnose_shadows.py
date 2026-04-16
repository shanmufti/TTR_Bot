#!/usr/bin/env python3
"""Diagnose fish shadow detection: capture frames, show what the vision sees."""

import time

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.vision.color_matcher import (
    average_water_brightness,
    build_relative_shadow_mask,
    build_water_mask,
)
from ttr_bot.vision.fish_detector import detect_fish_shadows, find_best_fish, find_best_moving_fish
from ttr_bot.vision.pond_detector import detect_pond

OUT = f"{settings.DATA_DIR}/_debug"


def annotate_frame(frame, pond, candidates, best, label):
    out = frame.copy()

    cv2.rectangle(
        out, (pond.x, pond.y), (pond.x + pond.width, pond.y + pond.height), (0, 255, 0), 2
    )

    margin_x = pond.width * 15 // 100
    margin_y = pond.height * 20 // 100
    ix, iy = pond.x + margin_x, pond.y + margin_y
    iw, ih = pond.width - 2 * margin_x, pond.height - 2 * margin_y
    cv2.rectangle(out, (ix, iy), (ix + iw, iy + ih), (0, 200, 0), 1)

    for c in candidates:
        color = (0, 255, 255) if c.has_bubbles else (0, 165, 255)
        cv2.circle(out, (c.cx, c.cy), 14, color, 2)
        cv2.putText(
            out,
            f"{c.size}px s={c.score:.2f}",
            (c.cx + 16, c.cy - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )

    if best:
        cv2.circle(out, best, 18, (0, 255, 0), 3)

    cv2.putText(out, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    return out


def save_masks(frame, pond, label):
    """Save intermediate vision masks for inspection."""
    margin_x = pond.width * 15 // 100
    margin_y = pond.height * 20 // 100
    ix, iy = pond.x + margin_x, pond.y + margin_y
    iw, ih = pond.width - 2 * margin_x, pond.height - 2 * margin_y
    crop = frame[iy : iy + ih, ix : ix + iw]

    water = build_water_mask(crop)
    shadow = build_relative_shadow_mask(crop, water)

    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    shadow_clean = cv2.morphologyEx(shadow, cv2.MORPH_OPEN, open_kernel)

    cv2.imwrite(f"{OUT}/shadow_{label}_water_mask.png", water)
    cv2.imwrite(f"{OUT}/shadow_{label}_shadow_mask.png", shadow)
    cv2.imwrite(f"{OUT}/shadow_{label}_shadow_clean.png", shadow_clean)
    cv2.imwrite(f"{OUT}/shadow_{label}_crop.png", crop)
    water_pct = 100 * np.count_nonzero(water) / water.size
    print(f"  Water pixels: {np.count_nonzero(water)} / {water.size} ({water_pct:.1f}%)")
    print(f"  Shadow pixels: {np.count_nonzero(shadow_clean)} / {shadow_clean.size}")


def main():
    import os

    os.makedirs(OUT, exist_ok=True)

    win = find_ttr_window()
    if not win:
        print("TTR window not found")
        return

    print(f"Window: {win.width}x{win.height}")

    # Frame 1
    f1 = capture_window(win)
    if f1 is None:
        print("Capture failed")
        return

    pond = detect_pond(f1)
    print(f"Pond: {pond.width}x{pond.height} at ({pond.x},{pond.y}) empty={pond.empty}")

    if pond.empty:
        print("No pond detected!")
        return

    crop = f1[pond.y : pond.y + pond.height, pond.x : pond.x + pond.width]
    wm = build_water_mask(crop)
    avg_bright = average_water_brightness(crop, wm)
    print(f"Water brightness: {avg_bright}")

    print("\n--- Frame 1 ---")
    c1 = detect_fish_shadows(f1, pond, avg_bright)
    b1 = find_best_fish(f1, pond, avg_bright)
    save_masks(f1, pond, "f1")
    ann1 = annotate_frame(f1, pond, c1, b1, "Frame 1")
    cv2.imwrite(f"{OUT}/shadow_f1_annotated.png", ann1)
    print(f"  Candidates: {len(c1)}")
    for c in c1:
        print(f"    ({c.cx},{c.cy}) area={c.size} score={c.score:.2f} bubbles={c.has_bubbles}")

    # Wait and capture frame 2
    print("\nWaiting 3s for shadows to move...")
    time.sleep(3.0)

    f2 = capture_window(win)
    if f2 is None:
        print("Capture 2 failed")
        return

    print("--- Frame 2 ---")
    c2 = detect_fish_shadows(f2, pond, avg_bright)
    b2 = find_best_fish(f2, pond, avg_bright)
    save_masks(f2, pond, "f2")
    ann2 = annotate_frame(f2, pond, c2, b2, "Frame 2 (+3s)")
    cv2.imwrite(f"{OUT}/shadow_f2_annotated.png", ann2)
    print(f"  Candidates: {len(c2)}")
    for c in c2:
        print(f"    ({c.cx},{c.cy}) area={c.size} score={c.score:.2f} bubbles={c.has_bubbles}")

    # Compare — did anything move?
    if c1 and c2:
        print("\n--- Movement analysis ---")
        for i, s1 in enumerate(c1):
            closest = min(c2, key=lambda s: abs(s.cx - s1.cx) + abs(s.cy - s1.cy))
            dx = closest.cx - s1.cx
            dy = closest.cy - s1.cy
            moved = abs(dx) > 10 or abs(dy) > 10
            state = "MOVED" if moved else "STATIC"
            print(
                f"  Shadow {i}: ({s1.cx},{s1.cy}) -> ({closest.cx},{closest.cy})"
                f" delta=({dx:+d},{dy:+d}) {state}"
            )

    # Test the combined motion-based best-fish picker
    print("\n--- Motion-based best fish (new method) ---")

    def _cap():
        return capture_window(win)

    best_moving = find_best_moving_fish(_cap, pond, avg_bright)
    if best_moving:
        print(f"  Best moving fish: {best_moving}")
    else:
        print("  No moving fish found")

    print(f"\nSaved to {OUT}/shadow_*.png")


if __name__ == "__main__":
    main()
