#!/usr/bin/env python3
"""Diagnose template matching: capture a frame and check every anchor + the
red fishing button at a range of scales, report the best match for each."""

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.vision.template_matcher import _CALIBRATION_ANCHORS, _load_template

SCALES = np.arange(0.5, 1.6, 0.1)
_MIN_TEMPLATE_DIM = 10
_CONF_GOOD = 0.65
_CONF_LOW = 0.48

TEMPLATES_TO_CHECK = list(dict.fromkeys([*_CALIBRATION_ANCHORS, "red_fishing_button"]))


def main() -> None:
    win = find_ttr_window()
    if win is None:
        print("ERROR: TTR window not found")
        return

    print(f"Window: {win.width}x{win.height} at ({win.x},{win.y})")
    frame = capture_window(win)
    if frame is None:
        print("ERROR: capture failed")
        return
    print(f"Frame: {frame.shape[1]}x{frame.shape[0]} (retina)\n")

    out_path = f"{settings.DATA_DIR}/_debug/template_diag.png"

    annotations = []

    for name in TEMPLATES_TO_CHECK:
        tmpl = _load_template(name)
        if tmpl is None:
            print(f"  {name:30s}  MISSING")
            continue

        best_val, best_scale, best_loc = -1.0, 1.0, (0, 0)
        for scale in SCALES:
            th, tw = tmpl.shape[:2]
            new_w = int(tw * scale)
            new_h = int(th * scale)
            fh, fw = frame.shape[:2]
            if new_w < _MIN_TEMPLATE_DIM or new_h < _MIN_TEMPLATE_DIM or new_w > fw or new_h > fh:
                continue
            scaled = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            result = cv2.matchTemplate(frame, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_val:
                best_val = max_val
                best_scale = scale
                best_loc = max_loc
                best_size = (new_w, new_h)

        status = "OK" if best_val >= _CONF_GOOD else "LOW" if best_val >= _CONF_LOW else "FAIL"
        print(
            f"  {name:30s}  conf={best_val:.3f}  scale={best_scale:.2f}  at={best_loc}  [{status}]"
        )

        if best_val >= _CONF_LOW:
            cx = best_loc[0] + best_size[0] // 2
            cy = best_loc[1] + best_size[1] // 2
            color = (0, 255, 0) if best_val >= _CONF_GOOD else (0, 165, 255)
            annotations.append((cx, cy, best_size[0], best_size[1], name, best_val, color))

    out = frame.copy()
    for cx, cy, w, h, name, conf, color in annotations:
        pt1 = (cx - w // 2, cy - h // 2)
        pt2 = (cx + w // 2, cy + h // 2)
        cv2.rectangle(out, pt1, pt2, color, 2)
        cv2.putText(
            out,
            f"{name} {conf:.2f}",
            (pt1[0], pt1[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )

    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, out)
    print(f"\nAnnotated frame saved: {out_path}")


if __name__ == "__main__":
    main()
