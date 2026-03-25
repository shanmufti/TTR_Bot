"""Golfing tab — custom JSON replay + auto round (ported from Toontown-Rewritten-Bot)."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from ttr_bot.config import settings
from ttr_bot.golf.action_player import load_actions, shot_summary
from ttr_bot.golf.detector import list_action_stems, path_for_stem
from ttr_bot.golf.golf_bot import GolfBot
from ttr_bot.utils.logger import log

BG = "#0f3460"
FG = "#eaeaea"
ACCENT = "#e94560"
ENTRY_BG = "#16213e"
_STOP = "■ Stop"


class GolfingTab:
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

        self._bot = GolfBot()
        self._build_ui()
        self._wire_callbacks()

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        info = tk.Label(
            self._parent,
            text="Uses the same JSON format as Toontown-Rewritten-Bot (Custom Golf Actions).\n"
                 "Place files in golf_actions/ — copy from your other bot's Services/CustomGolfActions.",
            font=("Helvetica", 9),
            fg="#a0a0a0",
            bg=BG,
            justify="left",
        )
        info.pack(anchor="w", padx=8, pady=(6, 2))

        custom = tk.LabelFrame(
            self._parent,
            text="Custom action file",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        custom.pack(fill="x", **pad)

        row = tk.Frame(custom, bg=BG)
        row.pack(fill="x", padx=8, pady=4)

        tk.Label(row, text="Course JSON:", fg=FG, bg=BG).pack(side="left")
        self._stem_var = tk.StringVar(value="")
        self._combo = ttk.Combobox(
            row,
            textvariable=self._stem_var,
            values=[],
            width=36,
            state="readonly",
        )
        self._combo.pack(side="left", padx=6)
        tk.Button(
            row,
            text="↻",
            width=2,
            highlightbackground=ENTRY_BG,
            command=self._refresh_stems,
        ).pack(side="left")

        self._summary = tk.Text(
            custom,
            height=8,
            width=60,
            font=("Menlo", 9),
            bg=ENTRY_BG,
            fg=FG,
            wrap="word",
            state="disabled",
        )
        self._summary.pack(fill="x", padx=8, pady=(0, 6))

        btn_row = tk.Frame(custom, bg=BG)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))

        self._run_custom_btn = tk.Button(
            btn_row,
            text="▶ Run selected actions",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#1a8f3c",
            command=self._on_run_custom,
        )
        self._run_custom_btn.pack(side="left", padx=(0, 8))

        auto = tk.LabelFrame(
            self._parent,
            text="Auto round",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        auto.pack(fill="x", **pad)

        ar = tk.Frame(auto, bg=BG)
        ar.pack(fill="x", padx=8, pady=6)

        tk.Label(ar, text="Holes:", fg=FG, bg=BG).pack(side="left")
        self._holes_var = tk.IntVar(value=3)
        tk.Spinbox(
            ar,
            from_=1,
            to=9,
            textvariable=self._holes_var,
            width=4,
            bg=ENTRY_BG,
            fg=FG,
        ).pack(side="left", padx=6)

        tk.Label(
            ar,
            text="(detects course via scoreboard + OCR; needs pencil/close templates)",
            font=("Helvetica", 9),
            fg="#a0a0a0",
            bg=BG,
        ).pack(side="left", padx=8)

        self._auto_btn = tk.Button(
            auto,
            text="▶ Auto round",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#533483",
            command=self._on_auto_round,
        )
        self._auto_btn.pack(anchor="w", padx=8, pady=(0, 8))

        stop_row = tk.Frame(self._parent, bg=BG)
        stop_row.pack(fill="x", padx=8, pady=6)

        self._stop_btn = tk.Button(
            stop_row,
            text=_STOP,
            font=("Helvetica", 12, "bold"),
            highlightbackground=ACCENT,
            width=10,
            command=self._on_stop,
            state="disabled",
        )
        self._stop_btn.pack(side="left")

        self._refresh_stems()
        self._combo.bind("<<ComboboxSelected>>", lambda _: self._update_summary())
        if self._stem_var.get():
            self._update_summary()

    def _wire_callbacks(self) -> None:
        self._bot.on_status_update = self._on_status_thread
        self._bot.on_golf_ended = self._on_ended_thread

    def _on_status_thread(self, msg: str) -> None:
        self._root.after(0, lambda: self._status_var.set(msg))

    def _on_ended_thread(self, reason: str) -> None:
        self._root.after(0, lambda: self._ended_ui(reason))

    def _ended_ui(self, reason: str) -> None:
        self._stop_btn.config(state="disabled")
        self._run_custom_btn.config(state="normal")
        self._auto_btn.config(state="normal")
        self._status_var.set(f"Golf: {reason}")

    def _refresh_stems(self) -> None:
        stems = list_action_stems()
        self._combo["values"] = stems
        if stems and not self._stem_var.get():
            self._stem_var.set(stems[0])
        self._update_summary()

    def _update_summary(self) -> None:
        stem = self._stem_var.get().strip()
        self._summary.config(state="normal")
        self._summary.delete("1.0", tk.END)
        if not stem:
            self._summary.insert(tk.END, "Select or add JSON files under golf_actions/")
            self._summary.config(state="disabled")
            return
        path = path_for_stem(stem)
        if not os.path.isfile(path):
            self._summary.insert(tk.END, f"Missing: {path}")
            self._summary.config(state="disabled")
            return
        try:
            actions = load_actions(path)
            s = shot_summary(actions)
            self._summary.insert(tk.END, s.describe())
        except Exception as exc:
            self._summary.insert(tk.END, f"Error: {exc}")
        self._summary.config(state="disabled")

    def _ensure_calibrated(self) -> bool:
        from ttr_bot.vision import template_matcher as tm

        self._calibrate_fn()
        # Must read via module — `from tm import _global_scale` would be a stale snapshot.
        if tm._global_scale is None:
            log.warning("Golf: calibration failed")
            self._status_var.set("Calibration failed — show game UI first")
            return False
        return True

    def _on_run_custom(self) -> None:
        stem = self._stem_var.get().strip()
        if not stem:
            self._status_var.set("Select a golf action file")
            return
        path = path_for_stem(stem)
        if not os.path.isfile(path):
            self._status_var.set(f"Missing file: {path}")
            return
        if not self._ensure_calibrated():
            return

        self._run_custom_btn.config(state="disabled")
        self._auto_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._bot.start_custom_file(path)

    def _on_auto_round(self) -> None:
        if not self._ensure_calibrated():
            return
        self._run_custom_btn.config(state="disabled")
        self._auto_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._bot.on_need_manual_course = self._pick_course_blocking
        self._bot.start_auto_round(holes=self._holes_var.get())

    def _pick_course_blocking(self, options: list[str]) -> str | None:
        """Called from golf worker thread — blocks until user picks or cancels."""
        result: list[str | None] = [None]
        ready = threading.Event()

        def show_dialog() -> None:
            top = tk.Toplevel(self._root)
            top.title("Select golf course")
            top.configure(bg=BG)
            top.transient(self._root)
            top.grab_set()

            tk.Label(
                top,
                text="Could not read course from screen.\nPick the JSON to use for this hole:",
                fg=FG,
                bg=BG,
                justify="left",
            ).pack(padx=12, pady=8)

            var = tk.StringVar(value=options[0] if options else "")
            combo = ttk.Combobox(top, textvariable=var, values=options, width=40, state="readonly")
            combo.pack(padx=12, pady=4)

            def ok() -> None:
                result[0] = var.get().strip() or None
                ready.set()
                top.destroy()

            def cancel() -> None:
                result[0] = None
                ready.set()
                top.destroy()

            bf = tk.Frame(top, bg=BG)
            bf.pack(pady=8)
            tk.Button(bf, text="Use this course", command=ok, highlightbackground="#1a8f3c").pack(
                side="left", padx=4
            )
            tk.Button(bf, text="Skip", command=cancel, highlightbackground=ACCENT).pack(side="left", padx=4)

        self._root.after(0, show_dialog)
        ready.wait(timeout=300.0)
        return result[0]

    def _on_stop(self) -> None:
        self._bot.stop()

    @property
    def running(self) -> bool:
        return self._bot.running

    def shutdown(self) -> None:
        if self._bot.running:
            self._bot.stop()
