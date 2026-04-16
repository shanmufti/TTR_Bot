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

        # ---- Watch section ----
        watch_frame = tk.LabelFrame(
            parent,
            text="Garden Watch",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        watch_frame.pack(fill="x", **pad)

        # Flower selection row
        flower_row = tk.Frame(watch_frame, bg=BG)
        flower_row.pack(fill="x", padx=8, pady=(4, 2))

        tk.Label(flower_row, text="Bean count:", fg=FG, bg=BG).pack(
            side="left", padx=(0, 4),
        )
        self._bean_count_var = tk.IntVar(value=3)
        bean_spin = tk.Spinbox(
            flower_row,
            from_=1, to=8,
            textvariable=self._bean_count_var,
            width=4, bg=ENTRY_BG, fg=FG, insertbackground=FG,
            command=self._on_bean_count_changed,
        )
        bean_spin.pack(side="left", padx=(0, 12))
        bean_spin.bind("<Return>", lambda _: self._on_bean_count_changed())

        tk.Label(flower_row, text="Flower:", fg=FG, bg=BG).pack(
            side="left", padx=(0, 4),
        )
        self._flower_var = tk.StringVar()
        self._flower_combo = ttk.Combobox(
            flower_row,
            textvariable=self._flower_var,
            state="readonly",
            width=20,
        )
        self._flower_combo.pack(side="left")
        self._flower_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._on_flower_changed()
        )

        # Recipe display
        recipe_row = tk.Frame(watch_frame, bg=BG)
        recipe_row.pack(fill="x", padx=8, pady=(0, 2))
        tk.Label(recipe_row, text="Recipe:", fg=FG, bg=BG).pack(
            side="left", padx=(0, 4),
        )
        self._recipe_canvas = tk.Canvas(
            recipe_row, height=24, bg=BG, highlightthickness=0,
        )
        self._recipe_canvas.pack(side="left")

        watch_info = tk.Label(
            watch_frame,
            text="You walk — I garden. Move to each bed and\n"
                 "I'll auto pick / plant / water.",
            font=("Helvetica", 9),
            fg="#a0a0a0",
            bg=BG,
            justify="left",
        )
        watch_info.pack(padx=8, pady=(4, 2), anchor="w")

        watch_btns = tk.Frame(watch_frame, bg=BG)
        watch_btns.pack(fill="x", padx=8, pady=(2, 6))

        self._watch_btn = tk.Button(
            watch_btns,
            text="▶ Watch",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#8e44ad",
            width=12,
            command=self._on_watch,
        )
        self._watch_btn.pack(side="left", padx=(0, 8))

        self._watch_stop_btn = tk.Button(
            watch_btns,
            text=_STOP_LABEL,
            font=("Helvetica", 12, "bold"),
            highlightbackground=ACCENT,
            width=8,
            command=self._on_stop_watch,
            state="disabled",
        )
        self._watch_stop_btn.pack(side="left", padx=(0, 8))

        self._watch_progress_var = tk.StringVar(value="")
        tk.Label(
            watch_btns,
            textvariable=self._watch_progress_var,
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

    def _on_watch(self) -> None:
        if self._routine_runner.running or self._bot.running:
            return

        flower_name = self._flower_var.get()
        if not flower_name:
            self._status_var.set(_MSG_SELECT_FLOWER)
            return

        self._watch_btn.config(state="disabled")
        self._watch_stop_btn.config(state="normal")
        self._status_var.set("Starting watcher — calibrating…")
        self._routine_runner.start_watch(default_flower=flower_name)

    def _on_stop_watch(self) -> None:
        self._routine_runner.stop()
        self._watch_btn.config(state="normal")
        self._watch_stop_btn.config(state="disabled")
        self._watch_progress_var.set("")

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

    def _on_routine_progress_thread(self, progress: RoutineProgress) -> None:
        self._root.after(0, self._on_routine_progress_ui, progress)

    def _on_routine_progress_ui(self, progress: RoutineProgress) -> None:
        self._watch_progress_var.set(
            f"Beds: {progress.current_bed} — planted {progress.flowers_planted}"
        )

    def _on_routine_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_routine_ended_ui, reason)

    def _on_routine_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Watch: {reason}")
        self._watch_btn.config(state="normal")
        self._watch_stop_btn.config(state="disabled")
        self._watch_progress_var.set("")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._bot.running:
            self._bot.stop()
        if self._routine_runner.running:
            self._routine_runner.stop()
