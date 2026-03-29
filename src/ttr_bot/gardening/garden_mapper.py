"""Garden Mapper: heading-aware dead-reckoning 2D map.

TTR movement model (fixed camera behind character):
- **Up** = walk forward in the direction the character faces
- **Left** = turn left in place (pure rotation, no displacement)
- **Right** = turn right in place (pure rotation, no displacement)
- **Down** = walk backward (no turning)

The mapper tracks (x, y, heading).  Left/Right only change heading;
Up/Down change position along the current heading vector.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log


@dataclass
class BedMarker:
    """A discovered flower-bed position on the map."""
    x: float
    y: float
    bed_type: str
    index: int
    visited: bool = True


class GardenMapper:
    """Heading-aware 2D dead-reckoning map of the estate garden."""

    def __init__(self) -> None:
        self._x: float = 0.0
        self._y: float = 0.0
        self._heading: float = 0.0  # radians; 0 = initial facing
        self._path: list[tuple[float, float]] = [(0.0, 0.0)]
        self._beds: list[BedMarker] = []
        self._explored: set[tuple[int, int]] = {(0, 0)}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def position(self) -> tuple[float, float]:
        return (self._x, self._y)

    @property
    def heading(self) -> float:
        return self._heading

    @property
    def beds(self) -> list[BedMarker]:
        return list(self._beds)

    @property
    def bed_count(self) -> int:
        return len(self._beds)

    # ------------------------------------------------------------------
    # Position tracking
    # ------------------------------------------------------------------

    def update(self, keys: list[str], duration: float) -> None:
        """Advance estimated position after a movement burst.

        Left/Right turn the character in place (pure rotation, no
        displacement).  Up walks forward along the current heading;
        Down walks backward.
        """
        turn_rate = math.radians(settings.SWEEP_TURN_RATE_DEG_S)
        speed = settings.SWEEP_WALK_SPEED

        if "left" in keys:
            self._heading -= turn_rate * duration
        if "right" in keys:
            self._heading += turn_rate * duration

        if "up" in keys:
            self._x += math.cos(self._heading) * speed * duration
            self._y += math.sin(self._heading) * speed * duration
        elif "down" in keys:
            self._x -= math.cos(self._heading) * speed * duration
            self._y -= math.sin(self._heading) * speed * duration

        self._path.append((self._x, self._y))
        self._explored.add((round(self._x), round(self._y)))

    def mark_bed(self, bed_type: str) -> BedMarker:
        """Record current position as a flower bed.

        De-duplicates: if a bed already exists within a small radius,
        the existing marker is returned instead.
        """
        for existing in self._beds:
            if math.hypot(existing.x - self._x, existing.y - self._y) < 0.8:
                log.info(
                    "Mapper: bed at (%.1f,%.1f) matches existing #%d",
                    self._x, self._y, existing.index,
                )
                existing.visited = True
                return existing

        idx = len(self._beds) + 1
        bed = BedMarker(x=self._x, y=self._y, bed_type=bed_type, index=idx)
        self._beds.append(bed)
        log.info(
            "Mapper: new bed #%d at (%.1f,%.1f) [%s]",
            idx, self._x, self._y, bed_type,
        )
        return bed

    # ------------------------------------------------------------------
    # Path planning
    # ------------------------------------------------------------------

    def direction_to(
        self, target_x: float, target_y: float,
    ) -> tuple[list[str], float]:
        """Compute the next movement action to reach *(target_x, target_y)*.

        Returns a ``(keys, duration)`` pair.  If the character isn't
        facing the target, a turn action is returned first.  Once
        roughly aligned, a forward walk is returned.
        """
        dx = target_x - self._x
        dy = target_y - self._y
        dist = math.hypot(dx, dy)
        if dist < 0.15:
            return [], 0.0

        target_angle = math.atan2(dy, dx)
        diff = _normalize_angle(target_angle - self._heading)

        if abs(diff) > 0.3:
            key = "right" if diff > 0 else "left"
            turn_rate = math.radians(settings.SWEEP_TURN_RATE_DEG_S)
            dur = abs(diff) / turn_rate if turn_rate > 0 else 0.5
            return [key], dur

        return ["up"], dist / settings.SWEEP_WALK_SPEED

    def nearest_unvisited_bed(
        self, visited_indices: set[int] | None = None,
    ) -> BedMarker | None:
        visited = visited_indices or set()
        best: BedMarker | None = None
        best_dist = float("inf")
        for bed in self._beds:
            if bed.index in visited:
                continue
            d = math.hypot(bed.x - self._x, bed.y - self._y)
            if d < best_dist:
                best_dist = d
                best = bed
        return best

    def plan_route(
        self, visited_indices: set[int] | None = None,
    ) -> list[BedMarker]:
        """Greedy nearest-neighbor ordering of unvisited beds."""
        visited = set(visited_indices or [])
        route: list[BedMarker] = []
        cx, cy = self._x, self._y

        remaining = [b for b in self._beds if b.index not in visited]
        while remaining:
            ref_x, ref_y = cx, cy
            remaining.sort(
                key=lambda b, rx=ref_x, ry=ref_y: math.hypot(b.x - rx, b.y - ry),
            )
            nxt = remaining.pop(0)
            route.append(nxt)
            cx, cy = nxt.x, nxt.y

        return route

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, size: int = 800) -> np.ndarray:
        all_pts = list(self._path) + [(b.x, b.y) for b in self._beds]
        if len(all_pts) < 2:
            img = np.full((size, size, 3), 40, dtype=np.uint8)
            cv2.putText(
                img, "No data yet", (size // 4, size // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (150, 150, 150), 2,
            )
            return img

        min_x = min(p[0] for p in all_pts) - 1.5
        max_x = max(p[0] for p in all_pts) + 1.5
        min_y = min(p[1] for p in all_pts) - 1.5
        max_y = max(p[1] for p in all_pts) + 1.5
        range_x = max(max_x - min_x, 0.1)
        range_y = max(max_y - min_y, 0.1)

        pad = 60
        usable = size - 2 * pad
        scale = min(usable / range_x, usable / range_y)

        def px(x: float, y: float) -> tuple[int, int]:
            return int(pad + (x - min_x) * scale), int(pad + (y - min_y) * scale)

        img = np.full((size, size, 3), 40, dtype=np.uint8)

        self._draw_grid(img, min_x, max_x, min_y, max_y, pad, size, px)
        self._draw_path(img, px)
        self._draw_beds(img, px)
        self._draw_markers(img, px, scale)
        self._draw_legend(img, size)
        self._draw_title(img, pad)

        return img

    def _draw_grid(self, img, min_x, max_x, min_y, max_y, pad, size, px):
        step = max(1.0, round((max_x - min_x + max_y - min_y) / 2 / 10))
        gx = math.floor(min_x)
        while gx <= math.ceil(max_x):
            x_px, _ = px(gx, 0)
            cv2.line(img, (x_px, pad), (x_px, size - pad), (55, 55, 55), 1)
            gx += step
        gy = math.floor(min_y)
        while gy <= math.ceil(max_y):
            _, y_px = px(0, gy)
            cv2.line(img, (pad, y_px), (size - pad, y_px), (55, 55, 55), 1)
            gy += step

    def _draw_path(self, img, px):
        for i in range(1, len(self._path)):
            p1 = px(*self._path[i - 1])
            p2 = px(*self._path[i])
            cv2.line(img, p1, p2, (76, 175, 80), 2)

    def _draw_beds(self, img, px):
        colors = {
            "pick_flower_button": (60, 60, 230),
            "plant_flower_button": (60, 200, 60),
            "watering_can_button": (200, 160, 40),
            "remove_button": (140, 80, 200),
        }
        for bed in self._beds:
            pt = px(bed.x, bed.y)
            col = colors.get(bed.bed_type, (180, 180, 180))
            cv2.circle(img, pt, 14, col, -1)
            cv2.circle(img, pt, 14, (255, 255, 255), 1)
            label = str(bed.index)
            (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.putText(
                img, label, (pt[0] - tw // 2, pt[1] + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
            )

    def _draw_markers(self, img, px, scale):
        # Start star
        start = px(*self._path[0])
        cv2.drawMarker(img, start, (0, 255, 255), cv2.MARKER_STAR, 20, 2)

        # Current position + heading arrow
        cur = px(self._x, self._y)
        cv2.circle(img, cur, 9, (205, 188, 0), -1)
        cv2.circle(img, cur, 9, (255, 255, 255), 1)

        arrow_len = max(18, int(scale * 0.6))
        ax = int(cur[0] + arrow_len * math.cos(self._heading))
        ay = int(cur[1] + arrow_len * math.sin(self._heading))
        cv2.arrowedLine(img, cur, (ax, ay), (255, 255, 255), 2, tipLength=0.35)

    @staticmethod
    def _draw_legend(img, size):
        lx = size - 190
        items = [
            ((0, 255, 255), "Start"),
            ((76, 175, 80), "Path"),
            ((205, 188, 0), "Current pos"),
            ((255, 255, 255), "Heading"),
            ((60, 60, 230), "Bed (pick)"),
            ((60, 200, 60), "Bed (plant)"),
            ((200, 160, 40), "Bed (water)"),
            ((140, 80, 200), "Bed (growing)"),
        ]
        for i, (col, text) in enumerate(items):
            y = 20 + i * 22
            cv2.circle(img, (lx, y + 6), 6, col, -1)
            cv2.putText(
                img, text, (lx + 14, y + 11),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA,
            )

    def _draw_title(self, img, pad):
        cv2.putText(
            img, "Garden Map", (pad, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2, cv2.LINE_AA,
        )
        hdeg = math.degrees(self._heading) % 360
        cv2.putText(
            img,
            f"{len(self._beds)} beds  |  {len(self._path)} pts  |  "
            f"heading {hdeg:.0f} deg",
            (pad, 52),
            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1, cv2.LINE_AA,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        data = {
            "timestamp": datetime.now().isoformat(),
            "position": [self._x, self._y],
            "heading": self._heading,
            "beds": [
                {"x": b.x, "y": b.y, "type": b.bed_type, "index": b.index}
                for b in self._beds
            ],
            "path": self._path,
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        log.info(
            "Mapper: saved %s (%d beds, %d pts)", path,
            len(self._beds), len(self._path),
        )

    @classmethod
    def load(cls, path: str) -> GardenMapper:
        with open(path) as f:
            data = json.load(f)

        mapper = cls()
        pos = data.get("position", [0, 0])
        mapper._x, mapper._y = float(pos[0]), float(pos[1])
        mapper._heading = float(data.get("heading", 0.0))
        mapper._path = [
            (float(p[0]), float(p[1])) for p in data.get("path", [(0, 0)])
        ]
        for bd in data.get("beds", []):
            mapper._beds.append(BedMarker(
                x=float(bd["x"]),
                y=float(bd["y"]),
                bed_type=bd["type"],
                index=int(bd["index"]),
                visited=False,
            ))
        for pt_x, pt_y in mapper._path:
            mapper._explored.add((round(pt_x), round(pt_y)))

        log.info(
            "Mapper: loaded %s (%d beds, %d pts)", path,
            len(mapper._beds), len(mapper._path),
        )
        return mapper

    def save_image(self, path: str, size: int = 800) -> None:
        img = self.render(size)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        cv2.imwrite(path, img)
        log.info("Mapper: image saved to %s", path)


def _normalize_angle(a: float) -> float:
    """Normalize angle to [-pi, pi]."""
    a = a % (2 * math.pi)
    if a > math.pi:
        a -= 2 * math.pi
    return a
