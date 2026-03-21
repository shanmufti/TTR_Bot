"""Translucent stats overlay window for fishing progress."""

from __future__ import annotations

import tkinter as tk
from fishing.fishing_bot import FishingStats


class OverlayWindow:
    """A small, always-on-top, semi-transparent overlay showing fishing stats."""

    def __init__(self) -> None:
        self._root = tk.Toplevel()
        self._root.title("TTR Bot Overlay")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)

        # macOS transparency
        self._root.attributes("-alpha", 0.85)

        self._root.configure(bg="#1a1a2e")

        # Position: top-right corner
        self._root.geometry("260x160+20+40")

        self._root.bind("<Button-1>", self._start_move)
        self._root.bind("<B1-Motion>", self._do_move)

        header = tk.Label(
            self._root, text="TTR Fishing Bot", font=("Helvetica", 13, "bold"),
            fg="#e94560", bg="#1a1a2e",
        )
        header.pack(pady=(8, 2))

        self._status_label = tk.Label(
            self._root, text="Idle", font=("Helvetica", 11),
            fg="#eaeaea", bg="#1a1a2e",
        )
        self._status_label.pack()

        stats_frame = tk.Frame(self._root, bg="#1a1a2e")
        stats_frame.pack(pady=(6, 4), padx=10, fill="x")

        self._round_label = self._stat_row(stats_frame, "Round:", "—", 0)
        self._casts_label = self._stat_row(stats_frame, "Casts:", "0", 1)
        self._fish_label = self._stat_row(stats_frame, "Fish:", "0", 2)

        self._visible = True

    def _stat_row(self, parent: tk.Frame, label_text: str, value: str, row: int) -> tk.Label:
        tk.Label(
            parent, text=label_text, font=("Helvetica", 10),
            fg="#a0a0a0", bg="#1a1a2e", anchor="w",
        ).grid(row=row, column=0, sticky="w")
        val = tk.Label(
            parent, text=value, font=("Helvetica", 10, "bold"),
            fg="#ffffff", bg="#1a1a2e", anchor="e",
        )
        val.grid(row=row, column=1, sticky="e", padx=(10, 0))
        parent.columnconfigure(1, weight=1)
        return val

    def _start_move(self, event: tk.Event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_move(self, event: tk.Event) -> None:
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def update_stats(self, stats: FishingStats) -> None:
        if not self._visible:
            return
        try:
            self._round_label.config(text=f"{stats.current_round}/{stats.total_rounds}")
            self._casts_label.config(text=f"{stats.session_casts}  (round: {stats.cast_count})")
            self._fish_label.config(text=f"{stats.session_fish}  (round: {stats.fish_caught})")
        except tk.TclError:
            pass

    def update_status(self, msg: str) -> None:
        if not self._visible:
            return
        try:
            self._status_label.config(text=msg)
        except tk.TclError:
            pass

    def show(self) -> None:
        self._visible = True
        self._root.deiconify()

    def hide(self) -> None:
        self._visible = False
        self._root.withdraw()

    def destroy(self) -> None:
        self._visible = False
        try:
            self._root.destroy()
        except tk.TclError:
            pass
