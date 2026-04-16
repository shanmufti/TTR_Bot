"""Plant sequence: multi-step flower planting extracted from GardenBot."""

import threading
import time
from collections.abc import Callable

from ttr_bot.config import settings
from ttr_bot.core import input_controller as inp
from ttr_bot.core.window_manager import WindowInfo, find_ttr_window
from ttr_bot.gardening.flowers import BEAN_CHAR_TO_TEMPLATE
from ttr_bot.gardening.garden_ui_helpers import find_and_click
from ttr_bot.utils.logger import log


def execute_plant(
    flower_name: str,
    bean_sequence: str,
    stop_event: threading.Event,
    status_fn: Callable[[str], None] | None = None,
    water_fn: Callable[[int], bool] | None = None,
) -> bool:
    """Full plant flow: click plant button, select beans, confirm, and water."""
    plant_t0 = time.monotonic()
    win = find_ttr_window()
    if win is None:
        if status_fn:
            status_fn("Window not found")
        return False

    if not click_plant_button(win, stop_event, status_fn=status_fn):
        return False
    if not select_beans(bean_sequence, win, stop_event, status_fn=status_fn):
        return False
    if not confirm_plant(
        flower_name, stop_event, status_fn=status_fn, water_fn=water_fn
    ):
        return False

    log.info("[Timing] execute_plant total=%.0fms", (time.monotonic() - plant_t0) * 1000)
    log.info("Planted %s successfully", flower_name)
    return True


def click_plant_button(
    win: WindowInfo,
    stop_event: threading.Event,
    *,
    status_fn: Callable[[str], None] | None = None,
) -> bool:
    """Click the 'Plant Flower' button and wait for the dialog."""
    t0 = time.monotonic()
    if not find_and_click("plant_flower_button", win=win, stop_event=stop_event):
        if status_fn:
            status_fn("Plant Flower button not found")
        return False
    log.info("[Timing] plant_btn_click=%.0fms", (time.monotonic() - t0) * 1000)
    time.sleep(settings.GARDEN_POST_CONFIRM_DELAY_S)
    return True


def select_beans(
    bean_sequence: str,
    win: WindowInfo,
    stop_event: threading.Event,
    *,
    status_fn: Callable[[str], None] | None = None,
) -> bool:
    """Click each jellybean in the recipe, caching positions for repeats."""
    beans_t0 = time.monotonic()
    bean_positions: dict[str, tuple[int, int]] = {}

    for i, bean_char in enumerate(bean_sequence):
        if stop_event.is_set():
            return False
        template_name = BEAN_CHAR_TO_TEMPLATE.get(bean_char)
        if template_name is None:
            log.warning("Unknown bean character: %r", bean_char)
            return False

        t0 = time.monotonic()

        if template_name in bean_positions:
            pos = bean_positions[template_name]
            inp.ensure_focused()
            time.sleep(0.05)
            inp.click(pos[0], pos[1], window=win)
            log.info(
                "  Bean %d/%d: %s at (%d,%d) [repeat] %.0fms",
                i + 1,
                len(bean_sequence),
                template_name,
                pos[0],
                pos[1],
                (time.monotonic() - t0) * 1000,
            )
        else:
            pos = find_and_click(template_name, win=win, stop_event=stop_event)
            if pos is None:
                if status_fn:
                    status_fn(f"Jellybean button not found: {bean_char}")
                return False
            bean_positions[template_name] = pos
            log.info(
                "  Bean %d/%d: %s [found+clicked] %.0fms",
                i + 1,
                len(bean_sequence),
                template_name,
                (time.monotonic() - t0) * 1000,
            )

        time.sleep(settings.GARDEN_POST_BEAN_DELAY_S)

    log.info(
        "[Timing] all_beans=%.0fms (%d beans)",
        (time.monotonic() - beans_t0) * 1000,
        len(bean_sequence),
    )
    return True


def confirm_plant(
    flower_name: str,
    stop_event: threading.Event,
    *,
    status_fn: Callable[[str], None] | None = None,
    water_fn: Callable[[int], bool] | None = None,
) -> bool:
    """Confirm the plant, dismiss the OK dialog, and water if configured."""
    t0 = time.monotonic()
    if not find_and_click("blue_plant_button", stop_event=stop_event):
        if status_fn:
            status_fn("Plant confirmation button not found")
        return False
    log.info("[Timing] plant_confirm_click=%.0fms", (time.monotonic() - t0) * 1000)
    time.sleep(settings.GARDEN_POST_PLANT_DELAY_S)

    t0 = time.monotonic()
    ok_found = find_and_click("ok_button", timeout=8.0, stop_event=stop_event)
    ok_ms = (time.monotonic() - t0) * 1000
    log.info("[Timing] ok_btn_%s=%.0fms", "click" if ok_found else "timeout", ok_ms)
    time.sleep(settings.GARDEN_POST_CONFIRM_DELAY_S)

    if settings.GARDEN_WATERS_AFTER_PLANT > 0 and water_fn is not None:
        if status_fn:
            status_fn(f"Watering new {flower_name}…")
        t0 = time.monotonic()
        if not water_fn(settings.GARDEN_WATERS_AFTER_PLANT):
            if status_fn:
                status_fn("Watering failed after planting — game state may have changed")
            return False
        log.info("[Timing] water_after_plant=%.0fms", (time.monotonic() - t0) * 1000)

    return True
