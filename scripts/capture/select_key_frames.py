#!/usr/bin/env python3
"""
Select key frames for LLM visual analysis.
Sorts frames by information density (diff score, text density) and outputs top N.

Usage:
  python select_key_frames.py <screenshots_folder> [--count 100] [--output key_frames.json]

Output format (key_frames.json):
  {
    "folder": "path/to/screenshots",
    "total_frames": 1324,
    "selected_count": 100,
    "selection_method": "combined_score",
    "frames": [
      {
        "filename": "frame_0300_00.jpg",
        "timestamp": 300.0,
        "diff_score": 0.85,
        "rank": 1
      }
    ],
    "time_groups": {
      "0-300s": ["frame_0000_00.jpg", ...],
      "300-600s": [...]
    }
  }
"""

import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional


def parse_frame_timestamp(filename: str) -> Optional[float]:
    match = re.search(r'frame_(\d+)_(\d+)', filename)
    if match:
        secs = int(match.group(1))
        cents = int(match.group(2))
        return secs + cents / 100.0
    match = re.search(r'frame_(\d+)', filename)
    if match:
        return float(match.group(1))
    return None


def parse_diff_from_json(diffs_path: str) -> Dict[str, float]:
    """Parse diff scores from frame_diffs.json if available."""
    diff_scores = {}
    if not os.path.exists(diffs_path):
        return diff_scores
    
    with open(diffs_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for frame in data.get('frames', []):
        diff_scores[frame['filename']] = frame.get('diff_score', 0.1)
    
    return diff_scores


def estimate_text_density(image_path: str) -> float:
    """Estimate text density by file size ratio (larger = more detail)."""
    try:
        size = os.path.getsize(image_path)
        # Normalize: typical PPT slide with text is 80-150KB
        # Empty/dark slide is 20-40KB
        density = min(size / 100000.0, 2.0)  # Cap at 2.0
        return density
    except:
        return 0.5


def load_skip_set(screenshots_dir: str) -> set:
    """Load filenames flagged by filter_uninformative_frames.py (if run)."""
    p = os.path.join(screenshots_dir, 'frames_to_skip.json')
    if not os.path.exists(p):
        return set()
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return set(data.get('skip', {}).keys())
    except Exception:
        return set()


def select_key_frames(screenshots_dir: str, count: int = 100,
                      output_path: Optional[str] = None,
                      min_gap: Optional[float] = None) -> Dict[str, Any]:
    screenshots_dir = os.path.abspath(screenshots_dir)

    if not os.path.exists(screenshots_dir):
        print(f"Error: Directory not found: {screenshots_dir}", file=sys.stderr)
        sys.exit(1)

    image_files = sorted([
        f for f in os.listdir(screenshots_dir)
        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
    ])

    if not image_files:
        print(f"Error: No images found", file=sys.stderr)
        sys.exit(1)

    # Load diff scores from frame_diffs.json
    diffs_path = os.path.join(screenshots_dir, 'frame_diffs.json')
    diff_scores = parse_diff_from_json(diffs_path)

    # Load uninformative-frame blacklist (if filter_uninformative_frames.py was run)
    skip_set = load_skip_set(screenshots_dir)

    print(f"[Key Frame Selection]")
    print(f"  Folder: {screenshots_dir}")
    print(f"  Total frames: {len(image_files)}")
    print(f"  Diff scores loaded: {len(diff_scores)}")
    print(f"  Uninformative filtered: {len(skip_set)}")
    print(f"  Target selection: {count}")

    # Score each frame
    scored_frames = []
    for filename in image_files:
        if filename in skip_set:
            continue
        filepath = os.path.join(screenshots_dir, filename)
        timestamp = parse_frame_timestamp(filename) or 0.0

        # Combined score: diff_score * text_density
        diff = diff_scores.get(filename, 0.1)
        density = estimate_text_density(filepath)
        combined_score = diff * density

        scored_frames.append({
            "filename": filename,
            "timestamp": round(timestamp, 2),
            "diff_score": round(diff, 3),
            "text_density": round(density, 3),
            "combined_score": round(combined_score, 3),
        })

    # Sort by combined score descending
    scored_frames.sort(key=lambda x: x["combined_score"], reverse=True)

    # Adaptive minimum gap: spread selections across the video duration.
    # Rationale: a 60-min talk with count=100 should allow ~18s gaps; a 5-min
    # tutorial with count=30 should use ~5s. Hard-coded 10s clusters at the
    # front of long videos.
    if min_gap is None:
        if scored_frames:
            duration = max(f["timestamp"] for f in scored_frames)
            # Aim for even coverage: duration / count, halved to allow some density
            # Clamp to [5s, 30s]: too small -> duplicate selections; too big -> misses
            min_gap = max(5.0, min(30.0, duration / max(count, 1) / 2.0))
        else:
            min_gap = 10.0
    print(f"  Adaptive min_gap: {min_gap:.1f}s")

    selected = []
    for frame in scored_frames:
        timestamp = frame["timestamp"]
        # Check if this frame is too close to any already selected frame
        too_close = any(
            abs(timestamp - s["timestamp"]) < min_gap
            for s in selected
        )
        if not too_close:
            selected.append(frame)
        if len(selected) >= count:
            break
    
    # Sort by timestamp for chronological order
    selected.sort(key=lambda x: x["timestamp"])
    
    # Add rank
    for i, frame in enumerate(selected):
        frame["rank"] = i + 1
    
    # Group by time segments for easier LLM consumption
    time_groups = {}
    segment_size = 300  # 5 minutes per group
    for frame in selected:
        segment = int(frame["timestamp"] // segment_size) * segment_size
        key = f"{segment}-{segment + segment_size}s"
        if key not in time_groups:
            time_groups[key] = []
        time_groups[key].append(frame["filename"])
    
    result = {
        "folder": os.path.basename(screenshots_dir),  # relative: folder name only
        "total_frames": len(image_files),
        "filtered_out": len(skip_set),
        "selected_count": len(selected),
        "selection_method": "combined_score (diff * text_density)",
        "min_gap_seconds": round(min_gap, 2),
        "frames": selected,
        "time_groups": time_groups,
    }
    
    if output_path is None:
        output_path = os.path.join(os.path.dirname(screenshots_dir), "key_frames.json")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n[Done]")
    print(f"  Output: {output_path}")
    print(f"  Selected: {len(selected)} frames")
    print(f"  Time groups:")
    for key, files in sorted(time_groups.items(), key=lambda x: int(x[0].split('-')[0])):
        print(f"    {key}: {len(files)} frames")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Select key frames for LLM analysis')
    parser.add_argument('screenshots_dir', help='Path to screenshots folder')
    parser.add_argument('--count', '-n', type=int, default=100, help='Number of frames to select (default: 100)')
    parser.add_argument('--output', '-o', help='Output JSON path')
    parser.add_argument('--min-gap', type=float, default=None,
                        help='Minimum seconds between selections (default: adaptive, '
                             'duration/count/2 clamped to [5, 30])')
    args = parser.parse_args()

    select_key_frames(args.screenshots_dir, args.count, args.output, args.min_gap)


if __name__ == '__main__':
    main()
