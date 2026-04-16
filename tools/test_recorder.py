"""CHECKPOINT 1: Interactive test for the demo recorder.

Run this while TTR is open.  Records for 60 seconds (or until you
press Ctrl-C), then prints the recording summary.

Usage:
    python test_recorder.py [--seconds 60]
"""

from __future__ import annotations

import argparse
import signal
import time

from ttr_bot.gardening.demo_recorder import DemoRecorder


def main() -> None:
    parser = argparse.ArgumentParser(description="Test demo recorder")
    parser.add_argument("--seconds", type=int, default=60,
                        help="Recording duration (default 60)")
    args = parser.parse_args()

    recorder = DemoRecorder()
    recorder.on_status = lambda msg: print(msg)

    demo_dir = recorder.start()
    print(f"\nRecording to: {demo_dir}")
    print(f"Recording for {args.seconds}s — press Ctrl-C to stop early.\n")
    print("Walk around in TTR and press arrow keys...\n")

    def _sigint(sig, frame):
        pass
    signal.signal(signal.SIGINT, _sigint)

    try:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and recorder.recording:
            elapsed = recorder.duration
            fc = recorder.frame_count
            print(f"\r  {elapsed:.0f}s  |  {fc} frames captured", end="", flush=True)
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass

    print("\n\nStopping...")
    summary = recorder.stop()
    print()

    if summary:
        print("Pass criteria check:")
        fps = summary.get("avg_fps", 0)
        ok_fps = 4.0 <= fps <= 7.0
        print(f"  FPS: {fps} {'✓' if ok_fps else '✗ (expected 4-6)'}")

        events = summary.get("keyboard_events", 0)
        presses = summary.get("keyboard_presses", 0)
        print(f"  Key events: {events} ({presses} presses) "
              f"{'✓' if events > 0 else '✗ (no events — walk around!)'}")

        frames = summary.get("frame_count", 0)
        print(f"  Frames: {frames} {'✓' if frames > 10 else '✗'}")

        size_mb = summary.get("total_frame_bytes", 0) / (1024 * 1024)
        ok_size = size_mb < 500
        print(f"  Size: {size_mb:.1f} MB {'✓' if ok_size else '✗ (too large)'}")

        all_pass = ok_fps and events > 0 and frames > 10 and ok_size
        print(f"\n{'ALL PASS ✓' if all_pass else 'SOME CHECKS FAILED ✗'}")


if __name__ == "__main__":
    main()
