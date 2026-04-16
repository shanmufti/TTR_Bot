"""Debug annotation helpers for the fishing loop.

Extracted from FishingBot so the main bot file stays focused on logic.
"""

from ttr_bot.core.screen_capture import capture_window
from ttr_bot.core.window_manager import WindowInfo
from ttr_bot.utils import debug_frames as dbg
from ttr_bot.vision.pond_detector import PondArea


def save_shadow_debug(frame, btn, pond: PondArea, candidates, shadow) -> None:
    """Save an annotated debug frame showing shadow candidates and cast target."""
    margin_bot = pond.height * 40 // 100
    margin_top = pond.height * 10 // 100
    margin_x = pond.width * 10 // 100
    inner_y1 = pond.y + margin_top
    inner_y2 = pond.y + pond.height - margin_bot
    inner_x1 = pond.x + margin_x
    inner_x2 = pond.x + pond.width - margin_x

    anns: list[dict] = [
        {
            "type": "rect",
            "pt1": (pond.x, pond.y),
            "pt2": (pond.x + pond.width, pond.y + pond.height),
            "color": (100, 100, 100),
            "thickness": 1,
        },
        {
            "type": "rect",
            "pt1": (inner_x1, inner_y1),
            "pt2": (inner_x2, inner_y2),
            "color": (0, 200, 200),
            "thickness": 2,
        },
    ]
    for c in candidates:
        clr = (0, 255, 255) if c.has_bubbles else (0, 165, 255)
        anns.append(
            {
                "type": "circle",
                "center": (c.cx, c.cy),
                "radius": 18,
                "color": clr,
                "thickness": 2,
            }
        )
        anns.append(
            {
                "type": "text",
                "pos": (c.cx + 20, c.cy - 6),
                "text": f"s={c.score:.2f} {'B' if c.has_bubbles else ''}",
                "color": clr,
                "thickness": 2,
            }
        )
    if shadow is not None:
        anns.append(
            {
                "type": "circle",
                "center": shadow,
                "radius": 24,
                "color": (0, 255, 0),
                "thickness": 4,
            }
        )
        anns.append(
            {
                "type": "line",
                "pt1": (btn.x, btn.y),
                "pt2": shadow,
                "color": (0, 255, 0),
                "thickness": 2,
            }
        )
    anns.append(
        {
            "type": "circle",
            "center": (btn.x, btn.y),
            "radius": 14,
            "color": (0, 0, 255),
            "thickness": 3,
        }
    )
    dbg.save(frame, "cast_target" if shadow else "no_shadow", annotations=anns)


def save_bite_debug(win: WindowInfo, bite_result: str, cast_count: int) -> None:
    """Save a debug frame capturing the bite outcome."""
    bite_frame = capture_window(win)
    if bite_frame is not None:
        dbg.save(
            bite_frame,
            f"bite_{bite_result}",
            annotations=[
                {
                    "type": "text",
                    "pos": (20, 40),
                    "text": f"result={bite_result}  cast#{cast_count}",
                    "color": (0, 255, 0),
                    "thickness": 2,
                },
            ],
        )
