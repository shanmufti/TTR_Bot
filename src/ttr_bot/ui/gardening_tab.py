"""Gardening tab UI for the TTR Bot."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ttr_bot.gardening.flowers import BEAN_COLORS, get_flowers_by_beans, lookup_flower
from ttr_bot.gardening.gardening_bot import GardenBot, GardeningStats
from ttr_bot.gardening.routine_runner import RoutineRunner, RoutineProgress

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

        tk.Label(plant_frame, text="Bean count:", fg=FG, bg=BG).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._bean_count_var = tk.IntVar(value=3)
        bean_spin = tk.Spinbox(
            plant_frame,
            from_=1, to=8,
            textvariable=self._bean_count_var,
            width=4, bg=ENTRY_BG, fg=FG, insertbackground=FG,
            command=self._on_bean_count_changed,
        )
        bean_spin.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        bean_spin.bind("<Return>", lambda _: self._on_bean_count_changed())
        row += 1

        tk.Label(plant_frame, text="Flower:", fg=FG, bg=BG).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
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

        tk.Label(plant_frame, text="Recipe:", fg=FG, bg=BG).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._recipe_canvas = tk.Canvas(
            plant_frame, height=24, bg=BG, highlightthickness=0,
        )
        self._recipe_canvas.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        plant_btn_frame = tk.Frame(plant_frame, bg=BG)
        plant_btn_frame.grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=6,
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

        # ---- Sweep section ----
        sweep_frame = tk.LabelFrame(
            parent,
            text="Garden Sweep",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        sweep_frame.pack(fill="x", **pad)

        sweep_info = tk.Label(
            sweep_frame,
            text="Visually scan for flowers, walk to each bed,\n"
                 "and pick / plant / water automatically.",
            font=("Helvetica", 9),
            fg="#a0a0a0",
            bg=BG,
            justify="left",
        )
        sweep_info.pack(padx=8, pady=(4, 2), anchor="w")

        sweep_btns = tk.Frame(sweep_frame, bg=BG)
        sweep_btns.pack(fill="x", padx=8, pady=(2, 6))

        self._sweep_btn = tk.Button(
            sweep_btns,
            text="▶ Sweep",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#8e44ad",
            width=12,
            command=self._on_sweep,
        )
        self._sweep_btn.pack(side="left", padx=(0, 8))

        self._sweep_stop_btn = tk.Button(
            sweep_btns,
            text=_STOP_LABEL,
            font=("Helvetica", 12, "bold"),
            highlightbackground=ACCENT,
            width=8,
            command=self._on_stop_sweep,
            state="disabled",
        )
        self._sweep_stop_btn.pack(side="left", padx=(0, 8))

        self._sweep_progress_var = tk.StringVar(value="")
        tk.Label(
            sweep_btns,
            textvariable=self._sweep_progress_var,
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
            self._sweep_btn.config(state="normal")
            self._sweep_stop_btn.config(state="disabled")
            self._sweep_progress_var.set("")
        self._bot.stop()
        self._set_action_buttons_idle()

    def _on_sweep(self) -> None:
        if self._routine_runner.running or self._bot.running:
            return

        flower_name = self._flower_var.get()
        if not flower_name:
            self._status_var.set(_MSG_SELECT_FLOWER)
            return

        from ttr_bot.vision import template_matcher as tm_mod

        if tm_mod._global_scale is None:
            self._calibrate_fn()
        if tm_mod._global_scale is None:
            self._status_var.set(_MSG_CALIBRATION_FAILED)
            return

        self._sweep_btn.config(state="disabled")
        self._sweep_stop_btn.config(state="normal")
        self._set_action_buttons_running()
        self._routine_runner.start_sweep(default_flower=flower_name)

    def _on_stop_sweep(self) -> None:
        self._routine_runner.stop()
        self._sweep_btn.config(state="normal")
        self._sweep_stop_btn.config(state="disabled")
        self._sweep_progress_var.set("")
        self._set_action_buttons_idle()

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

    def _on_bot_stats_thread(self, _stats: GardeningStats) -> None:
        # No stats overlay in the UI yet; callback required by GardenBot interface.
        pass

    def _on_bot_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_bot_ended_ui, reason)

    def _on_bot_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Gardening: {reason}")
        self._set_action_buttons_idle()

    def _on_routine_progress_thread(self, progress: RoutineProgress) -> None:
        self._root.after(0, self._on_routine_progress_ui, progress)

    def _on_routine_progress_ui(self, progress: RoutineProgress) -> None:
        self._sweep_progress_var.set(
            f"Bed {progress.current_bed}/{progress.total_beds} — "
            f"planted {progress.flowers_planted}"
        )

    def _on_routine_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_routine_ended_ui, reason)

    def _on_routine_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Sweep: {reason}")
        self._sweep_btn.config(state="normal")
        self._sweep_stop_btn.config(state="disabled")
        self._sweep_progress_var.set("")
        self._set_action_buttons_idle()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._bot.running:
            self._bot.stop()
        if self._routine_runner.running:
            self._routine_runner.stop()
