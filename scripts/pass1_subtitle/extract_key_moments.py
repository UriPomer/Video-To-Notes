#!/usr/bin/env python3
"""
Extract one frame per key moment, identified by Pass 1 subtitle scanners.

Reads key_moments[] from pass1_scan.json (main agent merges sub-agent
outputs there), deduplicates nearby timestamps, then runs ffmpeg once per
surviving moment to produce screenshots/moment_SSSS.jpg at scale 800.

Usage:
  python extract_key_moments.py <video_folder> [--min-gap 3] [--scale 800]

After running, update pass1_scan.json.frames[] with the new moment_*.jpg
entries so Pass 2 can cite them the same way as regular frames.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Dict, List


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def locate_video_file(video_folder: str):
    for ext in ('mp4', 'webm', 'mkv', 'flv'):
        p = os.path.join(video_folder, f'video.{ext}')
        if os.path.exists(p):
            return p
    return None


def dedupe_and_sort(moments: List[Dict], min_gap: float) -> List[Dict]:
    """Drop moments within min_gap of a higher/equal-priority earlier moment."""
    priority_rank = {'high': 3, 'medium': 2, 'low': 1}

    sortable = []
    for m in moments:
        ts = float(m.get('timestamp_sec', 0))
        pr = priority_rank.get(m.get('priority', 'medium'), 2)
        sortable.append((ts, -pr, m))
    sortable.sort()

    kept: List[Dict] = []
    for ts, _, m in sortable:
        if kept and ts - kept[-1]['timestamp_sec'] < min_gap:
            # Merge reason to keep context
            prev = kept[-1]
            prev['reason'] = f"{prev.get('reason', '')} / {m.get('reason', '')}".strip(' /')
            continue
        kept.append({
            'timestamp_sec': ts,
            'reason': m.get('reason', ''),
            'content_type': m.get('content_type'),
            'priority': m.get('priority', 'medium'),
        })
    return kept


def extract_one(video_file: str, ts_sec: float, out_path: str, scale: int) -> bool:
    """ffmpeg -ss <ts> -i video -frames:v 1 -vf scale=<scale>:-1 out.jpg"""
    # -ss before -i enables fast seek; accurate enough for slide captures.
    cmd = [
        'ffmpeg', '-y',
        '-ss', f"{ts_sec:.3f}",
        '-i', video_file,
        '-frames:v', '1',
        '-vf', f'scale={scale}:-1',
        '-q:v', '3',
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        sys.stderr.write(f"[extract_key_moments] ffmpeg failed for {ts_sec}: {result.stderr[:200]}\n")
        return False
    return True


def extract_moments(video_folder: str, min_gap: float, scale: int) -> List[Dict]:
    video_folder = os.path.abspath(video_folder)
    video_file = locate_video_file(video_folder)
    if not video_file:
        print(f"Error: no video.* in {video_folder}", file=sys.stderr)
        sys.exit(1)

    scan_path = os.path.join(video_folder, 'pass1_scan.json')
    scan = load_json(scan_path, None)
    if scan is None:
        print(f"Error: {scan_path} not found. Merge sub-agent outputs into it first.", file=sys.stderr)
        sys.exit(1)

    moments = scan.get('key_moments', [])
    if not moments:
        print("[extract_key_moments] no key_moments in pass1_scan.json — nothing to do")
        return []

    kept = dedupe_and_sort(moments, min_gap)
    print(f"[extract_key_moments] {len(moments)} moments → {len(kept)} after dedupe (min_gap={min_gap}s)")

    screenshots_dir = os.path.join(video_folder, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)

    results: List[Dict] = []
    for m in kept:
        ts = m['timestamp_sec']
        fn = f"moment_{int(ts):04d}.jpg"
        out_path = os.path.join(screenshots_dir, fn)
        if extract_one(video_file, ts, out_path, scale):
            results.append({
                'filename': fn,
                'timestamp_sec': ts,
                'rel_path': f"screenshots/{fn}",
                'reason': m.get('reason', ''),
                'content_type': m.get('content_type'),
                'priority': m.get('priority', 'medium'),
            })

    # Write a manifest next to pass1_scan.json so the main agent can easily
    # plan the vision round without recomputing dedup.
    manifest_path = os.path.join(video_folder, 'key_moments_extracted.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump({'extracted': results}, f, ensure_ascii=False, indent=2)
    print(f"[extract_key_moments] wrote {len(results)} frames to {screenshots_dir}")
    print(f"[extract_key_moments] manifest: {manifest_path}")
    return results


def main():
    if not shutil.which('ffmpeg'):
        print("Error: ffmpeg not on PATH", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description='Extract key-moment frames from subtitle-driven Pass 1')
    parser.add_argument('video_folder')
    parser.add_argument('--min-gap', type=float, default=3.0,
                        help='Minimum gap between extracted moments in seconds (default: 3.0)')
    parser.add_argument('--scale', type=int, default=800,
                        help='Output width in pixels (default: 800, matches capture_ppt_frames)')
    args = parser.parse_args()
    extract_moments(args.video_folder, min_gap=args.min_gap, scale=args.scale)


if __name__ == '__main__':
    main()
