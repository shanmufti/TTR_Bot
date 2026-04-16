"""Tkinter-aware logging handler that streams records into a ScrolledText widget."""

import contextlib
import logging
import tkinter as tk
from tkinter import scrolledtext


class TkLogHandler(logging.Handler):
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
