"""Tkinter GUI for the TTR Bot (Fishing, Gardening, Golf)."""

import contextlib
import logging
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import (
    find_ttr_window,
    is_window_available,
    set_calibrated_bounds,
)
from ttr_bot.ui.theme import ACCENT, BG, ENTRY_BG, FG
from ttr_bot.utils.logger import log


class _TkLogHandler(logging.Handler):
    """Streams log records into a tkinter ScrolledText widget."""

    def __init__(self, text_widget: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self._text = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        with contextlib.suppress(Exception):
            self._text.after(0, self._append, msg)

    def _append(self, msg: str) -> None:
        try:
            self._text.configure(state="normal")
            self._text.insert(tk.END, msg)
            self._text.see(tk.END)
            self._text.configure(state="disabled")
        except tk.TclError:
            pass


class App:
    """Main application window with tabbed Fishing / Gardening / Golf UI."""

    def __init__(self) -> None:
        self._root = tk.Tk()
        self._root.title("TTR Bot")
        screen_w = self._root.winfo_screenwidth()
        self._root.geometry(f"520x650+{screen_w - 540}+30")
        self._root.resizable(False, False)
        self._root.configure(bg=BG)

        self._build_ui()
        self._attach_logger()
        self._poll_window_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root

        # ---- Header ----
        tk.Label(
            root,
            text="TTR Bot",
            font=("Helvetica", 18, "bold"),
            fg=ACCENT,
            bg=BG,
        ).pack(pady=(14, 2))

        self._status_var = tk.StringVar(value="Checking for TTR window…")
        tk.Label(
            root,
            textvariable=self._status_var,
            font=("Helvetica", 10),
            fg="#a0a0a0",
            bg=BG,
        ).pack()

        # ---- Calibrate button ----
        cal_frame = tk.Frame(root, bg=BG)
        cal_frame.pack(fill="x", padx=12, pady=(6, 2))

        self._calibrate_btn = tk.Button(
            cal_frame,
            text="Calibrate Window",
            font=("Helvetica", 11),
            highlightbackground="#2980b9",
            width=16,
            command=self._on_calibrate,
        )
        self._calibrate_btn.pack(side="left")

        # ---- Notebook (tabs) ----
        style = ttk.Style()
        style.configure("Bot.TNotebook", background=BG)
        style.configure("Bot.TNotebook.Tab", font=("Helvetica", 11, "bold"))

        notebook = ttk.Notebook(root, style="Bot.TNotebook")
        notebook.pack(fill="both", expand=True, padx=12, pady=(6, 0))

        # Fishing tab
        from ttr_bot.ui.fishing_tab import FishingTab

        fish_frame = tk.Frame(notebook, bg=BG)
        notebook.add(fish_frame, text="  Fishing  ")
        self._fishing_tab = FishingTab(
            fish_frame, self._root, self._status_var, self._on_calibrate
        )

        # Gardening tab
        from ttr_bot.ui.gardening_tab import GardeningTab

        garden_frame = tk.Frame(notebook, bg=BG)
        notebook.add(garden_frame, text="  Gardening  ")
        self._garden_tab = GardeningTab(
            garden_frame, self._root, self._status_var, self._on_calibrate
        )

        # Golf tab
        from ttr_bot.ui.golfing_tab import GolfingTab

        golf_frame = tk.Frame(notebook, bg=BG)
        notebook.add(golf_frame, text="  Golf  ")
        self._golf_tab = GolfingTab(golf_frame, self._root, self._status_var, self._on_calibrate)

        # ---- Log output ----
        tk.Label(
            root,
            text="Log",
            font=("Helvetica", 10, "bold"),
            fg=FG,
            bg=BG,
            anchor="w",
        ).pack(fill="x", padx=12)

        self._log_text = scrolledtext.ScrolledText(
            root,
            height=8,
            font=("Menlo", 9),
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=FG,
            state="disabled",
            wrap="word",
        )
        self._log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ------------------------------------------------------------------
    # Calibration (shared across tabs)
    # ------------------------------------------------------------------

    def _on_calibrate(self) -> None:
        win = find_ttr_window()
        if win is None:
            self._status_var.set("Calibration failed — TTR not found")
            return

        set_calibrated_bounds(
            win.x, win.y, win.width, win.height, window_id=win.window_id, pid=win.pid
        )
        log.info("Window locked: %dx%d at (%d,%d)", win.width, win.height, win.x, win.y)

        frame = capture_window(win)
        if frame is None:
            self._status_var.set("Calibration failed — capture error")
            return

        self._calibrate_btn.config(state="disabled")
        self._status_var.set("Calibrating…")

        def _run_calibration() -> None:
            from ttr_bot.vision.template_matcher import calibrate_scale, clear_cache

            clear_cache()
            scale = calibrate_scale(frame)
            self._root.after(0, self._calibration_done, scale, win.width, win.height)

        threading.Thread(target=_run_calibration, daemon=True).start()

    def _calibration_done(self, scale: float, w: int, h: int) -> None:
        self._calibrate_btn.config(state="normal")
        if scale < 0:
            self._status_var.set("Calibration failed — no known button visible")
        else:
            self._status_var.set(f"Calibrated: {w}×{h} scale={scale:.1f}")

    # ------------------------------------------------------------------
    # Logger
    # ------------------------------------------------------------------

    def _attach_logger(self) -> None:
        handler = _TkLogHandler(self._log_text)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        log.addHandler(handler)

    # ------------------------------------------------------------------
    # Periodic checks
    # ------------------------------------------------------------------

    def _poll_window_status(self) -> None:
        available = is_window_available()
        any_running = (
            self._fishing_tab.running or self._garden_tab.running or self._golf_tab.running
        )
        if not any_running:
            self._status_var.set("TTR window detected" if available else "TTR window not found")
        can_start = available and not any_running
        self._fishing_tab.set_start_enabled(can_start)
        self._root.after(2000, self._poll_window_status)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self) -> None:
        self._fishing_tab.shutdown()
        self._garden_tab.shutdown()
        self._golf_tab.shutdown()
        self._root.destroy()
