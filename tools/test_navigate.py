"""CHECKPOINT 5: Single-bed navigation test.

Navigate from one bed to another with verbose logging.
Verify that demo replay gets close and SIFT correction lands on target.

Usage:
    python test_navigate.py --from 1 --to 2
    python test_navigate.py --from 3 --to 4 --map gardening_routines/garden_map.json
"""

from __future__ import annotations

import argparse
import os
import threading

from ttr_bot.config import settings
from ttr_bot.vision.localizer import GardenMap, GardenLocalizer
from ttr_bot.gardening.navigator import GardenNavigator


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-bed navigation test")
    default_map = os.path.join(settings.GARDENING_ROUTINES_DIR, "garden_map.json")
    parser.add_argument("--map", default=default_map, help="Path to garden_map.json")
    parser.add_argument("--from", dest="from_bed", type=int, required=True,
                        help="Starting bed number")
    parser.add_argument("--to", dest="to_bed", type=int, required=True,
                        help="Target bed number")
    args = parser.parse_args()

    if not os.path.isfile(args.map):
        print(f"Error: map file not found: {args.map}")
        print("Run a demo recording + processing first.")
        return

    garden_map = GardenMap.load(args.map)
    localizer = GardenLocalizer(garden_map)

    print(f"Map loaded: {len(garden_map.bed_nodes)} beds, "
          f"{len(garden_map.waypoint_nodes)} waypoints\n")

    from_id = f"bed_{args.from_bed}"
    to_id = f"bed_{args.to_bed}"

    from_node = garden_map.get_bed(from_id)
    to_node = garden_map.get_bed(to_id)

    if from_node is None:
        print(f"Error: bed {from_id} not in map")
        return
    if to_node is None:
        print(f"Error: bed {to_id} not in map")
        return

    stop_event = threading.Event()
    navigator = GardenNavigator(garden_map, localizer, stop_event)
    navigator.on_log = lambda msg: print(f"  {msg}")
    navigator.current_bed = from_id

    print(f"{'─' * 50}")
    print(f" NAVIGATION: {from_id} → {to_id}")
    print(f"{'─' * 50}")
    print(f" Stand at bed {args.from_bed} in TTR, then press Enter to start.\n")

    input(" Press Enter to begin navigation... ")
    print()

    result = navigator.navigate_to_bed(to_id)

    print(f"\n{'─' * 50}")
    print(f" RESULT: {'ARRIVED' if result.arrived else 'FAILED'} "
          f"via {result.method or 'none'} ({result.duration_s:.1f}s)")
    if result.stuck_recoveries > 0:
        print(f" Stuck recoveries: {result.stuck_recoveries}")
    if result.skipped:
        print(" SKIPPED (bed not in map)")
    print(f"{'─' * 50}")


if __name__ == "__main__":
    main()
