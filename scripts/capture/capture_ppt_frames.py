#!/usr/bin/env python3
"""
Smart PPT/Slide detection for presentation videos.
Detects content changes in the presentation area (typically left/center of screen).

Usage:
  python capture_ppt_frames.py <video_file> <output_folder> [options]
"""

import sys
import os
import json
import subprocess
import argparse
import cv2
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class FrameInfo:
    timestamp: float
    diff_score: float
    filepath: str


def ts_to_filename(ts: float) -> str:
    """Convert timestamp to safe filename."""
    secs = int(ts)
    cents = int(round((ts - secs) * 100))
    return f"frame_{secs:04d}_{cents:02d}.jpg"


def filename_to_ts(filename: str) -> float:
    """Extract timestamp from filename."""
    base = os.path.splitext(filename)[0]
    # frame_0012_50.jpg -> 12.50
    parts = base.replace('frame_', '').split('_')
    if len(parts) == 2:
        return int(parts[0]) + int(parts[1]) / 100.0
    return 0.0


def get_video_info(video_path: str) -> Tuple[float, float, int, int]:
    """Get video duration, fps, width, height."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0, 0, 0, 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()
    return duration, fps, width, height


def extract_ppt_region(frame: np.ndarray, mode: str = 'auto') -> np.ndarray:
    """
    Extract the presentation/slide region from a video frame.
    """
    h, w = frame.shape[:2]
    if mode == 'left':
        return frame[:, :int(w * 0.75)]
    elif mode == 'center':
        margin = int(w * 0.15)
        return frame[:, margin:w-margin]
    elif mode == 'auto':
        right_region = frame[:, int(w * 0.7):]
        gray_right = cv2.cvtColor(right_region, cv2.COLOR_BGR2GRAY)
        right_std = np.std(gray_right)
        if right_std < 40:
            return frame[:, :int(w * 0.72)]
        else:
            return frame
    else:
        return frame


def calculate_region_diff(frame1: np.ndarray, frame2: np.ndarray,
                         region_mode: str = 'auto') -> float:
    """Calculate difference focusing on presentation region."""
    region1 = extract_ppt_region(frame1, region_mode)
    region2 = extract_ppt_region(frame2, region_mode)

    r1 = cv2.resize(region1, (320, 180))
    r2 = cv2.resize(region2, (320, 180))

    g1 = cv2.cvtColor(r1, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(r2, cv2.COLOR_BGR2GRAY)

    diff = cv2.absdiff(g1, g2)

    sobel1 = cv2.Sobel(g1, cv2.CV_64F, 1, 1, ksize=3)
    sobel2 = cv2.Sobel(g2, cv2.CV_64F, 1, 1, ksize=3)
    edge_diff = np.abs(sobel1 - sobel2)

    combined_diff = diff.astype(float) + edge_diff.astype(float) * 0.5
    score = np.mean(combined_diff) / 255.0

    return score


def capture_frame_ffmpeg(video_path: str, ts: float, output_file: str,
                         scale: int = 800) -> bool:
    """Capture a single frame using ffmpeg with HD quality."""
    cmd = [
        'ffmpeg', '-y', '-ss', str(ts), '-i', video_path,
        '-vframes', '1', '-q:v', '1',
        '-vf', f'scale={scale}:-1',
        output_file
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return os.path.exists(output_file)
    except Exception:
        return False


def load_frame_cv(video_path: str, ts: float, fps: float) -> Optional[np.ndarray]:
    """Load a frame at given timestamp using OpenCV."""
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def capture_ppt_frames(video_path: str, output_folder: str,
                      threshold: float = 0.03,
                      min_interval: float = 2.0,
                      max_depth: int = 6,
                      initial_interval: int = 10,
                      max_frames: int = 200,
                      scale: int = 800) -> List[FrameInfo]:
    """
    Capture frames optimized for presentation videos.
    Focuses on detecting slide/PPT changes.
    """
    duration, fps, width, height = get_video_info(video_path)
    if duration == 0:
        print("Error: Could not determine video info", file=sys.stderr)
        return []

    print(f"[PPT Detection Mode]")
    print(f"  Video: {width}x{height}, {duration:.1f}s @ {fps:.1f}fps")
    print(f"  Initial interval: {initial_interval}s")
    print(f"  Threshold: {threshold}")
    print(f"  Min interval: {min_interval}s")
    print(f"  Max depth: {max_depth}")
    print(f"  Max frames: {max_frames}")
    print(f"  Output scale: {scale}px width")
    print()

    os.makedirs(output_folder, exist_ok=True)
    captured_frames: List[FrameInfo] = []

    # Phase 1: Initial coarse sampling
    print("Phase 1: Initial coarse sampling...")
    initial_timestamps = list(range(0, int(duration) + 1, initial_interval))
    if not initial_timestamps or initial_timestamps[-1] < duration:
        initial_timestamps.append(duration)

    prev_frame = None

    for ts in initial_timestamps:
        output_file = os.path.join(output_folder, ts_to_filename(ts))
        if not capture_frame_ffmpeg(video_path, ts, output_file, scale):
            continue

        frame = load_frame_cv(video_path, ts, fps)
        if frame is None:
            continue

        if prev_frame is not None:
            score = calculate_region_diff(prev_frame, frame, 'left')
            print(f"  [{ts:.1f}s] PPT region diff: {score:.3f}")
        else:
            score = 1.0
            print(f"  [{ts:.1f}s] First frame")

        captured_frames.append(FrameInfo(ts, score, output_file))
        prev_frame = frame

    print(f"  {len(captured_frames)} initial samples")
    print()

    # Phase 2: Adaptive refinement for high-change regions
    print("Phase 2: Refining high-change regions...")

    def refine_recursive(t1: float, t2: float,
                        frame1: np.ndarray, frame2: np.ndarray,
                        depth: int):
        """Recursively find slide transitions between two timestamps."""
        interval = t2 - t1

        if interval <= min_interval or depth >= max_depth:
            return

        # Check frame limit
        if len(captured_frames) >= max_frames:
            print(f"  {'  ' * depth}[{t1:.1f}s - {t2:.1f}s] FRAME LIMIT REACHED")
            return

        score = calculate_region_diff(frame1, frame2, 'left')

        if score <= threshold:
            print(f"  {'  ' * depth}[{t1:.1f}s - {t2:.1f}s] diff={score:.3f} -> skip")
            return

        mid = (t1 + t2) / 2
        print(f"  {'  ' * depth}[{t1:.1f}s - {t2:.1f}s] diff={score:.3f} -> capture {mid:.1f}s")

        mid_file = os.path.join(output_folder, ts_to_filename(mid))
        if not capture_frame_ffmpeg(video_path, mid, mid_file, scale):
            return

        mid_frame = load_frame_cv(video_path, mid, fps)
        if mid_frame is None:
            return

        captured_frames.append(FrameInfo(mid, score, mid_file))

        refine_recursive(t1, mid, frame1, mid_frame, depth + 1)
        refine_recursive(mid, t2, mid_frame, frame2, depth + 1)

    # Run refinement on consecutive pairs
    for i in range(len(captured_frames) - 1):
        f1 = captured_frames[i]
        f2 = captured_frames[i + 1]

        if f2.diff_score > threshold:
            print(f"\nRefining [{f1.timestamp:.1f}s - {f2.timestamp:.1f}s]...")

            frame1 = load_frame_cv(video_path, f1.timestamp, fps)
            frame2 = load_frame_cv(video_path, f2.timestamp, fps)

            if frame1 is not None and frame2 is not None:
                refine_recursive(f1.timestamp, f2.timestamp, frame1, frame2, 0)

        # Early exit if we've hit the limit
        if len(captured_frames) >= max_frames:
            print(f"\n! Reached max frames limit ({max_frames}), stopping refinement.")
            break

    # Sort and deduplicate
    captured_frames.sort(key=lambda x: x.timestamp)
    unique = []
    seen = set()
    for f in captured_frames:
        key = round(f.timestamp, 1)
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # If still over limit after dedup, keep highest-diff frames
    if len(unique) > max_frames:
        print(f"\n! Too many frames ({len(unique)}), pruning to {max_frames} highest-change frames...")
        unique.sort(key=lambda x: x.diff_score, reverse=True)
        keep_files = {f.filepath for f in unique[:max_frames]}
        unique = unique[:max_frames]
        unique.sort(key=lambda x: x.timestamp)

        # Delete pruned frames
        for f in captured_frames:
            if f.filepath not in keep_files and os.path.exists(f.filepath):
                os.remove(f.filepath)

    print(f"\n{'='*50}")
    print(f"Total unique frames: {len(unique)}")
    print(f"{'='*50}")

    # Save frame diff scores for key frame selection
    diffs_path = os.path.join(output_folder, 'frame_diffs.json')
    diffs_data = {
        'frames': [
            {
                'filename': os.path.basename(f.filepath),
                'timestamp': f.timestamp,
                'diff_score': f.diff_score,
            }
            for f in unique
        ]
    }
    with open(diffs_path, 'w', encoding='utf-8') as f:
        json.dump(diffs_data, f, ensure_ascii=False, indent=2)
    print(f"Frame diffs saved: {diffs_path}")

    return unique


def main():
    parser = argparse.ArgumentParser(
        description='PPT-focused frame capture for presentation videos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic PPT detection (default: max 200 frames)
  python capture_ppt_frames.py video.mp4 screenshots

  # High sensitivity for fast slides
  python capture_ppt_frames.py video.mp4 screenshots --threshold 0.02 --max-depth 8

  # Limit to 100 frames, higher resolution
  python capture_ppt_frames.py video.mp4 screenshots --max-frames 100 --scale 1920

  # Focus on left region (GDC style)
  python capture_ppt_frames.py video.mp4 screenshots --region left
        """
    )
    parser.add_argument('video_file', help='Path to video file')
    parser.add_argument('output_folder', help='Output folder for screenshots')
    parser.add_argument('--threshold', type=float, default=0.03,
                        help='PPT region change threshold (default: 0.03)')
    parser.add_argument('--min-interval', type=float, default=2.0,
                        help='Minimum interval between captures (default: 2.0)')
    parser.add_argument('--max-depth', type=int, default=6,
                        help='Maximum recursion depth (default: 6)')
    parser.add_argument('--initial-interval', type=int, default=10,
                        help='Initial sampling interval (default: 10)')
    parser.add_argument('--max-frames', type=int, default=200,
                        help='Maximum number of frames to capture (default: 200)')
    parser.add_argument('--scale', type=int, default=800,
                        help='Output image width in pixels (default: 800)')
    parser.add_argument('--region', choices=['left', 'center', 'auto'], default='left',
                        help='Presentation region mode (default: left)')

    args = parser.parse_args()

    capture_ppt_frames(
        args.video_file,
        args.output_folder,
        threshold=args.threshold,
        min_interval=args.min_interval,
        max_depth=args.max_depth,
        initial_interval=args.initial_interval,
        max_frames=args.max_frames,
        scale=args.scale
    )


if __name__ == '__main__':
    main()
