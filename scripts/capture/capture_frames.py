#!/usr/bin/env python3
"""
Capture screenshots from video at fixed intervals.
Used by run_workflow.py for non-PPT mode.

Usage:
  python capture_frames.py <video_file> <output_folder> --interval 30
"""

import sys
import os
import argparse

# Add scripts/ root so common.utils is importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_ROOT = os.path.dirname(_HERE)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from common.utils import probe_duration as get_video_duration, capture_frame_ffmpeg  # noqa: E402


def capture_frames_fixed(video_path: str, output_folder: str, interval: int = 30):
    """Capture frames at fixed intervals."""
    duration = get_video_duration(video_path)
    if duration == 0:
        print("Error: Could not determine video duration", file=sys.stderr)
        return 0

    print(f"[Fixed Mode] Duration: {duration:.1f}s, interval: {interval}s")
    os.makedirs(output_folder, exist_ok=True)

    captured = 0
    for timestamp in range(0, int(duration), interval):
        output_file = os.path.join(output_folder, f'frame_{timestamp:04d}.jpg')
        if capture_frame_ffmpeg(video_path, timestamp, output_file):
            captured += 1
            print(f"  Captured: {timestamp}s")

    print(f"Total frames captured: {captured}")
    return captured


def main():
    parser = argparse.ArgumentParser(description='Capture video frames at fixed intervals')
    parser.add_argument('video_file', help='Path to video file')
    parser.add_argument('output_folder', help='Output folder for screenshots')
    parser.add_argument('--interval', type=int, default=30,
                        help='Fixed interval in seconds (default: 30)')
    args = parser.parse_args()
    capture_frames_fixed(args.video_file, args.output_folder, interval=args.interval)


if __name__ == '__main__':
    main()
