"""Tkinter GUI for the TTR Fishing Bot."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext
import logging

from config import settings
from core.window_manager import is_window_available
from fishing.fishing_bot import FishingBot, FishingConfig, FishingStats
from fishing.sell_controller import list_sell_paths
from ui.overlay import OverlayWindow
from utils.logger import log


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
    """Main application window."""

    _SELL_AUTO = "(auto)"

    def __init__(self) -> None:
        self._root = tk.Tk()
        self._root.title("TTR Fishing Bot")
        screen_w = self._root.winfo_screenwidth()
        self._root.geometry(f"520x690+{screen_w - 540}+30")
        self._root.resizable(False, False)
        self._root.configure(bg="#0f3460")

        self._bot = FishingBot()
        self._overlay: OverlayWindow | None = None

        self._build_ui()
        self._attach_logger()
        self._wire_callbacks()
        self._on_location_changed()
        self._poll_window_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        pad = {"padx": 12, "pady": 4}
        bg = "#0f3460"
        fg = "#eaeaea"
        accent = "#e94560"
        entry_bg = "#16213e"

        # Title
        tk.Label(
            root, text="TTR Fishing Bot", font=("Helvetica", 18, "bold"),
            fg=accent, bg=bg,
        ).pack(pady=(14, 2))

        # Status bar
        self._status_var = tk.StringVar(value="Checking for TTR window…")
        self._status_label = tk.Label(
            root, textvariable=self._status_var, font=("Helvetica", 10),
            fg="#a0a0a0", bg=bg,
        )
        self._status_label.pack()

        # ---- Settings frame ----
        settings_frame = tk.LabelFrame(
            root, text="Settings", font=("Helvetica", 11, "bold"),
            fg=fg, bg=bg, bd=1, relief="groove",
        )
        settings_frame.pack(fill="x", **pad)

        row = 0

        # Location
        tk.Label(settings_frame, text="Location:", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._location_var = tk.StringVar(value=settings.FISHING_LOCATIONS[0])
        loc_combo = ttk.Combobox(
            settings_frame, textvariable=self._location_var,
            values=settings.FISHING_LOCATIONS, state="readonly", width=28,
        )
        loc_combo.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        loc_combo.bind("<<ComboboxSelected>>", lambda _: self._on_location_changed())
        row += 1

        # Casts
        tk.Label(settings_frame, text="Casts per round:", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._casts_var = tk.IntVar(value=settings.DEFAULT_CASTS)
        tk.Spinbox(
            settings_frame, from_=1, to=999, textvariable=self._casts_var,
            width=8, bg=entry_bg, fg=fg, insertbackground=fg,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Sell rounds
        tk.Label(settings_frame, text="Sell rounds:", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._sells_var = tk.IntVar(value=settings.DEFAULT_SELL_ROUNDS)
        tk.Spinbox(
            settings_frame, from_=1, to=99, textvariable=self._sells_var,
            width=8, bg=entry_bg, fg=fg, insertbackground=fg,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        # Variance
        tk.Label(settings_frame, text="Cast variance (px):", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        self._variance_var = tk.IntVar(value=settings.DEFAULT_VARIANCE)
        tk.Spinbox(
            settings_frame, from_=0, to=100, textvariable=self._variance_var,
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

        # Sell path
        tk.Label(settings_frame, text="Sell path:", fg=fg, bg=bg).grid(
            row=row, column=0, sticky="w", padx=8, pady=3,
        )
        sell_outer = tk.Frame(settings_frame, bg=bg)
        sell_outer.grid(row=row, column=1, sticky="w", padx=4, pady=3)

        sell_row1 = tk.Frame(sell_outer, bg=bg)
        sell_row1.pack(anchor="w")

        sell_options = self._get_sell_path_options()
        default_sell = next(
            (n for n in sell_options if "donalds" in n.lower() or "dreamland" in n.lower()),
            self._SELL_AUTO,
        )
        self._sell_path_var = tk.StringVar(value=default_sell)
        self._sell_path_combo = ttk.Combobox(
            sell_row1, textvariable=self._sell_path_var,
            values=sell_options, state="readonly", width=20,
        )
        self._sell_path_combo.pack(side="left")

        tk.Button(
            sell_row1, text="Record", font=("Helvetica", 9),
            highlightbackground="#533483",
            command=self._on_record_sell_path,
        ).pack(side="left", padx=(6, 0))

        tk.Button(
            sell_row1, text="↻", font=("Helvetica", 9),
            highlightbackground=entry_bg, width=2,
            command=self._refresh_sell_paths,
        ).pack(side="left", padx=(4, 0))

        self._sell_status_var = tk.StringVar(value="")
        self._sell_status_label = tk.Label(
            sell_outer, textvariable=self._sell_status_var,
            font=("Helvetica", 9), fg="#a0a0a0", bg=bg, anchor="w",
        )
        self._sell_status_label.pack(anchor="w", pady=(2, 0))
        row += 1

        # Checkboxes
        checks_frame = tk.Frame(settings_frame, bg=bg)
        checks_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=3)


        self._quickcast_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            checks_frame, text="Quick cast", variable=self._quickcast_var,
            fg=fg, bg=bg, selectcolor=entry_bg, activebackground=bg, activeforeground=fg,
        ).pack(side="left", padx=(0, 12))

        self._overlay_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            checks_frame, text="Show overlay", variable=self._overlay_var,
            fg=fg, bg=bg, selectcolor=entry_bg, activebackground=bg, activeforeground=fg,
            command=self._toggle_overlay,
        ).pack(side="left")

        # ---- Buttons ----
        style = ttk.Style()
        style.configure("Green.TButton", font=("Helvetica", 12, "bold"))
        style.configure("Red.TButton", font=("Helvetica", 12, "bold"))
        style.configure("Purple.TButton", font=("Helvetica", 11))
        style.configure("Blue.TButton", font=("Helvetica", 11))
        style.configure("Gold.TButton", font=("Helvetica", 11))

        btn_frame = tk.Frame(root, bg=bg)
        btn_frame.pack(fill="x", padx=12, pady=8)

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

        # ---- Calibrate / Test buttons ----
        test_frame = tk.Frame(root, bg=bg)
        test_frame.pack(fill="x", padx=12, pady=(0, 8))

        self._calibrate_btn = tk.Button(
            test_frame, text="Calibrate Window", font=("Helvetica", 11),
            highlightbackground="#2980b9", width=16, command=self._on_calibrate,
        )
        self._calibrate_btn.pack(side="left", padx=(0, 8))

        self._test_sell_btn = tk.Button(
            test_frame, text="Test Sell Trip", font=("Helvetica", 11),
            highlightbackground="#b8860b", width=14, command=self._on_test_sell,
        )
        self._test_sell_btn.pack(side="left")

        # ---- Cast calibration button ----
        cast_cal_frame = tk.Frame(root, bg=bg)
        cast_cal_frame.pack(fill="x", padx=12, pady=(0, 8))

        self._cast_cal_btn = tk.Button(
            cast_cal_frame, text="Calibrate Cast", font=("Helvetica", 11),
            highlightbackground="#e67e22", width=16, command=self._on_calibrate_cast,
        )
        self._cast_cal_btn.pack(side="left", padx=(0, 8))

        self._cast_cal_status = tk.Label(
            cast_cal_frame, text="", font=("Helvetica", 10), fg="#e67e22", bg=bg,
        )
        self._cast_cal_status.pack(side="left")

        # ---- Log output ----
        log_label = tk.Label(
            root, text="Log", font=("Helvetica", 10, "bold"), fg=fg, bg=bg, anchor="w",
        )
        log_label.pack(fill="x", padx=12)

        self._log_text = scrolledtext.ScrolledText(
            root, height=12, font=("Menlo", 9), bg=entry_bg, fg=fg,
            insertbackground=fg, state="disabled", wrap="word",
        )
        self._log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _attach_logger(self) -> None:
        handler = _TkLogHandler(self._log_text)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        log.addHandler(handler)

    def _wire_callbacks(self) -> None:
        self._bot.on_stats_update = self._on_stats_update_thread
        self._bot.on_status_update = self._on_status_update_thread
        self._bot.on_fishing_ended = self._on_fishing_ended_thread

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if self._bot.running:
            return

        # --- Auto-calibrate window before fishing ---
        self._status_var.set("Calibrating…")
        self._root.update_idletasks()
        self._on_calibrate()

        from vision.template_matcher import _global_scale
        if _global_scale is None:
            self._status_var.set("Calibration failed — sit on dock first!")
            return

        # --- Load cast calibration ---
        from core.cast_calibration import cast_calibration
        if not cast_calibration.is_calibrated:
            cast_calibration.load()
        if not cast_calibration.is_calibrated:
            self._status_var.set("Run Calibrate Cast first!")
            return

        # Resolve sell path file — explicit selection or auto-match by location
        sell_path_file = None
        sell_choice = self._sell_path_var.get()
        if sell_choice and sell_choice != self._SELL_AUTO:
            for entry in list_sell_paths():
                if entry["name"] == sell_choice:
                    sell_path_file = entry["path"]
                    break
        # (auto): sell_controller will match by location name at runtime

        cfg = FishingConfig(
            location=self._location_var.get(),
            casts_per_round=self._casts_var.get(),
            sell_rounds=self._sells_var.get(),
            variance=self._variance_var.get(),
            auto_detect=True,
            quick_cast=self._quickcast_var.get(),
            bite_timeout=float(self._timeout_var.get()),
            sell_path_file=sell_path_file,
        )

        if self._overlay_var.get() and self._overlay is None:
            self._overlay = OverlayWindow()

        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._pause_btn.config(state="normal")

        log.info("Starting fishing: %s", cfg)
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
        """Detect the current TTR window bounds and lock them for the session."""
        from core.window_manager import find_ttr_window, set_calibrated_bounds
        from vision.template_matcher import clear_cache, calibrate_scale
        from core.screen_capture import capture_window

        win = find_ttr_window()
        if win is None:
            log.warning("Calibration failed: TTR window not found")
            self._status_var.set("Calibration failed — TTR not found")
            return

        set_calibrated_bounds(win.x, win.y, win.width, win.height)
        log.info("Window locked: %dx%d at (%d,%d)", win.width, win.height, win.x, win.y)

        clear_cache()
        frame = capture_window(win)
        if frame is None:
            log.warning("Could not capture frame — check Screen Recording permission")
            self._status_var.set("Calibration failed — capture error")
            return

        scale = calibrate_scale(frame)
        if scale < 0:
            self._status_var.set("Calibration failed — sit on dock first!")
        else:
            self._status_var.set(f"Calibrated: {win.width}×{win.height} scale={scale:.1f}")

    def _on_calibrate_cast(self) -> None:
        """Fully automatic cast calibration — bot casts 3 times and detects landings."""
        import threading

        def _run() -> None:
            import time
            from core.window_manager import find_ttr_window, focus_window
            from core.screen_capture import capture_window
            from core.input_controller import fishing_cast_raw, ensure_focused
            from vision.template_matcher import find_template
            from vision.pond_detector import detect_pond
            from core.cast_calibration import (
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

                # Capture before frame
                before = capture_window(win)
                if before is None:
                    log.warning("Cast calibration: capture failed on cast %d", idx + 1)
                    continue

                # Re-detect button (may shift after previous cast)
                new_btn = find_template(before, "red_fishing_button")
                if new_btn is not None:
                    btn = new_btn
                else:
                    log.warning("Cast button not found for calibration cast %d", idx + 1)
                    continue

                # Perform the cast with known drag
                ensure_focused()
                fishing_cast_raw(btn.x, btn.y, drag_dx, drag_dy, window=win)

                # Wait for bobber to settle
                time.sleep(2.0)

                # Capture after frame and detect bobber
                after = capture_window(win)
                if after is None:
                    log.warning("Cast calibration: post-cast capture failed")
                    continue

                landing = detect_bobber(
                    before, after, pond.x, pond.y, pond.width, pond.height,
                )
                if landing is None:
                    log.warning("Cast calibration: bobber not detected for cast %d", idx + 1)
                    # Wait for timeout/bite before next cast
                    self._cast_cal_status.config(text=f"Bobber not found ({idx + 1}/{total})")
                    time.sleep(12.0)
                    continue

                bx, by = landing
                land_dx = float(bx - btn.x)
                land_dy = float(by - btn.y)
                new_cal.add_sample(CalibrationSample(drag_dx, drag_dy, land_dx, land_dy))

                # Wait for the bite timeout / catch popup to clear before next cast
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

    def _on_test_sell(self) -> None:
        """Run a test sell trip in a background thread (calibrate + sell)."""
        import threading

        def _run():
            try:
                from core.window_manager import find_ttr_window, focus_window
                from core.screen_capture import capture_window
                from vision.template_matcher import calibrate_scale, clear_cache
                from fishing.sell_controller import walk_and_sell

                self._test_sell_btn.config(state="disabled", text="Running…")
                log.info("Test sell: starting…")

                focus_window()
                import time
                time.sleep(0.3)
                win = find_ttr_window()
                if win is None:
                    log.warning("Test sell: TTR window not found")
                    return

                clear_cache()
                frame = capture_window(win)
                if frame is not None:
                    calibrate_scale(frame)

                location = self._location_var.get()
                walk_and_sell(location)
                log.info("Test sell: complete")
            except Exception as exc:
                log.exception("Test sell failed: %s", exc)
            finally:
                self._root.after(0, lambda: self._test_sell_btn.config(
                    state="normal", text="Test Sell Trip",
                ))

        threading.Thread(target=_run, daemon=True).start()

    def _get_sell_path_options(self) -> list[str]:
        """Build the dropdown list of sell paths."""
        options = [self._SELL_AUTO]
        for entry in list_sell_paths():
            options.append(entry["name"])
        return options

    def _get_sell_path_names(self) -> set[str]:
        """Return a set of recorded sell path names (lowercased)."""
        return {e["name"].lower() for e in list_sell_paths()}

    def _on_location_changed(self) -> None:
        """When the fishing location changes, update the sell path status."""
        location = self._location_var.get()
        if location == "Fish Anywhere":
            self._sell_status_var.set("No sell needed for Fish Anywhere")
            self._sell_status_label.config(fg="#a0a0a0")
            return

        recorded = self._get_sell_path_names()
        if location.lower() in recorded:
            self._sell_status_var.set(f"Sell path found for {location}")
            self._sell_status_label.config(fg="#1a8f3c")
        else:
            self._sell_status_var.set(f"No sell path for {location} — click Record")
            self._sell_status_label.config(fg="#e94560")

    def _refresh_sell_paths(self) -> None:
        """Refresh the sell path dropdown and re-check status."""
        options = self._get_sell_path_options()
        self._sell_path_combo["values"] = options
        log.info("Refreshed sell paths: %d custom paths found", len(options) - 1)
        self._on_location_changed()

    def _on_record_sell_path(self) -> None:
        """Launch the sell-path recorder in a new terminal window.

        Pre-fills the current fishing location as the suggested path name.
        """
        script = os.path.join(settings.PROJECT_ROOT, "record_sell_path.py")
        venv_python = os.path.join(settings.PROJECT_ROOT, "venv", "bin", "python3")
        if not os.path.isfile(venv_python):
            venv_python = sys.executable

        location = self._location_var.get()
        cmd = f'cd "{settings.PROJECT_ROOT}" && "{venv_python}" "{script}" --name "{location}"'
        subprocess.Popen(
            ["osascript", "-e", f'tell app "Terminal" to do script "{cmd}"'],
        )
        log.info("Launched sell-path recorder for '%s'", location)

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
    # Thread-safe callbacks from the fishing bot
    # ------------------------------------------------------------------

    def _on_stats_update_thread(self, stats: FishingStats) -> None:
        self._root.after(0, self._on_stats_update_ui, stats)

    def _on_status_update_thread(self, msg: str) -> None:
        self._root.after(0, self._on_status_update_ui, msg)

    def _on_fishing_ended_thread(self, reason: str) -> None:
        self._root.after(0, self._on_fishing_ended_ui, reason)

    def _on_stats_update_ui(self, stats: FishingStats) -> None:
        if self._overlay:
            self._overlay.update_stats(stats)

    def _on_status_update_ui(self, msg: str) -> None:
        self._status_var.set(msg)
        if self._overlay:
            self._overlay.update_status(msg)

    def _on_fishing_ended_ui(self, reason: str) -> None:
        self._status_var.set(f"Stopped: {reason}")
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._pause_btn.config(state="disabled", text="Pause")

    # ------------------------------------------------------------------
    # Periodic checks
    # ------------------------------------------------------------------

    def _poll_window_status(self) -> None:
        """Check every 2 seconds whether the TTR window is visible."""
        available = is_window_available()
        if not self._bot.running:
            self._status_var.set(
                "TTR window detected" if available else "TTR window not found"
            )
            self._start_btn.config(state="normal" if available else "disabled")
        self._root.after(2000, self._poll_window_status)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the tkinter main loop."""
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self) -> None:
        if self._bot.running:
            self._bot.stop()
        if self._overlay:
            self._overlay.destroy()
        self._root.destroy()
