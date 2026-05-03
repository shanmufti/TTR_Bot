"""Garden Watcher: passive screen poller for hands-free gardening.

The player navigates manually.  This module continuously polls the screen
for gardening UI buttons (Pick / Plant / Water / Remove).  When detected
it automatically performs the full gardening sequence:

  Pick (if grown) → Plant new flower → Water once

After each action the watcher resumes polling so the player can walk to
the next bed.
"""

import contextlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2

from ttr_bot.config import settings
from ttr_bot.core.screen_capture import grab_frame
from ttr_bot.gardening.bed_ui import BedState, classify_bed_state
from ttr_bot.gardening.gardening_bot import GardenBot
from ttr_bot.utils import debug_frames as dbg
from ttr_bot.utils.logger import log

_DEBUG_DIR = os.path.join(settings.DEBUG_OUTPUT_BASE_DIR, "watcher")

_POLL_INTERVAL_S = 0.3
_HEARTBEAT_POLLS = 30  # log a heartbeat every ~9 s of silence
_UNKNOWN_STREAK_LIMIT = 3  # unknown frames before declaring bed UI gone


@dataclass(slots=True)
class WatcherResult:
    """Summary returned after a garden-watcher session ends."""

    beds_actioned: int = 0
    beds_picked: int = 0
    beds_planted: int = 0
    total_time_s: float = 0.0


class GardenWatcher:
    """Passive screen watcher that auto-gardens when bed UI appears."""

    def __init__(
        self,
        garden_bot: GardenBot,
        stop_event: threading.Event,
    ) -> None:
        self._bot = garden_bot
        self._stop_event = stop_event
        self.on_status: Callable[[str], None] | None = None
        self._debug_seq = 0
        os.makedirs(_DEBUG_DIR, exist_ok=True)

    def watch(
        self,
        flower_name: str,
        bean_sequence: str,
    ) -> WatcherResult:
        result = WatcherResult()
        t0 = time.monotonic()

        self._debug_seq = 0
        dbg.clear_pngs(_DEBUG_DIR)

        self._status(f"Watching — walk to beds, I'll handle the rest ({flower_name})")

        if not self._bot.ensure_calibrated():
            self._status("Calibration failed")
            return result

        self._poll_loop(flower_name, bean_sequence, result)

        result.total_time_s = time.monotonic() - t0
        self._print_summary(result)
        return result

    def _poll_loop(
        self,
        flower_name: str,
        bean_sequence: str,
        result: WatcherResult,
    ) -> None:
        polls_since_log = 0
        t_between = time.monotonic()
        while not self._stop_event.is_set():
            t_poll = time.monotonic()
            frame = self._grab_frame()
            grab_ms = getattr(self, "_last_grab_ms", 0)

            if frame is None:
                polls_since_log += 1
                if polls_since_log >= _HEARTBEAT_POLLS:
                    log.info(
                        "[Watcher] polling… (no window) [%d polls, %.1fs since last bed]",
                        polls_since_log,
                        time.monotonic() - t_between,
                    )
                    polls_since_log = 0
                time.sleep(_POLL_INTERVAL_S)
                continue

            t_cls = time.monotonic()
            state = classify_bed_state(frame)
            cls_ms = (time.monotonic() - t_cls) * 1000
            poll_ms = (time.monotonic() - t_poll) * 1000

            if state not in (BedState.PICK, BedState.PLANT):
                polls_since_log += 1
                if polls_since_log >= _HEARTBEAT_POLLS:
                    log.info(
                        "[Watcher] polling… state=%s [%d polls, grab=%.0fms "
                        "classify=%.0fms poll=%.0fms, %.1fs since last bed]",
                        state,
                        polls_since_log,
                        grab_ms,
                        cls_ms,
                        poll_ms,
                        time.monotonic() - t_between,
                    )
                    polls_since_log = 0
                time.sleep(_POLL_INTERVAL_S)
                continue

            between_ms = (time.monotonic() - t_between) * 1000
            polls_since_log = 0
            result.beds_actioned += 1
            bed_num = result.beds_actioned

            log.info("[Timing] bed_transition=%.0fms (polls until detection)", between_ms)
            log.info("[Timing] classify=%.0fms grab=%.0fms → %s", cls_ms, grab_ms, state)
            self._debug_save(frame, state, bed_num)
            self._status(f"Bed #{bed_num}: {state}")

            t0 = time.monotonic()
            self._execute(state, bed_num, flower_name, bean_sequence, result, frame)
            log.info("[Timing] bed_action_total=%.0fms", (time.monotonic() - t0) * 1000)
            self._status("Done — walk to next bed…")

            self._wait_for_new_bed()
            t_between = time.monotonic()

    def _wait_for_new_bed(self) -> None:
        """After acting on a bed, wait until the player reaches a new one.

        The sidebar stays visible between beds — only the buttons change.
        After plant+water, the current bed shows ``pick`` (for the flower we
        just planted).  We wait until:
          - ``plant`` appears (new empty bed), or
          - ``unknown`` persists for 3 frames (player walked away / between beds)
        Either means we've moved on and can act again.
        """
        unknown_streak = 0
        t0 = time.monotonic()
        while not self._stop_event.is_set():
            frame = self._grab_frame()
            if frame is None:
                unknown_streak += 1
            else:
                state = classify_bed_state(frame, log_matches=False)
                if state == BedState.PLANT:
                    log.info(
                        "[Watcher] new bed detected (plant) after %.0fms",
                        (time.monotonic() - t0) * 1000,
                    )
                    return
                if state == BedState.UNKNOWN:
                    unknown_streak += 1
                else:
                    unknown_streak = 0

            if unknown_streak >= _UNKNOWN_STREAK_LIMIT:
                log.info("[Watcher] bed UI gone after %.0fms", (time.monotonic() - t0) * 1000)
                return

            time.sleep(_POLL_INTERVAL_S)

        log.info("[Watcher] stop requested during new-bed wait")

    def _grab_frame(self):
        t0 = time.monotonic()
        frame = grab_frame()
        self._last_grab_ms = (time.monotonic() - t0) * 1000
        return frame

    def _execute(  # noqa: PLR0913 — watcher bed handler needs full context
        self,
        state: BedState,
        bed_num: int,
        flower_name: str,
        bean_sequence: str,
        result: WatcherResult,
        frame,
    ) -> None:
        if state == BedState.PICK:
            self._status(f"Bed #{bed_num}: picking → planting {flower_name} → watering")
            if self._bot.pick_flower(hint_frame=frame):
                result.beds_picked += 1
                t_gap = time.monotonic()
                time.sleep(1.0)
                log.info(
                    "[Timing] pick_to_plant_gap=%.0fms (sleep 1.0s)",
                    (time.monotonic() - t_gap) * 1000,
                )
                if self._bot.plant_flower_no_pick(flower_name, bean_sequence):
                    result.beds_planted += 1
        elif state == BedState.PLANT:
            self._status(f"Bed #{bed_num}: planting {flower_name} → watering")
            if self._bot.plant_flower_no_pick(flower_name, bean_sequence):
                result.beds_planted += 1

    def _debug_save(self, frame, state: BedState, bed_num: int) -> None:
        t0 = time.monotonic()
        self._debug_seq += 1
        path = os.path.join(_DEBUG_DIR, f"{self._debug_seq:03d}_bed{bed_num}_{state.value}.png")
        debug_frame = frame.copy()
        cv2.putText(
            debug_frame,
            f"BED #{bed_num}: {state.value}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 255, 255),
            3,
        )
        cv2.imwrite(path, debug_frame)
        log.info("[Timing] debug_save=%.0fms", (time.monotonic() - t0) * 1000)

    def _status(self, msg: str) -> None:
        log.info("[Watcher] %s", msg)
        if self.on_status:
            with contextlib.suppress(Exception):
                self.on_status(msg)

    def _print_summary(self, r: WatcherResult) -> None:
        msg = (
            f"\n{'═' * 44}\n"
            f" WATCHER COMPLETE\n"
            f"{'═' * 44}\n"
            f" Beds actioned:      {r.beds_actioned}\n"
            f" Picked:             {r.beds_picked}\n"
            f" Planted:            {r.beds_planted}\n"
            f" Time:               {int(r.total_time_s) // 60}m "
            f"{int(r.total_time_s) % 60:02d}s\n"
            f"{'═' * 44}"
        )
        self._status(msg)
