"""CHECKPOINT 3: Live localizer accuracy test.

Captures live frames from TTR and runs SIFT localization against the
garden map.  Walk to each bed in TTR and verify correct identification.

Optionally shows a Tkinter window with the position dot on the schematic.

Usage:
    python test_localizer.py [--map gardening_routines/garden_map.json] [--gui]
"""

from __future__ import annotations

import argparse
import os
import time
import threading
import tkinter as tk

from ttr_bot.config import settings
from ttr_bot.core.window_manager import find_ttr_window
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.vision.localizer import GardenMap, GardenLocalizer, HeadingEstimator, LocalizationResult


def _format_result(frame_num: int, result: LocalizationResult | None) -> str:
    """Format a single localization result for console output."""
    if result is None:
        return f"\rFrame #{frame_num:>4}  |  No match (too few features)"

    line = (
        f"\rFrame #{frame_num:>4}  |  "
        f"Latency: {result.latency_ms:.0f}ms  |  "
        f"Best: {result.best_node_id:<12} "
        f"({result.match_count} matches, "
        f"conf {result.confidence:.2f})"
    )
    if result.second_best_id:
        line += (
            f"  |  2nd: {result.second_best_id:<12} "
            f"(conf {result.second_best_conf:.2f})"
        )
    line += f"  |  Pos: ({result.map_x:.0f}, {result.map_y:.0f})"
    return line


def _capture_frame():
    """Capture a live TTR frame. Returns (frame, wait_time) or (None, wait_time)."""
    win = find_ttr_window()
    if win is None:
        return None, 1.0
    frame = capture_window(win)
    if frame is None:
        return None, 0.2
    return frame, 0.0


def _run_console(localizer: GardenLocalizer, garden_map: GardenMap) -> None:
    """Continuously localize and print results with heading."""
    frame_num = 0
    heading_est = HeadingEstimator()
    print("\nLOCALIZER TEST — press Ctrl-C to stop")
    print("Walk to each bed in TTR and verify correct identification.\n")

    try:
        while True:
            frame, wait = _capture_frame()
            if frame is None:
                msg = "TTR window not found..." if wait >= 1.0 else "capture failed..."
                print(f"\r  {msg}", end="", flush=True)
                time.sleep(wait)
                continue

            result = localizer.localize(frame)
            frame_num += 1
            line = _format_result(frame_num, result)
            if result is not None:
                heading = heading_est.update(result)
                if heading is not None:
                    line += f"  |  Heading: {heading:.0f}°"
            print(line, end="", flush=True)
            time.sleep(settings.NAV_RECHECK_INTERVAL_MS / 1000.0)

    except KeyboardInterrupt:
        print("\n\nDone.")


def _draw_map_nodes(canvas: tk.Canvas, garden_map: GardenMap) -> None:
    """Draw bed and waypoint nodes on the canvas."""
    for node in garden_map.nodes:
        color = "#4ecca3" if node.node_type == "bed" else "#555555"
        r = 8 if node.node_type == "bed" else 4
        x, y = node.map_x, node.map_y
        canvas.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="")
        if node.node_type == "bed":
            canvas.create_text(x, y - 14, text=node.id,
                               fill="#eaeaea", font=("Helvetica", 8))


def _gui_update_loop(
    localizer: GardenLocalizer, heading_est: HeadingEstimator,
    root: tk.Tk, dot_id: int, info_var: tk.StringVar, canvas: tk.Canvas,
    stop_event: threading.Event,
) -> None:
    """Background thread: localize and push updates to the GUI."""
    while not stop_event.is_set():
        frame, wait = _capture_frame()
        if frame is None:
            time.sleep(wait)
            continue

        result = localizer.localize(frame)
        if result is not None:
            heading = heading_est.update(result)
            root.after(0, _gui_draw_result, canvas, dot_id,
                       info_var, result, heading)

        time.sleep(settings.NAV_RECHECK_INTERVAL_MS / 1000.0)


def _gui_draw_result(
    canvas: tk.Canvas, dot_id: int,
    info_var: tk.StringVar, r: LocalizationResult,
    heading: float | None,
) -> None:
    import math
    x, y = r.map_x, r.map_y
    canvas.coords(dot_id, x - 6, y - 6, x + 6, y + 6)

    heading_str = f"  Heading: {heading:.0f}°" if heading is not None else ""
    info_var.set(
        f"Best: {r.best_node_id:<12}  "
        f"({r.match_count} matches, conf {r.confidence:.2f})  "
        f"Latency: {r.latency_ms:.0f}ms  "
        f"Pos: ({r.map_x:.0f}, {r.map_y:.0f}){heading_str}"
    )

    if heading is not None and hasattr(canvas, "heading_line"):
        arrow_len = 25
        ex = x + arrow_len * math.cos(math.radians(heading))
        ey = y + arrow_len * math.sin(math.radians(heading))
        canvas.coords(canvas.heading_line, x, y, ex, ey)


def _run_gui(localizer: GardenLocalizer, garden_map: GardenMap) -> None:
    """Tkinter window showing position dot on the schematic."""
    root = tk.Tk()
    root.title("Localizer Test")
    root.configure(bg="#1a1a2e")

    canvas = tk.Canvas(root, width=650, height=650,
                       bg="#16213e", highlightthickness=0)
    canvas.pack(padx=10, pady=10)

    info_var = tk.StringVar(value="Waiting...")
    tk.Label(root, textvariable=info_var, font=("Courier", 11),
             fg="#eaeaea", bg="#1a1a2e", anchor="w", justify="left").pack(
                 padx=10, pady=(0, 10), fill="x")

    _draw_map_nodes(canvas, garden_map)

    dot_id = canvas.create_oval(0, 0, 0, 0, fill="#e94560", outline="white")
    canvas.heading_line = canvas.create_line(0, 0, 0, 0, fill="#e94560", width=2)

    heading_est = HeadingEstimator()
    stop_event = threading.Event()

    def _on_close():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    t = threading.Thread(
        target=_gui_update_loop,
        args=(localizer, heading_est, root, dot_id, info_var, canvas, stop_event),
        daemon=True,
    )
    t.start()
    root.mainloop()
    stop_event.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Live localizer test")
    default_map = os.path.join(settings.GARDENING_ROUTINES_DIR, "garden_map.json")
    parser.add_argument("--map", default=default_map, help="Path to garden_map.json")
    parser.add_argument("--gui", action="store_true", help="Show Tkinter schematic")
    args = parser.parse_args()

    if not os.path.isfile(args.map):
        print(f"Error: map file not found: {args.map}")
        print("Run a demo recording + processing first.")
        return

    garden_map = GardenMap.load(args.map)
    localizer = GardenLocalizer(garden_map)

    print(f"Loaded map: {len(garden_map.bed_nodes)} beds, "
          f"{len(garden_map.waypoint_nodes)} waypoints")

    if args.gui:
        _run_gui(localizer, garden_map)
    else:
        _run_console(localizer, garden_map)


if __name__ == "__main__":
    main()
