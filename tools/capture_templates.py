#!/usr/bin/env python3
"""Interactive template capture utility using tkinter (macOS-friendly).

Run this while in TTR. It takes a live screenshot and opens a tkinter window
where you click-drag to select each UI element the bot needs.

Usage:
    python capture_templates.py              # fishing templates
    python capture_templates.py --gardening  # gardening templates
    python capture_templates.py --golf      # golf (pencil, scoreboard close, turn timer)
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from ttr_bot.config.settings import TEMPLATES_DIR
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window

FISHING_TEMPLATES = [
    ("Red_Fishing_Button.png", "RED FISHING BUTTON (cast button at bottom-center)"),
    ("Exit_Fishing_Button.png", "EXIT FISHING BUTTON (button to leave the dock)"),
    ("FishPopupCloseButton.png", "FISH CAUGHT POPUP CLOSE (X on the catch popup)"),
    ("Blue_Sell_All_Button.png", "SELL ALL BUTTON (at the fisherman NPC)"),
    ("Blue_Ok_Button.png", "BLUE OK BUTTON (confirmation dialogs)"),
    ("FishBucketFullPopup.png", "BUCKET FULL POPUP (skip if not visible)"),
]

GARDEN_STEP1_EMPTY_BED = [
    ("Plant_Flower_Button.png", "PLANT FLOWER BUTTON (on an empty flower bed)"),
]

GARDEN_STEP2_BEAN_PICKER = [
    ("Red_Jellybean_Button.png", "RED JELLYBEAN BUTTON"),
    ("Green_Jellybean_Button.png", "GREEN JELLYBEAN BUTTON"),
    ("Orange_Jellybean_Button.png", "ORANGE JELLYBEAN BUTTON"),
    ("Purple_Jellybean_Button.png", "PURPLE JELLYBEAN BUTTON"),
    ("Blue_Jellybean_Button.png", "BLUE JELLYBEAN BUTTON"),
    ("Pink_Jellybean_Button.png", "PINK JELLYBEAN BUTTON"),
    ("Yellow_Jellybean_Button.png", "YELLOW JELLYBEAN BUTTON"),
    ("Cyan_Jellybean_Button.png", "CYAN JELLYBEAN BUTTON"),
    ("Silver_Jellybean_Button.png", "SILVER JELLYBEAN BUTTON"),
    ("Blue_Plant_Button.png", "BLUE PLANT BUTTON (confirm after picking beans)"),
]

GARDEN_STEP3_POST_PLANT = [
    ("Blue_Ok_Button.png", "BLUE OK BUTTON (dialog after planting)"),
]

GARDEN_STEP4_PLANTED_BED = [
    ("Watering_Can_Button.png", "WATERING CAN BUTTON"),
    ("Pick_Flower_Button.png", "PICK FLOWER BUTTON (remove existing flower)"),
]

# Filenames must match config.settings.TEMPLATE_NAMES (golf_* keys).
GOLF_STEP1_PENCIL = [
    (
        "Golf_Pencil_Button.png",
        "GOLF PENCIL (scoreboard icon — small pencil on the golf HUD)",
    ),
]
GOLF_STEP2_SCOREBOARD = [
    (
        "Golf_Close_Button.png",
        "GOLF SCOREBOARD RED X (close button on the open scoreboard)",
    ),
]
GOLF_STEP3_TURN_TIMER = [
    (
        "Golf_Turn_Timer.png",
        "ORANGE TURN TIMER (small clock in the top-right when it's your swing)",
    ),
]


class CaptureApp:
    """Single tkinter root that handles all template captures sequentially."""

    def __init__(self, task_list: list[tuple[str, np.ndarray]]):
        """*task_list*: [(filename, description, frame_bgr), ...]"""
        self._tasks = task_list
        self._task_idx = 0
        self._saved = 0

        self._start = None
        self._end = None
        self._rect_id = None
        self._tk_img = None

        self._root = tk.Tk()
        self._root.title("TTR Bot — Template Capture")
        self._root.configure(bg="#222")
        self._root.protocol("WM_DELETE_WINDOW", self._on_quit)

        # Header label
        self._header_var = tk.StringVar()
        tk.Label(
            self._root,
            textvariable=self._header_var,
            fg="#ffff00",
            bg="#222",
            font=("Helvetica", 13, "bold"),
            wraplength=700,
            justify="left",
        ).pack(fill="x", padx=10, pady=(8, 0))

        # Counter label
        self._counter_var = tk.StringVar()
        tk.Label(
            self._root,
            textvariable=self._counter_var,
            fg="#a0a0a0",
            bg="#222",
            font=("Helvetica", 11),
        ).pack(fill="x", padx=10, pady=(0, 4))

        # Buttons (macOS native buttons -- use highlightbackground for tint)
        btn_frame = tk.Frame(self._root, bg="#222")
        btn_frame.pack(fill="x", padx=8, pady=6)
        tk.Button(
            btn_frame,
            text="✓ Save (Enter)",
            font=("Helvetica", 13, "bold"),
            highlightbackground="#1a8f3c",
            width=14,
            command=self._on_save,
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            btn_frame,
            text="Skip (S)",
            font=("Helvetica", 13),
            highlightbackground="#b8860b",
            width=12,
            command=self._on_skip,
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            btn_frame,
            text="Quit (Q)",
            font=("Helvetica", 13),
            highlightbackground="#e94560",
            width=12,
            command=self._on_quit,
        ).pack(side="left")

        # Keyboard shortcuts
        self._root.bind("<Return>", lambda e: self._on_save())
        self._root.bind("<s>", lambda e: self._on_skip())
        self._root.bind("<q>", lambda e: self._on_quit())

        # Canvas (placeholder size, updated per task)
        self._canvas = tk.Canvas(
            self._root,
            cursor="crosshair",
            highlightthickness=0,
            bg="#111",
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        self._load_task()

        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.after(200, lambda: self._root.attributes("-topmost", False))

    @property
    def saved_count(self) -> int:
        return self._saved

    def run(self) -> None:
        self._root.mainloop()

    # ------------------------------------------------------------------

    def _load_task(self) -> None:
        if self._task_idx >= len(self._tasks):
            self._root.quit()
            return

        filename, description, frame_bgr = self._tasks[self._task_idx]
        self._cur_filename = filename
        self._cur_frame = frame_bgr

        fh, fw = frame_bgr.shape[:2]
        max_w = 1400
        self._scale = min(1.0, max_w / fw)
        disp_w = int(fw * self._scale)
        disp_h = int(fh * self._scale)

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if self._scale < 1.0:
            frame_rgb = cv2.resize(frame_rgb, (disp_w, disp_h))
        pil_img = Image.fromarray(frame_rgb)
        self._tk_img = ImageTk.PhotoImage(pil_img)

        self._canvas.config(width=disp_w, height=disp_h)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._tk_img)

        self._start = None
        self._end = None
        self._rect_id = None

        n = self._task_idx + 1
        total = len(self._tasks)
        self._header_var.set(f"Draw a box around: {description}")
        self._counter_var.set(f"Template {n}/{total}  —  {filename}")
        self._root.geometry(f"{disp_w}x{disp_h + 100}")

        print(f"\n>>> [{n}/{total}] Select: {description}")

    def _advance(self) -> None:
        self._task_idx += 1
        self._load_task()

    # ------------------------------------------------------------------
    # Mouse handlers
    # ------------------------------------------------------------------

    def _on_press(self, event):
        self._start = (event.x, event.y)
        self._end = None
        if self._rect_id:
            self._canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event):
        self._end = (event.x, event.y)
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(
            self._start[0],
            self._start[1],
            event.x,
            event.y,
            outline="#00ff00",
            width=2,
        )

    def _on_release(self, event):
        self._end = (event.x, event.y)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        if not self._start or not self._end:
            messagebox.showwarning("No selection", "Draw a box first!")
            return

        s = self._scale
        x1 = int(min(self._start[0], self._end[0]) / s)
        y1 = int(min(self._start[1], self._end[1]) / s)
        x2 = int(max(self._start[0], self._end[0]) / s)
        y2 = int(max(self._start[1], self._end[1]) / s)

        if x2 <= x1 + 5 or y2 <= y1 + 5:
            messagebox.showwarning("Too small", "Selection is too small, try again.")
            return

        crop = self._cur_frame[y1:y2, x1:x2]
        os.makedirs(TEMPLATES_DIR, exist_ok=True)
        path = os.path.join(TEMPLATES_DIR, self._cur_filename)
        cv2.imwrite(path, crop)
        print(f"    Saved → {path}  ({crop.shape[1]}x{crop.shape[0]})")
        self._saved += 1
        self._advance()

    def _on_skip(self) -> None:
        print(f"    Skipped {self._cur_filename}")
        self._advance()

    def _on_quit(self) -> None:
        self._root.quit()
        self._root.destroy()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _capture_frame() -> np.ndarray:
    win = find_ttr_window()
    if win is None:
        print("ERROR: TTR window not found. Is the game running?")
        sys.exit(1)

    frame = capture_window(win)
    if frame is None:
        print("ERROR: Could not capture screenshot. Check Screen Recording permission.")
        sys.exit(1)

    print(f"  Captured screenshot: {frame.shape[1]}x{frame.shape[0]}")
    return frame


def _single_capture(filename: str, description: str) -> None:
    """Capture a single template from a fresh screenshot."""
    print("=" * 60)
    print(f"  Capture: {description}")
    print("=" * 60)
    print()
    print(f"Make sure the '{description}' is visible on screen.")
    input("Press Enter when ready...")
    frame = _capture_frame()

    tasks = [(filename, description, frame)]
    app = CaptureApp(tasks)
    app.run()

    print(f"\n{'=' * 60}")
    print(f"  Done! Captured {app.saved_count}/1 templates.")
    print(f"  Templates saved in: {TEMPLATES_DIR}")
    print(f"{'=' * 60}")


def main():
    gardening_mode = "--gardening" in sys.argv or "-g" in sys.argv
    golf_mode = "--golf" in sys.argv
    single_template = None
    for arg in sys.argv[1:]:
        if arg.startswith("--only="):
            single_template = arg.split("=", 1)[1]

    if single_template:
        all_templates = (
            FISHING_TEMPLATES
            + GARDEN_STEP1_EMPTY_BED
            + GARDEN_STEP2_BEAN_PICKER
            + GARDEN_STEP3_POST_PLANT
            + GARDEN_STEP4_PLANTED_BED
            + GOLF_STEP1_PENCIL
            + GOLF_STEP2_SCOREBOARD
            + GOLF_STEP3_TURN_TIMER
        )
        match = next(((f, d) for f, d in all_templates if f == single_template), None)
        if match is None:
            print(f"ERROR: Unknown template '{single_template}'")
            print("Available templates:")
            for f, d in all_templates:
                print(f"  {f}  — {d}")
            sys.exit(1)
        _single_capture(match[0], match[1])
        return

    if gardening_mode and golf_mode:
        print("ERROR: Use only one of --gardening or --golf")
        sys.exit(1)

    if gardening_mode:
        mode_name = "Gardening"
    elif golf_mode:
        mode_name = "Golf"
    else:
        mode_name = "Fishing"

    print("=" * 60)
    print(f"  TTR Bot — {mode_name} Template Capture Tool")
    print("=" * 60)
    print()

    if golf_mode:
        tasks: list[tuple[str, str, np.ndarray]] = []

        print("STEP 1: On a GOLF COURSE. The pencil / scoreboard icon must be visible.")
        print("         (Do not open the scoreboard yet.)")
        input("Press Enter when ready...")
        frame_g1 = _capture_frame()
        for filename, desc in GOLF_STEP1_PENCIL:
            tasks.append((filename, desc, frame_g1))

        print()
        print("STEP 2: In-game, OPEN the scoreboard (click the pencil).")
        print("         The cream/yellow scoreboard with the RED X close must show.")
        input("Press Enter when the scoreboard is open...")
        frame_g2 = _capture_frame()
        for filename, desc in GOLF_STEP2_SCOREBOARD:
            tasks.append((filename, desc, frame_g2))

        print()
        print("STEP 3: Close the scoreboard. Wait until it is YOUR TURN to swing.")
        print("         The ORANGE countdown clock should appear top-right.")
        input("Press Enter when the turn timer is visible...")
        frame_g3 = _capture_frame()
        for filename, desc in GOLF_STEP3_TURN_TIMER:
            tasks.append((filename, desc, frame_g3))

        print(f"\nOpening selector — {len(tasks)} templates to capture.\n")

        app = CaptureApp(tasks)
        app.run()

        print(f"\n{'=' * 60}")
        print(f"  Done! Captured {app.saved_count}/{len(tasks)} templates.")
        print(f"  Templates saved in: {TEMPLATES_DIR}")
        print(f"{'=' * 60}")
        return

    if gardening_mode:
        tasks: list[tuple[str, str, np.ndarray]] = []

        print("STEP 1: Click on an EMPTY flower bed in-game.")
        print("        The 'Plant Flower' button should appear.")
        input("Press Enter when ready...")
        frame1 = _capture_frame()
        for filename, desc in GARDEN_STEP1_EMPTY_BED:
            tasks.append((filename, desc, frame1))

        print()
        print("STEP 2: Now click 'Plant Flower' in-game to open the")
        print("        jellybean picker. All 9 bean color buttons and")
        print("        the blue Plant button should be visible.")
        input("Press Enter when ready...")
        frame2 = _capture_frame()
        for filename, desc in GARDEN_STEP2_BEAN_PICKER:
            tasks.append((filename, desc, frame2))

        print()
        print("STEP 3: Now actually plant a flower (pick beans + click Plant).")
        print("        An OK/confirmation dialog should appear on screen.")
        input("Press Enter when the OK dialog is visible...")
        frame3 = _capture_frame()
        for filename, desc in GARDEN_STEP3_POST_PLANT:
            tasks.append((filename, desc, frame3))

        print()
        print("STEP 4: Dismiss the OK dialog. Click on a flower bed that")
        print("        HAS a plant in it. The Watering Can button should appear.")
        input("Press Enter when ready...")
        frame4 = _capture_frame()
        for filename, desc in GARDEN_STEP4_PLANTED_BED:
            tasks.append((filename, desc, frame4))

    else:
        print("Make sure you're at a FISHING DOCK in TTR.")
        print("(The red cast button should be visible on screen.)")
        input("Press Enter when ready...")
        frame = _capture_frame()
        tasks = [(f, d, frame) for f, d in FISHING_TEMPLATES]

    print(f"\nOpening selector — {len(tasks)} templates to capture.\n")

    app = CaptureApp(tasks)
    app.run()

    print(f"\n{'=' * 60}")
    print(f"  Done! Captured {app.saved_count}/{len(tasks)} templates.")
    print(f"  Templates saved in: {TEMPLATES_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
