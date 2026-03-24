"""Garden map data model and SIFT-based localization.

Loads a garden_map.json produced by demo_processor and provides real-time
localization by matching live frames against stored SIFT references.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import NamedTuple

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.utils.logger import log

FLANN_INDEX_KDTREE = 1
_FLANN_PARAMS = {"algorithm": FLANN_INDEX_KDTREE, "trees": 5}
_SEARCH_PARAMS = {"checks": 50}


# ---------------------------------------------------------------------------
# Garden map data model
# ---------------------------------------------------------------------------


@dataclass
class MapNode:
    id: str
    node_type: str  # "bed" or "waypoint"
    map_x: int
    map_y: int
    reference_image_path: str = ""
    sift_file_path: str = ""
    sift_keypoints: int = 0
    demo_segment_to_next: str | None = None
    descriptors: np.ndarray | None = None
    keypoints: np.ndarray | None = None


class GardenMap:
    """In-memory representation of a processed garden map."""

    def __init__(self) -> None:
        self.nodes: list[MapNode] = []
        self.bed_nodes: list[MapNode] = []
        self.waypoint_nodes: list[MapNode] = []
        self.route_order: list[int] = []
        self.camera_tab_count: int = 2
        self._base_dir: str = ""

    @classmethod
    def load(cls, map_path: str) -> GardenMap:
        """Load a garden map from JSON and pre-load SIFT descriptors."""
        with open(map_path) as f:
            data = json.load(f)

        gmap = cls()
        gmap._base_dir = os.path.dirname(map_path)
        gmap.camera_tab_count = data.get("camera_tab_count", 2)
        gmap.route_order = data.get("route_order", [])

        for nd in data.get("nodes", []):
            node = MapNode(
                id=nd["id"],
                node_type=nd.get("type", "bed"),
                map_x=nd.get("map_x", 0),
                map_y=nd.get("map_y", 0),
                reference_image_path=os.path.join(gmap._base_dir,
                                                  nd.get("reference_image", "")),
                sift_file_path=os.path.join(gmap._base_dir,
                                            nd.get("sift_file", "")),
                sift_keypoints=nd.get("sift_keypoints", 0),
                demo_segment_to_next=nd.get("demo_segment_to_next"),
            )
            gmap._load_sift(node)
            gmap.nodes.append(node)

            if node.node_type == "bed":
                gmap.bed_nodes.append(node)
            else:
                gmap.waypoint_nodes.append(node)

        log.info("GardenMap loaded: %d beds, %d waypoints from %s",
                 len(gmap.bed_nodes), len(gmap.waypoint_nodes), map_path)
        return gmap

    def get_bed(self, bed_id: str) -> MapNode | None:
        for node in self.bed_nodes:
            if node.id == bed_id:
                return node
        return None

    def get_bed_by_number(self, bed_num: int) -> MapNode | None:
        return self.get_bed(f"bed_{bed_num}")

    def get_demo_segment(self, from_bed: str, to_bed: str) -> dict | None:
        """Load demo keyboard segment for a bed-to-bed transition."""
        node = self.get_bed(from_bed)
        if node is None or node.demo_segment_to_next is None:
            return None

        seg_path = os.path.join(self._base_dir, node.demo_segment_to_next)
        log.debug("Loading segment %s → %s from %s", from_bed, to_bed, seg_path)
        if not os.path.isfile(seg_path):
            log.warning("Demo segment not found: %s", seg_path)
            return None

        with open(seg_path) as f:
            return json.load(f)

    def _load_sift(self, node: MapNode) -> None:
        if not node.sift_file_path or not os.path.isfile(node.sift_file_path):
            return
        try:
            data = np.load(node.sift_file_path)
            node.descriptors = data["descriptors"]
            node.keypoints = data["keypoints"]
        except Exception as exc:
            log.warning("Failed to load SIFT for %s: %s", node.id, exc)


# ---------------------------------------------------------------------------
# Localization result
# ---------------------------------------------------------------------------


class LocalizationResult(NamedTuple):
    map_x: float
    map_y: float
    confidence: float
    best_node_id: str
    match_count: int
    latency_ms: float
    second_best_id: str = ""
    second_best_conf: float = 0.0


# ---------------------------------------------------------------------------
# SIFT localizer
# ---------------------------------------------------------------------------


class GardenLocalizer:
    """Real-time SIFT localization against a garden map."""

    def __init__(self, garden_map: GardenMap) -> None:
        self._map = garden_map
        self._sift = cv2.SIFT_create(nfeatures=settings.SIFT_NFEATURES)
        self._flann = cv2.FlannBasedMatcher(_FLANN_PARAMS, _SEARCH_PARAMS)
        self._nodes_with_desc = [
            n for n in garden_map.nodes if n.descriptors is not None
        ]
        log.info("GardenLocalizer: %d nodes with SIFT descriptors",
                 len(self._nodes_with_desc))

    def localize(self, frame_bgr: np.ndarray) -> LocalizationResult | None:
        """Match a live frame against all reference nodes.

        Returns the best match with interpolated map position,
        or None if no confident match is found.
        """
        t0 = time.monotonic()

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        kps, des = self._sift.detectAndCompute(gray, None)
        if des is None or len(kps) < 5:
            return None

        scores: list[tuple[MapNode, int, float]] = []

        for node in self._nodes_with_desc:
            if node.descriptors is None:
                continue

            good_matches = self._match_descriptors(des, node.descriptors)
            if len(good_matches) < settings.LOCALIZATION_MIN_MATCHES:
                continue

            max_possible = min(len(des), len(node.descriptors))
            confidence = len(good_matches) / max(max_possible, 1)
            scores.append((node, len(good_matches), confidence))

        if not scores:
            return None

        scores.sort(key=lambda x: x[1], reverse=True)

        best_node, best_count, best_conf = scores[0]
        second_id = ""
        second_conf = 0.0
        if len(scores) > 1:
            second_id = scores[1][0].id
            second_conf = scores[1][2]

        map_x, map_y = self._interpolate_position(scores[:3])

        latency = (time.monotonic() - t0) * 1000

        return LocalizationResult(
            map_x=map_x,
            map_y=map_y,
            confidence=best_conf,
            best_node_id=best_node.id,
            match_count=best_count,
            latency_ms=round(latency, 1),
            second_best_id=second_id,
            second_best_conf=round(second_conf, 3),
        )

    def _match_descriptors(
        self, query_des: np.ndarray, ref_des: np.ndarray,
    ) -> list:
        """FLANN match with Lowe's ratio test."""
        if len(ref_des) < 2 or len(query_des) < 2:
            return []

        try:
            matches = self._flann.knnMatch(query_des, ref_des, k=2)
        except cv2.error:
            return []

        good = []
        for pair in matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < settings.SIFT_MATCH_RATIO * n.distance:
                    good.append(m)
        return good

    def _interpolate_position(
        self, top_scores: list[tuple[MapNode, int, float]],
    ) -> tuple[float, float]:
        """Weighted-average position from the top N matches."""
        total_weight = 0.0
        wx = 0.0
        wy = 0.0

        for node, count, conf in top_scores:
            weight = count * conf
            wx += node.map_x * weight
            wy += node.map_y * weight
            total_weight += weight

        if total_weight < 1e-9:
            return (top_scores[0][0].map_x, top_scores[0][0].map_y)

        return (wx / total_weight, wy / total_weight)


# ---------------------------------------------------------------------------
# Heading estimator
# ---------------------------------------------------------------------------


class HeadingEstimator:
    """Estimates the character's facing direction from consecutive positions.

    Primary method: atan2 of position deltas with rolling average.
    Fallback: holds the last known heading when stationary.
    """

    def __init__(self, smoothing: int = settings.NAV_HEADING_SMOOTHING) -> None:
        self._smoothing = smoothing
        self._history: list[tuple[float, float]] = []
        self._heading_history: list[float] = []
        self._heading: float | None = None

    @property
    def heading(self) -> float | None:
        """Current heading in degrees (0=right, 90=down, etc.)."""
        return self._heading

    def update(self, result: LocalizationResult) -> float | None:
        """Update heading with a new localization result.

        Returns the smoothed heading in degrees, or None if not enough data.
        """
        pos = (result.map_x, result.map_y)
        self._history.append(pos)

        if len(self._history) < 2:
            return self._heading

        prev = self._history[-2]
        dx = pos[0] - prev[0]
        dy = pos[1] - prev[1]
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < 2.0:
            return self._heading

        import math
        raw_heading = math.degrees(math.atan2(dy, dx))

        self._heading_history.append(raw_heading)
        if len(self._heading_history) > self._smoothing:
            self._heading_history = self._heading_history[-self._smoothing:]

        self._heading = self._smooth_heading()

        if len(self._history) > 20:
            self._history = self._history[-20:]

        return self._heading

    def reset(self) -> None:
        self._history.clear()
        self._heading_history.clear()
        self._heading = None

    def _smooth_heading(self) -> float:
        """Circular mean of heading history."""
        import math
        sin_sum = sum(math.sin(math.radians(h)) for h in self._heading_history)
        cos_sum = sum(math.cos(math.radians(h)) for h in self._heading_history)
        return math.degrees(math.atan2(sin_sum, cos_sum))
