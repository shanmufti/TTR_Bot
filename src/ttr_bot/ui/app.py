"""Tkinter GUI for the TTR Bot (Fishing, Gardening, Golf)."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import scrolledtext, ttk

from ttr_bot.config import settings
from ttr_bot.core.window_manager import is_window_available
from ttr_bot.fishing.cast_recorder import CastRecorder, fit_cast_params
from ttr_bot.fishing.fishing_bot import FishingBot, FishingConfig, FishingStats
from ttr_bot.ui.overlay import OverlayWindow
from ttr_bot.utils.logger import log


class _TkLogHandler(logging.Handler):
    """Streams log records into a tkinter ScrolledText widget."""

    def __init__(self, text_widget: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self._text = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record) + "\n"
        try:
            self._text.after(0, self._append, msg)
        except Exception:
            pass

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

    BG = "#0f3460"
    FG = "#eaeaea"
    ACCENT = "#e94560"
    ENTRY_BG = "#16213e"

    def __init__(self) -> None:
        self._root = tk.Tk()
        self._root.title("TTR Bot")
        screen_w = self._root.winfo_screenwidth()
        self._root.geometry(f"520x650+{screen_w - 540}+30")
        self._root.resizable(False, False)
        self._root.configure(bg=self.BG)

        self._bot = FishingBot()
        self._recorder = CastRecorder()
        self._overlay: OverlayWindow | None = None

        self._build_ui()
        self._attach_logger()
        self._wire_callbacks()
        self._poll_window_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        bg, fg, accent, entry_bg = self.BG, self.FG, self.ACCENT, self.ENTRY_BG

        # ---- Header ----
        tk.Label(
            root,
            text="TTR Bot",
            font=("Helvetica", 18, "bold"),
            fg=accent,
            bg=bg,
        ).pack(pady=(14, 2))

        self._status_var = tk.StringVar(value="Checking for TTR window…")
        self._status_label = tk.Label(
            root,
            textvariable=self._status_var,
            font=("Helvetica", 10),
            fg="#a0a0a0",
            bg=bg,
        )
        self._status_label.pack()

        # ---- Calibrate button ----
        cal_frame = tk.Frame(root, bg=bg)
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
        style.configure("Bot.TNotebook", background=bg)
        style.configure("Bot.TNotebook.Tab", font=("Helvetica", 11, "bold"))

        self._notebook = ttk.Notebook(root, style="Bot.TNotebook")
        self._notebook.pack(fill="both", expand=True, padx=12, pady=(6, 0))

        fish_tab = tk.Frame(self._notebook, bg=bg)
        self._notebook.add(fish_tab, text="  Fishing  ")
        self._build_fishing_tab(fish_tab)

        from ttr_bot.ui.gardening_tab import GardeningTab

        garden_frame = tk.Frame(self._notebook, bg=bg)
        self._notebook.add(garden_frame, text="  Gardening  ")
        self._garden_tab = GardeningTab(
            garden_frame,
            self._root,
            self._status_var,
            self._on_calibrate,
        )

        from ttr_bot.ui.golfing_tab import GolfingTab

        golf_frame = tk.Frame(self._notebook, bg=self.BG)
        self._notebook.add(golf_frame, text="  Golf  ")
        self._golf_tab = GolfingTab(
            golf_frame,
            self._root,
            self._status_var,
            self._on_calibrate,
        )

        # ---- Log output ----
        log_label = tk.Label(
            root,
            text="Log",
            font=("Helvetica", 10, "bold"),
            fg=fg,
            bg=bg,
            anchor="w",
        )
        log_label.pack(fill="x", padx=12)

        self._log_text = scrolledtext.ScrolledText(
            root,
            height=8,
            font=("Menlo", 9),
            bg=entry_bg,
            fg=fg,
            insertbackground=fg,
            state="disabled",
            wrap="word",
        )
        self._log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ------------------------------------------------------------------
    # Fishing tab
    # ------------------------------------------------------------------

    def _build_fishing_tab(self, parent: tk.Frame) -> None:
        bg, fg, accent, entry_bg = self.BG, self.FG, self.ACCENT, self.ENTRY_BG
        pad = {"padx": 8, "pady": 4}

        settings_frame = tk.LabelFrame(
            parent,
            text="Settings",
            font=("Helvetica", 11, "bold"),
            fg=fg,
            bg=bg,
            bd=1,
            relief="groove",
        )
        settings_frame.pack(fill="x", **pad)

        row = 0

        # Max casts
        tk.Label(settings_frame, text="Max casts:", fg=fg, bg=bg).grid(
            row=row,
            column=0,
            sticky="w",
            padx=8,
            pady=3,
        )
        self._casts_var = tk.IntVar(value=settings.DEFAULT_CASTS)
        tk.Spinbox(
            settings_frame,
            from_=1,
            to=999,
            textvariable=self._casts_var,
            width=8,
            bg=entry_bg,
            fg=fg,
            insertbackground=fg,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Bite timeout
        tk.Label(settings_frame, text="Bite timeout (s):", fg=fg, bg=bg).grid(
            row=row,
            column=0,
            sticky="w",
            padx=8,
            pady=3,
        )
        self._timeout_var = tk.IntVar(value=int(settings.BITE_TIMEOUT_S))
        tk.Spinbox(
            settings_frame,
            from_=5,
            to=120,
            textvariable=self._timeout_var,
            width=8,
            bg=entry_bg,
            fg=fg,
            insertbackground=fg,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Overlay checkbox
        checks_frame = tk.Frame(settings_frame, bg=bg)
        checks_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=3)

        self._overlay_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            checks_frame,
            text="Show overlay",
            variable=self._overlay_var,
            fg=fg,
            bg=bg,
            selectcolor=entry_bg,
            activebackground=bg,
            activeforeground=fg,
            command=self._toggle_overlay,
        ).pack(side="left")

        # ---- Action buttons ----
        btn_frame = tk.Frame(parent, bg=bg)
        btn_frame.pack(fill="x", padx=8, pady=8)

        self._start_btn = tk.Button(
            btn_frame,
            text="▶ Start Fishing",
            font=("Helvetica", 12, "bold"),
            highlightbackground="#1a8f3c",
            width=16,
            command=self._on_start,
        )
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = tk.Button(
            btn_frame,
            text="■ Stop",
            font=("Helvetica", 12, "bold"),
            highlightbackground=accent,
            width=10,
            command=self._on_stop,
            state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(0, 8))

        self._pause_btn = tk.Button(
            btn_frame,
            text="Pause",
            font=("Helvetica", 11),
            highlightbackground="#533483",
            width=8,
            command=self._on_pause,
            state="disabled",
        )
        self._pause_btn.pack(side="left")

        # ---- Cast recording ----
        rec_frame = tk.Frame(parent, bg=bg)
        rec_frame.pack(fill="x", padx=8, pady=(0, 4))

        self._record_btn = tk.Button(
            rec_frame,
            text="Record Casts",
            font=("Helvetica", 11),
            highlightbackground="#e67e22",
            width=14,
            command=self._on_record_toggle,
        )
        self._record_btn.pack(side="left", padx=(0, 8))

        self._record_status = tk.Label(
            rec_frame,
            text="Fish manually to calibrate casting",
            font=("Helvetica", 10),
            fg="#e67e22",
            bg=bg,
        )
        self._record_status.pack(side="left")

    # ------------------------------------------------------------------
    # Logger / callbacks
    # ------------------------------------------------------------------

    def _attach_logger(self) -> None:
        handler = _TkLogHandler(self._log_text)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        log.addHandler(handler)

    def _wire_callbacks(self) -> None:
        self._bot.on_stats_update = self._on_stats_thread
        self._bot.on_status_update = self._on_status_thread
        self._bot.on_fishing_ended = self._on_ended_thread

    # ------------------------------------------------------------------
    # Fishing handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if self._bot.running:
            return

        import threading

        from ttr_bot.core.screen_capture import capture_window
        from ttr_bot.core.window_manager import find_ttr_window, set_calibrated_bounds

        self._start_btn.config(state="disabled")
        self._status_var.set("Calibrating…")

        def _calibrate_and_start() -> None:
            from ttr_bot.vision.template_matcher import calibrate_scale, clear_cache

            win = find_ttr_window()
            if win is None:
                self._root.after(0, self._start_failed, "TTR window not found")
                return

            set_calibrated_bounds(
                win.x, win.y, win.width, win.height, window_id=win.window_id, pid=win.pid
            )
            log.info("Window locked: %dx%d at (%d,%d)", win.width, win.height, win.x, win.y)

            clear_cache()
            frame = capture_window(win)
            if frame is None:
                self._root.after(0, self._start_failed, "Capture failed")
                return

            scale = calibrate_scale(frame)
            if scale < 0:
                self._root.after(0, self._start_failed, "Calibration failed — sit on dock first!")
                return

            self._root.after(0, self._start_fishing, scale, win.width, win.height)

        threading.Thread(target=_calibrate_and_start, daemon=True).start()

    def _start_failed(self, msg: str) -> None:
        self._status_var.set(msg)
        self._start_btn.config(state="normal")

    def _start_fishing(self, scale: float, w: int, h: int) -> None:
        self._status_var.set(f"Calibrated: {w}×{h} scale={scale:.1f}")

        cfg = FishingConfig(
            max_casts=self._casts_var.get(),
            bite_timeout=float(self._timeout_var.get()),
        )

        if self._overlay_var.get() and self._overlay is None:
            self._overlay = OverlayWindow()

        self._stop_btn.config(state="normal")
        self._pause_btn.config(state="normal")
        self._bot.start(cfg)

    def _on_stop(self) -> None:
        self._bot.stop()
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._pause_btn.config(state="disabled", text="Pause")

    def _on_pause(self) -> None:
        self._bot.toggle_pause()
        text = "Resume" if self._bot.paused else "Pause"
        self._pause_btn.config(text=text)

    def _on_calibrate(self) -> None:
        import threading

        from ttr_bot.core.screen_capture import capture_window
        from ttr_bot.core.window_manager import find_ttr_window, set_calibrated_bounds

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

    def _on_record_toggle(self) -> None:
        """Start or stop recording manual casts for calibration."""
        import threading

        if self._recorder.recording:
            self._recorder.stop()
            self._record_btn.config(text="Record Casts", state="disabled")
            self._record_status.config(text="Stopping…")

            def _finish_recording() -> None:
                if self._recorder._thread is not None:
                    self._recorder._thread.join(timeout=5.0)
                samples = list(self._recorder.samples)
                self._root.after(0, self._on_recording_done, samples)

            threading.Thread(target=_finish_recording, daemon=True).start()
        else:
            self._recorder.on_status = lambda msg: self._root.after(
                0,
                self._record_status.config,
                {"text": msg},
            )
            self._recorder.start()
            self._record_btn.config(text="Stop Recording")
            self._record_status.config(text="Fish normally — recording…")

    def _on_recording_done(self, samples: list) -> None:
        self._record_btn.config(state="normal")
        if len(samples) >= 2:
            self._record_status.config(text="Fitting cast curves…")
            params = fit_cast_params(samples)
            if params is not None:
                from ttr_bot.core.input_controller import reload_cast_params

                reload_cast_params()
                self._record_status.config(
                    text=f"Done! power={params.power_base:.1f} aim={params.aim_base:.1f}"
                )
            else:
                self._record_status.config(text="Fit failed — try more casts")
        else:
            self._record_status.config(text=f"Need 2+ casts, got {len(samples)}")

    # ------------------------------------------------------------------
    # Overlay
    # ------------------------------------------------------------------

    def _toggle_overlay(self) -> None:
        if self._overlay_var.get():
            if self._overlay is None:
                self._overlay = OverlayWindow()
            else:
                self._overlay.show()
        else:
            if self._overlay is not None:
                self._overlay.hide()

    # ------------------------------------------------------------------
    # Thread-safe callbacks
    # ------------------------------------------------------------------

    def _on_stats_thread(self, stats: FishingStats) -> None:
        self._root.after(0, self._on_stats_ui, stats)

    def _on_status_thread(self, msg: str) -> None:
        self._root.after(0, self._status_var.set, msg)

    def _on_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_ended_ui, reason)

    def _on_stats_ui(self, stats: FishingStats) -> None:
        if self._overlay:
            self._overlay.update_stats(stats)

    def _on_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Stopped: {reason}")
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._pause_btn.config(state="disabled", text="Pause")

    # ------------------------------------------------------------------
    # Periodic checks
    # ------------------------------------------------------------------

    def _poll_window_status(self) -> None:
        available = is_window_available()
        if not self._bot.running:
            garden_running = hasattr(self, "_garden_tab") and (
                self._garden_tab._bot.running or self._garden_tab._routine_runner.running
            )
            golf_running = hasattr(self, "_golf_tab") and self._golf_tab.running
            busy_other = garden_running or golf_running
            if not busy_other:
                self._status_var.set(
                    "TTR window detected" if available else "TTR window not found"
                )
            can_start = available and not busy_other
            self._start_btn.config(state="normal" if can_start else "disabled")
        self._root.after(2000, self._poll_window_status)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self) -> None:
        if self._bot.running:
            self._bot.stop()
        if hasattr(self, "_garden_tab"):
            self._garden_tab.shutdown()
        if hasattr(self, "_golf_tab"):
            self._golf_tab.shutdown()
        if self._overlay:
            self._overlay.destroy()
        self._root.destroy()
