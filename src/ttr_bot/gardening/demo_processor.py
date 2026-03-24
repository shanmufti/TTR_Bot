"""Process a recorded TTR gardening demo into a garden map.

Reads the frames and keyboard events from a demo directory, detects
bed arrivals via interaction button template matching, extracts SIFT
references per bed, and produces a garden_map.json + supporting files.

Usage:
    python -m gardening.demo_processor gardening_routines/demos/demo_XXXX/
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np

from ttr_bot.config import settings
from ttr_bot.vision import template_matcher as tm
from ttr_bot.utils.logger import log

_INTERACTION_BUTTONS = ("plant_flower_button", "pick_flower_button")

_DEBOUNCE_FRAMES = 15

_WAYPOINT_SAMPLE_RATE = 10


@dataclass
class _BedArrival:
    bed_num: int
    frame_idx: int
    timestamp: float
    reference_frame: np.ndarray | None = None
    sift_keypoints: int = 0


@dataclass
class _KeySegment:
    from_bed: int
    to_bed: int
    events: list[dict] = field(default_factory=list)
    duration: float = 0.0


class DemoProcessor:
    """Processes a demo directory into a garden map."""

    def __init__(self, demo_dir: str) -> None:
        self._demo_dir = demo_dir
        self._frames_dir = os.path.join(demo_dir, "frames")
        self._frame_timestamps: list[float] = []
        self._keyboard_events: list[dict] = []
        self._beds: list[_BedArrival] = []
        self._segments: list[_KeySegment] = []
        self._waypoints: list[tuple[int, float, int]] = []

    def process(self) -> dict:
        """Run all processing steps. Returns a summary dict."""
        self._load_metadata()

        if not self._calibrate():
            return {"error": "Calibration failed — no anchor template found in any frame"}

        self._detect_bed_arrivals()
        self._extract_sift_references()
        self._extract_keyboard_segments()
        self._sample_waypoints()
        map_data = self._build_map()
        self._save_outputs(map_data)

        summary = self._build_summary()
        self._print_summary(summary)
        return summary

    def _load_metadata(self) -> None:
        ts_path = os.path.join(self._demo_dir, "frame_timestamps.json")
        with open(ts_path) as f:
            self._frame_timestamps = json.load(f)

        kb_path = os.path.join(self._demo_dir, "keyboard.jsonl")
        self._keyboard_events = []
        if os.path.isfile(kb_path):
            with open(kb_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._keyboard_events.append(json.loads(line))

        log.info("Loaded demo: %d frames, %d keyboard events",
                 len(self._frame_timestamps), len(self._keyboard_events))

    def _calibrate(self) -> bool:
        """Run template matcher calibration on an early frame."""
        if tm._global_scale is not None:
            return True

        for idx in range(0, min(50, len(self._frame_timestamps)), 5):
            frame = self._load_frame(idx)
            if frame is None:
                continue
            scale = tm.calibrate_scale(frame)
            if scale > 0:
                log.info("Calibrated on frame %d (scale=%.2f)", idx, scale)
                return True
        return False

    def _detect_bed_arrivals(self) -> None:
        """Scan frames for interaction buttons to find bed arrival moments."""
        self._beds = []
        total = len(self._frame_timestamps)
        was_visible = False
        last_detect_idx = -_DEBOUNCE_FRAMES

        for idx in range(total):
            frame = self._load_frame(idx)
            if frame is None:
                continue

            visible = False
            for btn in _INTERACTION_BUTTONS:
                if tm.find_template(frame, btn) is not None:
                    visible = True
                    break

            if visible and not was_visible and (idx - last_detect_idx) >= _DEBOUNCE_FRAMES:
                bed_num = len(self._beds) + 1
                ref_idx = max(0, idx - 2)
                ref_frame = self._load_frame(ref_idx)

                arrival = _BedArrival(
                    bed_num=bed_num,
                    frame_idx=idx,
                    timestamp=self._frame_timestamps[idx],
                    reference_frame=ref_frame,
                )
                self._beds.append(arrival)
                last_detect_idx = idx
                log.info("Bed %d arrival at frame %d (t=%.1fs)",
                         bed_num, idx, self._frame_timestamps[idx])

            was_visible = visible

        log.info("Detected %d bed arrivals", len(self._beds))

    def _extract_sift_references(self) -> None:
        """Extract SIFT features from each bed's reference frame."""
        sift = cv2.SIFT_create(nfeatures=settings.SIFT_NFEATURES)

        for bed in self._beds:
            if bed.reference_frame is None:
                continue

            gray = cv2.cvtColor(bed.reference_frame, cv2.COLOR_BGR2GRAY)
            kps, _ = sift.detectAndCompute(gray, None)
            bed.sift_keypoints = len(kps) if kps else 0

            if bed.sift_keypoints < 50:
                self._try_alternate_frames(bed, sift)

            status = "✓" if bed.sift_keypoints >= 100 else "⚠ LOW"
            log.info("Bed %d: %d SIFT keypoints %s",
                     bed.bed_num, bed.sift_keypoints, status)

    def _try_alternate_frames(self, bed: _BedArrival, sift) -> None:
        """Try adjacent frames if the primary reference has too few SIFT keypoints."""
        for offset in [-1, 1, -3, 3]:
            alt_idx = bed.frame_idx + offset
            if not (0 <= alt_idx < len(self._frame_timestamps)):
                continue
            alt_frame = self._load_frame(alt_idx)
            if alt_frame is None:
                continue
            alt_gray = cv2.cvtColor(alt_frame, cv2.COLOR_BGR2GRAY)
            alt_kps, _ = sift.detectAndCompute(alt_gray, None)
            if alt_kps and len(alt_kps) > bed.sift_keypoints:
                bed.sift_keypoints = len(alt_kps)
                bed.reference_frame = alt_frame
                log.info("Bed %d: used alternate frame (offset %d) for better features",
                         bed.bed_num, offset)
                break

    def _extract_keyboard_segments(self) -> None:
        """Extract keyboard events between consecutive bed arrivals."""
        self._segments = []
        for i in range(len(self._beds) - 1):
            curr = self._beds[i]
            nxt = self._beds[i + 1]
            t_start = curr.timestamp
            t_end = nxt.timestamp

            events = [
                e for e in self._keyboard_events
                if t_start <= e.get("t", 0) <= t_end
            ]

            seg = _KeySegment(
                from_bed=curr.bed_num,
                to_bed=nxt.bed_num,
                events=events,
                duration=round(t_end - t_start, 2),
            )
            self._segments.append(seg)

        log.info("Extracted %d keyboard segments", len(self._segments))

    def _sample_waypoints(self) -> None:
        """Sample frames between beds as intermediate waypoints."""
        self._waypoints = []
        sift = cv2.SIFT_create(nfeatures=settings.SIFT_NFEATURES)

        for i in range(len(self._beds) - 1):
            start_idx = self._beds[i].frame_idx
            end_idx = self._beds[i + 1].frame_idx

            for idx in range(start_idx, end_idx, _WAYPOINT_SAMPLE_RATE):
                if idx == start_idx:
                    continue
                frame = self._load_frame(idx)
                if frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                kps, _ = sift.detectAndCompute(gray, None)
                kp_count = len(kps) if kps else 0
                self._waypoints.append((idx, self._frame_timestamps[idx], kp_count))

        log.info("Sampled %d waypoints between beds", len(self._waypoints))

    def _build_map(self) -> dict:
        """Build the garden map JSON data structure."""
        num_beds = len(self._beds)
        nodes = []

        for i, bed in enumerate(self._beds):
            angle = 2 * math.pi * i / max(num_beds, 1)
            radius = 200
            map_x = int(300 + radius * math.cos(angle))
            map_y = int(300 + radius * math.sin(angle))

            seg_file = None
            if i < len(self._segments):
                seg_file = f"demo_segments/bed_{bed.bed_num}_to_bed_{bed.bed_num + 1}.json"

            nodes.append({
                "id": f"bed_{bed.bed_num}",
                "type": "bed",
                "map_x": map_x,
                "map_y": map_y,
                "reference_image": f"map_images/bed_{bed.bed_num}_reference.png",
                "sift_file": f"map_images/bed_{bed.bed_num}_sift.npz",
                "sift_keypoints": bed.sift_keypoints,
                "demo_segment_to_next": seg_file,
                "frame_idx": bed.frame_idx,
                "timestamp": bed.timestamp,
            })

        wp_nodes = []
        for wp_idx, (frame_idx, ts, kp_count) in enumerate(self._waypoints):
            between = self._find_between_beds(frame_idx)
            if between is None:
                continue
            from_bed, to_bed = between
            frac = self._interpolation_frac(from_bed, to_bed, frame_idx)
            from_node = nodes[from_bed - 1] if from_bed <= len(nodes) else None
            to_node = nodes[to_bed - 1] if to_bed <= len(nodes) else None
            if from_node and to_node:
                map_x = int(from_node["map_x"] + frac * (to_node["map_x"] - from_node["map_x"]))
                map_y = int(from_node["map_y"] + frac * (to_node["map_y"] - from_node["map_y"]))
            else:
                map_x, map_y = 300, 300

            wp_id = f"waypoint_{wp_idx + 1:02d}"
            wp_nodes.append({
                "id": wp_id,
                "type": "waypoint",
                "map_x": map_x,
                "map_y": map_y,
                "reference_image": f"map_images/{wp_id}.png",
                "sift_file": f"map_images/{wp_id}_sift.npz",
                "sift_keypoints": kp_count,
                "frame_idx": frame_idx,
                "timestamp": ts,
            })

        route_order = list(range(1, num_beds + 1))

        return {
            "camera_tab_count": settings.CAMERA_TAB_COUNT,
            "nodes": nodes + wp_nodes,
            "route_order": route_order,
            "bed_count": num_beds,
            "waypoint_count": len(wp_nodes),
            "demo_dir": self._demo_dir,
        }

    def _save_outputs(self, map_data: dict) -> None:
        """Save map JSON, reference images, SIFT features, and demo segments."""
        base = settings.GARDENING_ROUTINES_DIR
        img_dir = os.path.join(base, "map_images")
        seg_dir = os.path.join(base, "demo_segments")
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(seg_dir, exist_ok=True)

        sift = cv2.SIFT_create(nfeatures=settings.SIFT_NFEATURES)

        for bed in self._beds:
            if bed.reference_frame is not None:
                img_path = os.path.join(img_dir, f"bed_{bed.bed_num}_reference.png")
                cv2.imwrite(img_path, bed.reference_frame)

                gray = cv2.cvtColor(bed.reference_frame, cv2.COLOR_BGR2GRAY)
                kps, des = sift.detectAndCompute(gray, None)
                sift_path = os.path.join(img_dir, f"bed_{bed.bed_num}_sift.npz")
                if kps and des is not None:
                    kp_pts = np.array([kp.pt for kp in kps], dtype=np.float32)
                    np.savez_compressed(sift_path, descriptors=des, keypoints=kp_pts)

        for wp_idx, (frame_idx, ts, kp_count) in enumerate(self._waypoints):
            wp_id = f"waypoint_{wp_idx + 1:02d}"
            frame = self._load_frame(frame_idx)
            if frame is not None:
                img_path = os.path.join(img_dir, f"{wp_id}.png")
                cv2.imwrite(img_path, frame)

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                kps, des = sift.detectAndCompute(gray, None)
                sift_path = os.path.join(img_dir, f"{wp_id}_sift.npz")
                if kps and des is not None:
                    kp_pts = np.array([kp.pt for kp in kps], dtype=np.float32)
                    np.savez_compressed(sift_path, descriptors=des, keypoints=kp_pts)

        for seg in self._segments:
            seg_path = os.path.join(seg_dir,
                                    f"bed_{seg.from_bed}_to_bed_{seg.to_bed}.json")
            seg_data = {
                "from_bed": seg.from_bed,
                "to_bed": seg.to_bed,
                "duration": seg.duration,
                "events": seg.events,
            }
            with open(seg_path, "w") as f:
                json.dump(seg_data, f, indent=2)

        map_path = os.path.join(base, "garden_map.json")
        with open(map_path, "w") as f:
            json.dump(map_data, f, indent=2)

        log.info("Saved garden map → %s", map_path)

    def _build_summary(self) -> dict:
        total_frames = len(self._frame_timestamps)
        duration = self._frame_timestamps[-1] if self._frame_timestamps else 0
        return {
            "total_frames": total_frames,
            "duration_s": duration,
            "bed_arrivals": len(self._beds),
            "beds": [
                {
                    "bed_num": b.bed_num,
                    "frame_idx": b.frame_idx,
                    "timestamp": b.timestamp,
                    "sift_keypoints": b.sift_keypoints,
                }
                for b in self._beds
            ],
            "waypoints_sampled": len(self._waypoints),
            "avg_waypoint_keypoints": (
                int(np.mean([w[2] for w in self._waypoints]))
                if self._waypoints else 0
            ),
            "segments": len(self._segments),
            "segment_details": [
                {
                    "from": s.from_bed,
                    "to": s.to_bed,
                    "events": len(s.events),
                    "duration": s.duration,
                }
                for s in self._segments
            ],
        }

    def _print_summary(self, s: dict) -> None:
        mins = int(s["duration_s"]) // 60
        secs = int(s["duration_s"]) % 60
        print(f"\n{'═' * 48}")
        print(" DEMO PROCESSING")
        print(f"{'═' * 48}")
        print(f" Total frames:  {s['total_frames']}")
        print(f" Total duration: {mins}m {secs}s")
        print()
        print(f" Bed arrivals detected: {s['bed_arrivals']}")
        for b in s["beds"]:
            status = "✓" if b["sift_keypoints"] >= 100 else "⚠ LOW"
            print(f"   bed_{b['bed_num']}: frame {b['frame_idx']}  "
                  f"(t={b['timestamp']:.1f}s)   — "
                  f"{b['sift_keypoints']} SIFT keypoints {status}")
        print()
        print(f" Waypoints sampled: {s['waypoints_sampled']} (between beds)")
        print(f"   Average SIFT keypoints per waypoint: {s['avg_waypoint_keypoints']}")
        print()
        print(f" Demo segments extracted: {s['segments']} (bed-to-bed transitions)")
        for seg in s["segment_details"]:
            print(f"   bed_{seg['from']}→bed_{seg['to']}: "
                  f"{seg['events']} key events, {seg['duration']:.1f}s duration")
        print()
        print(f" Schematic built: {s['bed_arrivals']} beds + "
              f"{s['waypoints_sampled']} waypoints on circle layout")
        print(f" Map saved to: {settings.GARDENING_ROUTINES_DIR}/garden_map.json")
        print(f"{'═' * 48}")

    def _load_frame(self, idx: int) -> np.ndarray | None:
        for ext in ("jpg", "png"):
            path = os.path.join(self._frames_dir, f"{idx:05d}.{ext}")
            if os.path.isfile(path):
                frame = cv2.imread(path, cv2.IMREAD_COLOR)
                if frame is not None:
                    return self._ensure_retina_scale(frame)
        return None

    def _ensure_retina_scale(self, frame: np.ndarray) -> np.ndarray:
        """Upscale to retina (2x) if the frame was saved at logical resolution.

        The template matcher and calibration expect retina-resolution frames.
        Demo frames saved by demo_recorder are halved to save space, so we
        restore them here for processing.
        """
        h, w = frame.shape[:2]
        if w < 1200:
            return cv2.resize(frame, (w * 2, h * 2),
                              interpolation=cv2.INTER_LINEAR)
        return frame

    def _find_between_beds(self, frame_idx: int) -> tuple[int, int] | None:
        for i in range(len(self._beds) - 1):
            if self._beds[i].frame_idx <= frame_idx < self._beds[i + 1].frame_idx:
                return (self._beds[i].bed_num, self._beds[i + 1].bed_num)
        return None

    def _interpolation_frac(self, from_bed: int, to_bed: int, frame_idx: int) -> float:
        from_arrival = None
        to_arrival = None
        for b in self._beds:
            if b.bed_num == from_bed:
                from_arrival = b
            if b.bed_num == to_bed:
                to_arrival = b
        if from_arrival is None or to_arrival is None:
            return 0.5
        span = to_arrival.frame_idx - from_arrival.frame_idx
        if span <= 0:
            return 0.5
        return (frame_idx - from_arrival.frame_idx) / span


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m gardening.demo_processor <demo_dir>")
        sys.exit(1)

    demo_dir = sys.argv[1]
    if not os.path.isdir(demo_dir):
        print(f"Error: {demo_dir} is not a directory")
        sys.exit(1)

    processor = DemoProcessor(demo_dir)
    processor.process()


if __name__ == "__main__":
    main()
