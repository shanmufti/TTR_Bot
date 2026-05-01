"""Modal dialog for manually picking a golf course when OCR fails."""

import threading
import tkinter as tk
from tkinter import ttk

from ttr_bot.ui.theme import ACCENT, BG, FG


def pick_course_blocking(
    root: tk.Tk,
    options: list[str],
    *,
    abort_event: threading.Event | None = None,
) -> str | None:
    """Show a modal course-picker dialog.  Blocks the calling thread until the
    user selects a course or cancels.  Must be called from a *worker* thread —
    the actual dialog is scheduled on the Tk main loop via ``root.after``.

    If ``abort_event`` is set (e.g. app is quitting), returns ``None`` promptly
    so the worker thread can observe :meth:`~ttr_bot.core.bot_base.BotBase.stop`.
    """
    result: list[str | None] = [None]
    ready = threading.Event()

    def show_dialog() -> None:
        top = tk.Toplevel(root)
        top.title("Select golf course")
        top.configure(bg=BG)
        top.transient(root)
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
        tk.Button(bf, text="Skip", command=cancel, highlightbackground=ACCENT).pack(
            side="left", padx=4
        )

    root.after(0, show_dialog)
    while not ready.is_set():
        if abort_event is not None and abort_event.is_set():
            return None
        ready.wait(timeout=0.2)
    return result[0]
