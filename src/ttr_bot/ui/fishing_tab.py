"""Fishing tab UI for the TTR Bot."""

import threading
import tkinter as tk
from collections.abc import Callable

from ttr_bot.config import settings
from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import find_ttr_window, set_calibrated_bounds
from ttr_bot.fishing.cast_recorder import CastRecorder, fit_cast_params
from ttr_bot.fishing.fishing_bot import FishingBot, FishingConfig, FishingStats
from ttr_bot.ui.overlay import OverlayWindow
from ttr_bot.ui.theme import ACCENT, BG, ENTRY_BG, FG
from ttr_bot.utils.logger import log


class FishingTab:
    """Builds and manages the Fishing tab inside a parent frame."""

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

        self._bot = FishingBot()
        self._recorder = CastRecorder()
        self._overlay: OverlayWindow | None = None

        self._build_ui()
        self._wire_callbacks()

    @property
    def running(self) -> bool:
        return self._bot.running

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        parent = self._parent
        pad = {"padx": 8, "pady": 4}

        settings_frame = tk.LabelFrame(
            parent,
            text="Settings",
            font=("Helvetica", 11, "bold"),
            fg=FG,
            bg=BG,
            bd=1,
            relief="groove",
        )
        settings_frame.pack(fill="x", **pad)

        row = 0

        tk.Label(settings_frame, text="Max casts:", fg=FG, bg=BG).grid(
            row=row, column=0, sticky="w", padx=8, pady=3
        )
        self._casts_var = tk.IntVar(value=settings.DEFAULT_CASTS)
        tk.Spinbox(
            settings_frame,
            from_=1,
            to=999,
            textvariable=self._casts_var,
            width=8,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=FG,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        tk.Label(settings_frame, text="Bite timeout (s):", fg=FG, bg=BG).grid(
            row=row, column=0, sticky="w", padx=8, pady=3
        )
        self._timeout_var = tk.IntVar(value=int(settings.BITE_TIMEOUT_S))
        tk.Spinbox(
            settings_frame,
            from_=5,
            to=120,
            textvariable=self._timeout_var,
            width=8,
            bg=ENTRY_BG,
            fg=FG,
            insertbackground=FG,
        ).grid(row=row, column=1, sticky="w", padx=4, pady=3)
        row += 1

        checks_frame = tk.Frame(settings_frame, bg=BG)
        checks_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=3)

        self._overlay_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            checks_frame,
            text="Show overlay",
            variable=self._overlay_var,
            fg=FG,
            bg=BG,
            selectcolor=ENTRY_BG,
            activebackground=BG,
            activeforeground=FG,
            command=self._toggle_overlay,
        ).pack(side="left")

        btn_frame = tk.Frame(parent, bg=BG)
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
            highlightbackground=ACCENT,
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

        rec_frame = tk.Frame(parent, bg=BG)
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
            bg=BG,
        )
        self._record_status.pack(side="left")

    # ------------------------------------------------------------------
    # Callbacks wiring
    # ------------------------------------------------------------------

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

    def _on_record_toggle(self) -> None:
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

            def _update_status(msg: str) -> None:
                self._root.after(0, self._record_status.config, {"text": msg})

            self._recorder.on_status = _update_status
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
        elif self._overlay is not None:
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
    # Public helpers for App
    # ------------------------------------------------------------------

    def set_start_enabled(self, enabled: bool) -> None:
        self._start_btn.config(state="normal" if enabled else "disabled")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._bot.running:
            self._bot.stop()
        if self._overlay:
            self._overlay.destroy()
