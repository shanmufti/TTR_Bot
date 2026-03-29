"""Tkinter GUI for the TTR Bot (Fishing, Gardening, Golf)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, scrolledtext
import logging

from ttr_bot.config import settings
from ttr_bot.core.window_manager import is_window_available
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
            root, text="TTR Bot", font=("Helvetica", 18, "bold"),
            fg=accent, bg=bg,
        ).pack(pady=(14, 2))

        self._status_var = tk.StringVar(value="Checking for TTR window…")
        self._status_label = tk.Label(
            root, textvariable=self._status_var, font=("Helvetica", 10),
            fg="#a0a0a0", bg=bg,
        )
        self._status_label.pack()

        # ---- Calibrate button ----
        cal_frame = tk.Frame(root, bg=bg)
        cal_frame.pack(fill="x", padx=12, pady=(6, 2))

        self._calibrate_btn = tk.Button(
            cal_frame, text="Calibrate Window", font=("Helvetica", 11),
            highlightbackground="#2980b9", width=16, command=self._on_calibrate,
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
            garden_frame, self._root, self._status_var, self._on_calibrate,
        )

        from ttr_bot.ui.golfing_tab import GolfingTab
        golf_frame = tk.Frame(self._notebook, bg=self.BG)
        self._notebook.add(golf_frame, text="  Golf  ")
        self._golf_tab = GolfingTab(
            golf_frame, self._root, self._status_var, self._on_calibrate,
        )

        # ---- Log output ----
        log_label = tk.Label(
            root, text="Log", font=("Helvetica", 10, "bold"),
            fg=fg, bg=bg, anchor="w",
        )
        log_label.pack(fill="x", padx=12)

        self._log_text = scrolledtext.ScrolledText(
            root, height=8, font=("Menlo", 9), bg=entry_bg, fg=fg,
            insertbackground=fg, state="disabled", wrap="word",
        )
        self._log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # ------------------------------------------------------------------
    # Fishing tab
    # ------------------------------------------------------------------

    def _build_fishing_tab(self, parent: tk.Frame) -> None:
        bg, fg, accent, entry_bg = self.BG, self.FG, self.ACCENT, self.ENTRY_BG
        pad = {"padx": 8, "pady": 4}

        settings_frame = tk.LabelFrame(
            parent, text="Settings", font=("Helvetica", 11, "bold"),
            fg=fg, bg=bg, bd=1, relief="groove",
        )
        settings_frame.pack(fill="x", **pad)

        row = 0

        # Max casts
        tk.Label(settings_frame, text="Max casts:", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._casts_var = tk.IntVar(value=settings.DEFAULT_CASTS)
        tk.Spinbox(
            settings_frame, from_=1, to=999, textvariable=self._casts_var,
            width=8, bg=entry_bg, fg=fg, insertbackground=fg,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Bite timeout
        tk.Label(settings_frame, text="Bite timeout (s):", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._timeout_var = tk.IntVar(value=int(settings.BITE_TIMEOUT_S))
        tk.Spinbox(
            settings_frame, from_=5, to=120, textvariable=self._timeout_var,
            width=8, bg=entry_bg, fg=fg, insertbackground=fg,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Overlay checkbox
        checks_frame = tk.Frame(settings_frame, bg=bg)
        checks_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=3)

        self._overlay_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            checks_frame, text="Show overlay", variable=self._overlay_var,
            fg=fg, bg=bg, selectcolor=entry_bg, activebackground=bg, activeforeground=fg,
            command=self._toggle_overlay,
        ).pack(side="left")

        # ---- Action buttons ----
        btn_frame = tk.Frame(parent, bg=bg)
        btn_frame.pack(fill="x", padx=8, pady=8)

        self._start_btn = tk.Button(
            btn_frame, text="▶ Start Fishing", font=("Helvetica", 12, "bold"),
            highlightbackground="#1a8f3c", width=16, command=self._on_start,
        )
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = tk.Button(
            btn_frame, text="■ Stop", font=("Helvetica", 12, "bold"),
            highlightbackground=accent, width=10, command=self._on_stop, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(0, 8))

        self._pause_btn = tk.Button(
            btn_frame, text="Pause", font=("Helvetica", 11),
            highlightbackground="#533483", width=8,
            command=self._on_pause, state="disabled",
        )
        self._pause_btn.pack(side="left")

        # ---- Cast calibration ----
        cal_frame = tk.Frame(parent, bg=bg)
        cal_frame.pack(fill="x", padx=8, pady=(0, 4))

        self._cast_cal_btn = tk.Button(
            cal_frame, text="Calibrate Cast", font=("Helvetica", 11),
            highlightbackground="#e67e22", width=14, command=self._on_calibrate_cast,
        )
        self._cast_cal_btn.pack(side="left", padx=(0, 8))

        self._cast_cal_status = tk.Label(
            cal_frame, text="", font=("Helvetica", 10), fg="#e67e22", bg=bg,
        )
        self._cast_cal_status.pack(side="left")

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

        self._status_var.set("Calibrating…")
        self._root.update_idletasks()
        self._on_calibrate()

        from ttr_bot.vision import template_matcher as tm
        if tm._global_scale is None:
            self._status_var.set("Calibration failed — sit on dock first!")
            return

        from ttr_bot.core.cast_calibration import cast_calibration
        if not cast_calibration.is_calibrated:
            cast_calibration.load()
        if not cast_calibration.is_calibrated:
            self._status_var.set("Run Calibrate Cast first!")
            return

        cfg = FishingConfig(
            max_casts=self._casts_var.get(),
            bite_timeout=float(self._timeout_var.get()),
        )

        if self._overlay_var.get() and self._overlay is None:
            self._overlay = OverlayWindow()

        self._start_btn.config(state="disabled")
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
        from ttr_bot.core.window_manager import find_ttr_window, set_calibrated_bounds
        from ttr_bot.vision.template_matcher import clear_cache, calibrate_scale
        from ttr_bot.core.screen_capture import capture_window

        win = find_ttr_window()
        if win is None:
            self._status_var.set("Calibration failed — TTR not found")
            return

        set_calibrated_bounds(win.x, win.y, win.width, win.height)
        log.info("Window locked: %dx%d at (%d,%d)", win.width, win.height, win.x, win.y)

        clear_cache()
        frame = capture_window(win)
        if frame is None:
            self._status_var.set("Calibration failed — capture error")
            return

        scale = calibrate_scale(frame)
        if scale < 0:
            self._status_var.set("Calibration failed — no known button visible")
        else:
            self._status_var.set(f"Calibrated: {win.width}×{win.height} scale={scale:.1f}")

    def _on_calibrate_cast(self) -> None:
        """Fully automatic cast calibration — bot casts 3 times and detects landings."""
        import threading

        def _run() -> None:
            import time
            from ttr_bot.core.window_manager import find_ttr_window, focus_window
            from ttr_bot.core.screen_capture import capture_window
            from ttr_bot.core.input_controller import fishing_cast_raw, ensure_focused
            from ttr_bot.vision.template_matcher import find_template
            from ttr_bot.vision.pond_detector import detect_pond
            from ttr_bot.core.cast_calibration import (
                CastCalibration, CalibrationSample, CALIBRATION_DRAGS,
                cast_calibration, detect_bobber,
            )

            self._cast_cal_btn.config(state="disabled")
            total = len(CALIBRATION_DRAGS)

            win = find_ttr_window()
            if win is None:
                self._cast_cal_status.config(text="TTR not found")
                self._cast_cal_btn.config(state="normal")
                return

            focus_window()
            time.sleep(0.3)

            frame = capture_window(win)
            if frame is None:
                self._cast_cal_status.config(text="Capture failed")
                self._cast_cal_btn.config(state="normal")
                return

            btn = find_template(frame, "red_fishing_button")
            if btn is None:
                self._cast_cal_status.config(text="Sit on dock first!")
                self._cast_cal_btn.config(state="normal")
                return

            pond = detect_pond(frame)
            if pond.empty:
                self._cast_cal_status.config(text="Pond not detected")
                self._cast_cal_btn.config(state="normal")
                return

            new_cal = CastCalibration()

            for idx, (drag_dx, drag_dy) in enumerate(CALIBRATION_DRAGS):
                label = f"Auto-casting {idx + 1}/{total}…"
                self._cast_cal_status.config(text=label)
                log.info("Cast calibration: %s drag=(%+d,%+d)", label, drag_dx, drag_dy)

                before = capture_window(win)
                if before is None:
                    continue

                new_btn = find_template(before, "red_fishing_button")
                if new_btn is not None:
                    btn = new_btn
                else:
                    continue

                ensure_focused()
                fishing_cast_raw(btn.x, btn.y, drag_dx, drag_dy, window=win)
                time.sleep(2.0)

                after = capture_window(win)
                if after is None:
                    continue

                landing = detect_bobber(
                    before, after, pond.x, pond.y, pond.width, pond.height,
                )
                if landing is None:
                    self._cast_cal_status.config(text=f"Bobber not found ({idx + 1}/{total})")
                    time.sleep(12.0)
                    continue

                bx, by = landing
                land_dx = float(bx - btn.x)
                land_dy = float(by - btn.y)
                new_cal.add_sample(CalibrationSample(drag_dx, drag_dy, land_dx, land_dy))

                self._cast_cal_status.config(text=f"Waiting for reset ({idx + 1}/{total})…")
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    f = capture_window(win)
                    if f is not None and find_template(f, "red_fishing_button") is not None:
                        break
                time.sleep(0.5)

            if new_cal.sample_count >= 2 and new_cal.fit():
                cast_calibration._samples = new_cal._samples
                cast_calibration._matrix = new_cal._matrix
                cast_calibration.save()
                self._cast_cal_status.config(text="Cast calibration complete!")
                log.info("Cast calibration complete (%d samples)", new_cal.sample_count)
            else:
                self._cast_cal_status.config(
                    text=f"Calibration failed ({new_cal.sample_count} samples)"
                )

            self._cast_cal_btn.config(state="normal")

        threading.Thread(target=_run, daemon=True).start()

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
                self._garden_tab._bot.running
                or self._garden_tab._routine_runner.running
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
