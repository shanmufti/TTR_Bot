"""Gardening tab UI for the TTR Bot."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Callable

import cv2
from PIL import Image, ImageTk

from ttr_bot.config import settings
from ttr_bot.gardening.flowers import BEAN_COLORS, get_flowers_by_beans, lookup_flower
from ttr_bot.gardening.gardening_bot import GardenBot, GardeningStats
from ttr_bot.gardening.demo_recorder import DemoRecorder
from ttr_bot.gardening.demo_processor import DemoProcessor
from ttr_bot.gardening.routine_runner import RoutineRunner, RoutineProgress, list_routines
from ttr_bot.utils.logger import log

BG = "#0f3460"
FG = "#eaeaea"
ACCENT = "#e94560"
ENTRY_BG = "#16213e"
_STOP_LABEL = "■ Stop"
_MSG_SELECT_FLOWER = "Select a flower first"
_MSG_CALIBRATION_FAILED = "Calibration failed — stand at garden first"


class GardeningTab:
    """Builds and manages the Gardening tab inside a parent frame."""

    def __init__(
        self,
        parent: tk.Frame,
        root: tk.Tk,
        status_var: tk.StringVar,
        calibrate_fn: Callable[[], None],
    ) -> None:
        self._parent = parent
        self._root = root
        self._status_var = status_var
        self._calibrate_fn = calibrate_fn

        self._bot = GardenBot()
        self._routine_runner = RoutineRunner(self._bot)
        self._demo_recorder = DemoRecorder()

        self._build_ui()
        self._wire_callbacks()
        self._on_bean_count_changed()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        parent = self._parent
        pad = {"padx": 8, "pady": 4}

        # ---- Plant section ----
        plant_frame = tk.LabelFrame(
            parent,
            text="Plant Flower",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        plant_frame.pack(fill="x", **pad)

        row = 0

        # Bean count
        tk.Label(plant_frame, text="Bean count:", fg=FG, bg=BG).grid(
            row=row,
            column=0,
            sticky="w",
            padx=8,
            pady=3,
        )
        self._bean_count_var = tk.IntVar(value=3)
        bean_spin = tk.Spinbox(
            plant_frame,
            from_=1,
            to=8,
            textvariable=self._bean_count_var,
            width=4,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=FG,
            command=self._on_bean_count_changed,
        )
        bean_spin.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        bean_spin.bind("<Return>", lambda _: self._on_bean_count_changed())
        row += 1

        # Flower selector
        tk.Label(plant_frame, text="Flower:", fg=FG, bg=BG).grid(
            row=row,
            column=0,
            sticky="w",
            padx=8,
            pady=3,
        )
        self._flower_var = tk.StringVar()
        self._flower_combo = ttk.Combobox(
            plant_frame,
            textvariable=self._flower_var,
            state="readonly",
            width=24,
        )
        self._flower_combo.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        self._flower_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._on_flower_changed()
        )
        row += 1

        # Bean sequence preview
        tk.Label(plant_frame, text="Recipe:", fg=FG, bg=BG).grid(
            row=row,
            column=0,
            sticky="w",
            padx=8,
            pady=3,
        )
        self._recipe_canvas = tk.Canvas(
            plant_frame,
            height=24,
            bg=BG,
            highlightthickness=0,
        )
        self._recipe_canvas.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Plant button
        plant_btn_frame = tk.Frame(plant_frame, bg=BG)
        plant_btn_frame.grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=6
        )

        self._plant_btn = tk.Button(
            plant_btn_frame,
            text="▶ Plant",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#1a8f3c",
            width=12,
            command=self._on_plant,
        )
        self._plant_btn.pack(side="left", padx=(0, 8))

        self._plant_stop_btn = tk.Button(
            plant_btn_frame,
            text=_STOP_LABEL,
            font=("Helvetica", 12, "bold"),
            highlightbackground=ACCENT,
            width=8,
            command=self._on_stop,
            state="disabled",
        )
        self._plant_stop_btn.pack(side="left")

        # ---- Demo Recording section ----
        demo_frame = tk.LabelFrame(
            parent,
            text="Smart Navigation — Demo Recording",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        demo_frame.pack(fill="x", **pad)

        demo_info = tk.Label(
            demo_frame,
            text="Record yourself doing a garden cycle.\n"
                 "The bot learns where beds are + how to navigate.",
            font=("Helvetica", 9),
            fg="#a0a0a0",
            bg=BG,
            justify="left",
        )
        demo_info.pack(padx=8, pady=(4, 2), anchor="w")

        demo_btns = tk.Frame(demo_frame, bg=BG)
        demo_btns.pack(fill="x", padx=8, pady=(2, 4))

        self._record_btn = tk.Button(
            demo_btns,
            text="● Record Demo",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#c0392b",
            width=14,
            command=self._on_record_demo,
        )
        self._record_btn.pack(side="left", padx=(0, 8))

        self._stop_record_btn = tk.Button(
            demo_btns,
            text="■ Stop Recording",
            font=("Helvetica", 12, "bold"),
            highlightbackground=ACCENT,
            width=14,
            command=self._on_stop_recording,
            state="disabled",
        )
        self._stop_record_btn.pack(side="left", padx=(0, 8))

        self._process_btn = tk.Button(
            demo_btns,
            text="⚙ Process Demo",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#2980b9",
            width=14,
            command=self._on_process_demo,
        )
        self._process_btn.pack(side="left")

        self._demo_status_var = tk.StringVar(value="")
        tk.Label(
            demo_frame,
            textvariable=self._demo_status_var,
            font=("Helvetica", 9),
            fg="#a0a0a0",
            bg=BG,
            wraplength=500,
            justify="left",
        ).pack(padx=8, pady=(0, 6), anchor="w")

        # ---- Routine section ----
        routine_frame = tk.LabelFrame(
            parent,
            text="Gardening Routine",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        routine_frame.pack(fill="x", **pad)

        routine_sel = tk.Frame(routine_frame, bg=BG)
        routine_sel.pack(fill="x", padx=8, pady=(6, 2))

        tk.Label(routine_sel, text="Routine:", fg=FG, bg=BG).pack(side="left")

        routines = list_routines()
        routine_names = [r["name"] for r in routines]
        self._routine_var = tk.StringVar(
            value=routine_names[0] if routine_names else ""
        )
        self._routine_combo = ttk.Combobox(
            routine_sel,
            textvariable=self._routine_var,
            values=routine_names,
            state="readonly",
            width=20,
        )
        self._routine_combo.pack(side="left", padx=(4, 4))

        tk.Button(
            routine_sel,
            text="↻",
            font=("Helvetica", 9),
            highlightbackground=ENTRY_BG,
            width=2,
            command=self._refresh_routines,
        ).pack(side="left")

        routine_btns = tk.Frame(routine_frame, bg=BG)
        routine_btns.pack(fill="x", padx=8, pady=(2, 6))

        self._routine_start_btn = tk.Button(
            routine_btns,
            text="▶ Run Routine",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#1a8f3c",
            width=14,
            command=self._on_run_routine,
        )
        self._routine_start_btn.pack(side="left", padx=(0, 8))

        self._smart_routine_btn = tk.Button(
            routine_btns,
            text="▶ Run Smart",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#27ae60",
            width=12,
            command=self._on_run_smart_routine,
        )
        self._smart_routine_btn.pack(side="left", padx=(0, 8))

        self._routine_stop_btn = tk.Button(
            routine_btns,
            text="■ Stop",
            font=("Helvetica", 12, "bold"),
            highlightbackground=ACCENT,
            width=8,
            command=self._on_stop_routine,
            state="disabled",
        )
        self._routine_stop_btn.pack(side="left", padx=(0, 8))

        self._routine_progress_var = tk.StringVar(value="")
        tk.Label(
            routine_btns,
            textvariable=self._routine_progress_var,
            font=("Helvetica", 10),
            fg="#a0a0a0",
            bg=BG,
        ).pack(side="left")

    # ------------------------------------------------------------------
    # Callbacks wiring
    # ------------------------------------------------------------------

    def _wire_callbacks(self) -> None:
        self._bot.on_status_update = self._on_bot_status_thread
        self._bot.on_stats_update = self._on_bot_stats_thread
        self._bot.on_gardening_ended = self._on_bot_ended_thread

        self._routine_runner.on_status_update = self._on_bot_status_thread
        self._routine_runner.on_progress = self._on_routine_progress_thread
        self._routine_runner.on_routine_ended = self._on_routine_ended_thread

    # ------------------------------------------------------------------
    # Flower picker logic
    # ------------------------------------------------------------------

    def _on_bean_count_changed(self) -> None:
        try:
            count = self._bean_count_var.get()
        except tk.TclError:
            return
        flowers = get_flowers_by_beans(count)
        names = list(flowers.keys())
        self._flower_combo["values"] = names
        if names:
            self._flower_var.set(names[0])
        else:
            self._flower_var.set("")
        self._on_flower_changed()

    def _on_flower_changed(self) -> None:
        name = self._flower_var.get()
        info = lookup_flower(name)
        self._draw_recipe(info[1] if info else "")

    def _draw_recipe(self, sequence: str) -> None:
        c = self._recipe_canvas
        c.delete("all")
        size = 18
        gap = 4
        total_w = len(sequence) * (size + gap)
        c.config(width=max(total_w, 40))
        for i, ch in enumerate(sequence):
            _, color = BEAN_COLORS.get(ch, ("?", "#888"))
            x = i * (size + gap)
            c.create_oval(x, 2, x + size, 2 + size, fill=color, outline="")

    # ------------------------------------------------------------------
    # Alignment overlay
    # ------------------------------------------------------------------

    def _show_alignment_overlay(self, ref_path: str) -> bool:
        """Show saved start position vs live screenshot. Returns True to proceed."""
        from ttr_bot.core.window_manager import find_ttr_window
        from ttr_bot.core.screen_capture import capture_window

        ref_img = cv2.imread(ref_path)
        if ref_img is None:
            return True

        win = find_ttr_window()
        if win is None:
            self._status_var.set("TTR window not found")
            return False

        live_img = capture_window(win)
        if live_img is None:
            return True

        # Resize both to a reasonable display size
        display_w = 400
        ref_h, ref_w = ref_img.shape[:2]
        scale = display_w / ref_w
        display_h = int(ref_h * scale)

        ref_small = cv2.resize(ref_img, (display_w, display_h))
        live_small = cv2.resize(live_img, (display_w, display_h))

        # Convert BGR → RGB → PIL → Tk
        ref_rgb = cv2.cvtColor(ref_small, cv2.COLOR_BGR2RGB)
        live_rgb = cv2.cvtColor(live_small, cv2.COLOR_BGR2RGB)

        result = [False]

        overlay = tk.Toplevel(self._root)
        overlay.title("Align Starting Position")
        overlay.attributes("-topmost", True)
        overlay.configure(bg="#0f3460")
        overlay.resizable(False, False)

        tk.Label(
            overlay, text="Match your character position to the reference",
            font=("Helvetica", 12, "bold"), fg="#eaeaea", bg="#0f3460",
        ).pack(pady=(10, 6))

        img_frame = tk.Frame(overlay, bg="#0f3460")
        img_frame.pack(padx=10, pady=4)

        # Reference image
        ref_col = tk.Frame(img_frame, bg="#0f3460")
        ref_col.pack(side="left", padx=6)
        tk.Label(ref_col, text="Reference (saved)", fg="#4ecca3", bg="#0f3460",
                 font=("Helvetica", 10, "bold")).pack()
        ref_pil = ImageTk.PhotoImage(Image.fromarray(ref_rgb))
        tk.Label(ref_col, image=ref_pil, bd=2, relief="groove").pack()

        # Live image
        live_col = tk.Frame(img_frame, bg="#0f3460")
        live_col.pack(side="left", padx=6)
        tk.Label(live_col, text="Current (live)", fg="#e94560", bg="#0f3460",
                 font=("Helvetica", 10, "bold")).pack()
        live_label = tk.Label(live_col, bd=2, relief="groove")
        live_label.pack()
        live_pil = ImageTk.PhotoImage(Image.fromarray(live_rgb))
        live_label.config(image=live_pil)

        btn_frame = tk.Frame(overlay, bg="#0f3460")
        btn_frame.pack(pady=10)

        def _refresh():
            nonlocal live_pil
            frame = capture_window(win)
            if frame is not None:
                small = cv2.resize(frame, (display_w, display_h))
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                live_pil = ImageTk.PhotoImage(Image.fromarray(rgb))
                live_label.config(image=live_pil)

        def _go():
            result[0] = True
            overlay.destroy()

        def _cancel():
            overlay.destroy()

        tk.Button(btn_frame, text="↻ Refresh", font=("Helvetica", 12),
                  width=10, command=_refresh).pack(side="left", padx=6)
        tk.Button(btn_frame, text="▶ Start", font=("Helvetica", 12, "bold"),
                  width=10, command=_go).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", font=("Helvetica", 12),
                  width=10, command=_cancel).pack(side="left", padx=6)

        overlay.bind("<Return>", lambda _: _go())
        overlay.grab_set()
        overlay.wait_window()

        return result[0]

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_plant(self) -> None:
        if self._bot.running:
            return
        name = self._flower_var.get()
        info = lookup_flower(name)
        if info is None:
            self._status_var.set(_MSG_SELECT_FLOWER)
            return

        from ttr_bot.vision import template_matcher as tm

        if tm._global_scale is None:
            self._calibrate_fn()

        if tm._global_scale is None:
            self._status_var.set(_MSG_CALIBRATION_FAILED)
            return

        _, beans = info
        self._set_action_buttons_running()
        self._bot.start_plant(name, beans)

    def _on_stop(self) -> None:
        if self._routine_runner.running:
            self._routine_runner.stop()
            self._routine_start_btn.config(state="normal")
            self._smart_routine_btn.config(state="normal")
            self._routine_stop_btn.config(state="disabled")
            self._routine_progress_var.set("")
        self._bot.stop()
        self._set_action_buttons_idle()

    # ------------------------------------------------------------------
    # Demo recording handlers
    # ------------------------------------------------------------------

    def _on_record_demo(self) -> None:
        if self._demo_recorder.recording:
            return

        self._demo_recorder.on_status = lambda msg: self._root.after(
            0, self._demo_status_var.set, msg
        )
        demo_dir = self._demo_recorder.start()
        self._demo_status_var.set(f"Recording to {demo_dir}…")
        self._record_btn.config(state="disabled")
        self._stop_record_btn.config(state="normal")
        self._process_btn.config(state="disabled")

        self._recording_timer_id = self._root.after(1000, self._update_recording_status)

    def _update_recording_status(self) -> None:
        if not self._demo_recorder.recording:
            return
        elapsed = self._demo_recorder.duration
        frames = self._demo_recorder.frame_count
        self._demo_status_var.set(
            f"Recording… {elapsed:.0f}s | {frames} frames captured"
        )
        self._recording_timer_id = self._root.after(1000, self._update_recording_status)

    def _on_stop_recording(self) -> None:
        if not self._demo_recorder.recording:
            return

        if hasattr(self, "_recording_timer_id"):
            self._root.after_cancel(self._recording_timer_id)

        self._demo_status_var.set("Stopping recording…")

        import threading
        def _stop():
            summary = self._demo_recorder.stop()
            if summary:
                frames = summary.get("frame_count", 0)
                dur = summary.get("duration_s", 0)
                msg = f"Recorded {frames} frames in {dur:.0f}s. Click 'Process Demo' to build map."
            else:
                msg = "Recording stopped (no data)"
            self._root.after(0, self._demo_status_var.set, msg)
            self._root.after(0, self._record_btn.config, {"state": "normal"})
            self._root.after(0, self._stop_record_btn.config, {"state": "disabled"})
            self._root.after(0, self._process_btn.config, {"state": "normal"})

        threading.Thread(target=_stop, daemon=True).start()

    def _on_process_demo(self) -> None:
        import glob as glob_mod

        demos_dir = settings.DEMO_SAVE_DIR
        if not os.path.isdir(demos_dir):
            self._demo_status_var.set("No demos found. Record one first.")
            return

        demo_dirs = sorted(glob_mod.glob(os.path.join(demos_dir, "demo_*")))
        if not demo_dirs:
            self._demo_status_var.set("No demos found. Record one first.")
            return

        latest_demo = demo_dirs[-1]
        self._demo_status_var.set(f"Processing {os.path.basename(latest_demo)}…")
        self._process_btn.config(state="disabled")

        import threading
        def _process():
            try:
                processor = DemoProcessor(latest_demo)
                summary = processor.process()
                beds = summary.get("bed_arrivals", 0)
                msg = f"Processed: {beds} beds detected. Map saved. Ready to Run Smart!"
                self._root.after(0, self._demo_status_var.set, msg)
            except Exception as exc:
                self._root.after(0, self._demo_status_var.set, f"Processing failed: {exc}")
            finally:
                self._root.after(0, self._process_btn.config, {"state": "normal"})

        threading.Thread(target=_process, daemon=True).start()

    # ------------------------------------------------------------------
    # Routine handlers
    # ------------------------------------------------------------------

    def _on_run_routine(self) -> None:
        if self._routine_runner.running or self._bot.running:
            return

        name = self._routine_var.get()
        if not name:
            self._status_var.set("Select a routine first")
            return

        routines = list_routines()
        path = None
        for r in routines:
            if r["name"] == name:
                path = r["path"]
                break
        if path is None:
            self._status_var.set(f"Routine not found: {name}")
            return

        from ttr_bot.vision import template_matcher as tm

        if tm._global_scale is None:
            self._calibrate_fn()

        if tm._global_scale is None:
            self._status_var.set(_MSG_CALIBRATION_FAILED)
            return

        flower_name = self._flower_var.get()
        if not flower_name:
            self._status_var.set(_MSG_SELECT_FLOWER)
            return

        ref_path = os.path.join(settings.GARDENING_ROUTINES_DIR, "start_position.png")
        if os.path.isfile(ref_path):
            if not self._show_alignment_overlay(ref_path):
                return

        self._routine_start_btn.config(state="disabled")
        self._routine_stop_btn.config(state="normal")
        self._set_action_buttons_running()
        self._routine_runner.start(path, default_flower=flower_name)

    def _on_run_smart_routine(self) -> None:
        """Run the smart routine using the garden map + navigator."""
        if self._routine_runner.running or self._bot.running:
            return

        map_path = os.path.join(settings.GARDENING_ROUTINES_DIR, "garden_map.json")
        if not os.path.isfile(map_path):
            self._status_var.set("No garden map found — record + process a demo first")
            return

        flower_name = self._flower_var.get()
        if not flower_name:
            self._status_var.set(_MSG_SELECT_FLOWER)
            return

        from ttr_bot.vision import template_matcher as tm
        if tm._global_scale is None:
            self._calibrate_fn()
        if tm._global_scale is None:
            self._status_var.set(_MSG_CALIBRATION_FAILED)
            return

        self._routine_start_btn.config(state="disabled")
        self._smart_routine_btn.config(state="disabled")
        self._routine_stop_btn.config(state="normal")
        self._set_action_buttons_running()
        self._routine_runner.start_smart(map_path, default_flower=flower_name)

    def _on_stop_routine(self) -> None:
        self._routine_runner.stop()
        self._routine_start_btn.config(state="normal")
        self._smart_routine_btn.config(state="normal")
        self._routine_stop_btn.config(state="disabled")
        self._set_action_buttons_idle()

    def _refresh_routines(self) -> None:
        routines = list_routines()
        names = [r["name"] for r in routines]
        self._routine_combo["values"] = names
        if names and not self._routine_var.get():
            self._routine_var.set(names[0])
        log.info("Refreshed gardening routines: %d found", len(names))

    # ------------------------------------------------------------------
    # Button state helpers
    # ------------------------------------------------------------------

    def _set_action_buttons_running(self) -> None:
        self._plant_btn.config(state="disabled")
        self._plant_stop_btn.config(state="normal")

    def _set_action_buttons_idle(self) -> None:
        self._plant_btn.config(state="normal")
        self._plant_stop_btn.config(state="disabled")

    # ------------------------------------------------------------------
    # Thread-safe callbacks
    # ------------------------------------------------------------------

    def _on_bot_status_thread(self, msg: str) -> None:
        self._root.after(0, self._status_var.set, msg)

    def _on_bot_stats_thread(self, stats: GardeningStats) -> None:
        # Stats display not yet implemented; overlay could be added later.
        pass

    def _on_bot_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_bot_ended_ui, reason)

    def _on_bot_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Gardening: {reason}")
        self._set_action_buttons_idle()

    def _on_routine_progress_thread(self, progress: RoutineProgress) -> None:
        self._root.after(0, self._on_routine_progress_ui, progress)

    def _on_routine_progress_ui(self, progress: RoutineProgress) -> None:
        self._routine_progress_var.set(
            f"Bed {progress.current_bed}/{progress.total_beds} — planted {progress.flowers_planted}"
        )

    def _on_routine_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_routine_ended_ui, reason)

    def _on_routine_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Routine: {reason}")
        self._routine_start_btn.config(state="normal")
        self._smart_routine_btn.config(state="normal")
        self._routine_stop_btn.config(state="disabled")
        self._routine_progress_var.set("")
        self._set_action_buttons_idle()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._demo_recorder.recording:
            self._demo_recorder.stop()
        if self._bot.running:
            self._bot.stop()
        if self._routine_runner.running:
            self._routine_runner.stop()
