"""Shared threaded-bot lifecycle: start / stop / pause / callbacks.

All domain bots (FishingBot, GardenBot, GolfBot, CastRecorder,
RoutineRunner) inherit from :class:`BotBase` so thread management,
pause/resume, stop signaling, and status/end callbacks are consistent
everywhere.
"""

import contextlib
import threading
import time
from collections.abc import Callable

from ttr_bot.utils.logger import log


class BotBase:
    """Thread-safe bot lifecycle: start -> run -> stop, with pause and callbacks."""

    def __init__(self) -> None:
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self.on_status_update: Callable[[str], None] | None = None
        self.on_ended: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def _start_thread(self, target: Callable, *args: object) -> bool:
        """Create and start a daemon thread. Returns False if already running."""
        if self._running:
            log.warning("%s already running", type(self).__name__)
            return False
        self._stop_event.clear()
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=target, args=args, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Signal the bot to stop and wait for the thread to finish."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._running = False
        self._thread = None

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        state = "PAUSED" if self._paused else "RESUMED"
        log.info("%s %s", type(self).__name__, state)
        self._status(state)

    def _wait_if_paused(self) -> None:
        """Block while the bot is paused."""
        while self._paused and not self._stop_event.is_set():
            time.sleep(0.25)

    def _status(self, msg: str) -> None:
        """Log a message and forward to the UI callback."""
        log.info(msg)
        if self.on_status_update:
            with contextlib.suppress(Exception):
                self.on_status_update(msg)

    def _finish(self, reason: str) -> None:
        """Mark the bot as stopped and fire the ended callback."""
        self._running = False
        log.info("%s ended: %s", type(self).__name__, reason)
        if self.on_ended:
            with contextlib.suppress(Exception):
                self.on_ended(reason)
