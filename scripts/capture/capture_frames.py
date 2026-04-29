#!/usr/bin/env python3
"""
Capture screenshots from video at fixed intervals.
Used by run_workflow.py for non-PPT mode.

Usage:
  python capture_frames.py <video_file> <output_folder> --interval 30
"""

import sys
import os
import subprocess
import argparse


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            capture_output=True, text=True, check=True
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0.0


def capture_frame_ffmpeg(video_path: str, timestamp: float, output_file: str) -> bool:
    """Capture a single frame using ffmpeg."""
    cmd = [
        'ffmpeg', '-y', '-ss', str(timestamp),
        '-i', video_path,
        '-vframes', '1',
        '-q:v', '2',
        output_file
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return os.path.exists(output_file)
    except subprocess.CalledProcessError:
        return False


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
