#!/usr/bin/env python3
"""
Pass 1.5 — Gap resolution.

Reads pass1_scan.json's `gap_suspicions` (reported by Pass 1 sub-agents),
extracts new frames in each gap window via ffmpeg, filters uninformative
ones, then prints a ready-to-paste plan for round-2 sub-agents.

Usage:
  python resolve_gaps.py <video_folder> [options]

Options:
  --max-gaps N           Process at most N gaps (default: 20)
  --min-priority LEVEL   Only process gaps at this priority or higher
                         (high | medium | low, default: medium)
  --default-fps F        Fallback fps if sub-agent didn't specify (default: 0.5)
  --dry-run              Compute the plan but don't run ffmpeg
  --batch-size M         Target frames per round-2 sub-agent (default: 15)

Output:
  - New frames at screenshots/gap_<start>_<end>_<idx>.jpg
  - pass1_gaps_plan.json with the round-2 batch structure
  - Stdout: ready-to-paste round-2 sub-agent prompts
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Dict, List, Optional

# Re-use helpers from common/utils.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_ROOT = os.path.dirname(_HERE)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from common.utils import format_ts, load_json, classify, load_gray  # noqa: E402


PRIORITY_RANK = {'high': 3, 'medium': 2, 'low': 1}


def passes_priority(gap: Dict, min_level: str) -> bool:
    gap_p = gap.get('priority', 'medium')
    return PRIORITY_RANK.get(gap_p, 2) >= PRIORITY_RANK[min_level]


def dedupe_gaps(gaps: List[Dict]) -> List[Dict]:
    """Merge overlapping gap ranges, keeping highest priority."""
    if not gaps:
        return []
    # Sort by start time
    gaps = sorted(gaps, key=lambda g: g['range_sec'][0])
    merged = [dict(gaps[0])]
    for g in gaps[1:]:
        last = merged[-1]
        if g['range_sec'][0] <= last['range_sec'][1]:
            # Overlap: extend and keep the higher priority + concatenate reason
            last['range_sec'][1] = max(last['range_sec'][1], g['range_sec'][1])
            if PRIORITY_RANK.get(g.get('priority', 'medium'), 2) > PRIORITY_RANK.get(last.get('priority', 'medium'), 2):
                last['priority'] = g.get('priority', 'medium')
            last['reason'] = f"{last.get('reason', '')} | {g.get('reason', '')}"
            # Use the finer of the two suggested fps
            last['suggested_fps'] = max(
                last.get('suggested_fps') or 0,
                g.get('suggested_fps') or 0,
            ) or None
        else:
            merged.append(dict(g))
    return merged


def extract_gap_frames(video_file: str, screenshots_dir: str,
                       start: float, end: float, fps: float,
                       dry_run: bool = False) -> List[str]:
    """Run ffmpeg to extract frames in [start, end] at the given fps.

    Returns list of newly-created filenames (just basename)."""
    duration = end - start
    if duration <= 0:
        return []

    pattern = f"gap_{int(start):04d}_{int(end):04d}_%03d.jpg"
    out_pattern = os.path.join(screenshots_dir, pattern)

    cmd = [
        'ffmpeg', '-y', '-ss', f'{start:.2f}',
        '-to', f'{end:.2f}',
        '-i', video_file,
        '-vf', f'fps={fps},scale=800:-1',
        '-q:v', '2',
        out_pattern,
    ]

    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return []

    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"  ffmpeg failed for gap [{start:.1f}, {end:.1f}]: {e.stderr.decode('utf-8', errors='replace')[:200]}",
              file=sys.stderr)
        return []

    # Enumerate the files we just created (prefix-matched)
    prefix = f"gap_{int(start):04d}_{int(end):04d}_"
    created = sorted(
        fn for fn in os.listdir(screenshots_dir)
        if fn.startswith(prefix) and fn.endswith('.jpg')
    )
    return created


def filter_new_frames(screenshots_dir: str, filenames: List[str]) -> List[str]:
    """Apply the same uninformative-frame classifier; return survivors."""
    if not filenames:
        return []
    kept = []
    prev_gray = None
    for fn in filenames:
        gray = load_gray(os.path.join(screenshots_dir, fn))
        if gray is None:
            continue
        reasons = classify(gray, prev_gray)
        if not reasons:
            kept.append(fn)
            prev_gray = gray
    return kept


def estimate_ts_from_gap_filename(fn: str, start: float, fps: float) -> float:
    """gap_0320_0400_003.jpg -> start + (idx-1) / fps."""
    import re
    m = re.match(r'gap_(\d+)_(\d+)_(\d+)\.jpg$', fn)
    if not m:
        return start
    _start = int(m.group(1))
    idx = int(m.group(3))
    return float(_start) + (idx - 1) / fps


def build_round2_batches(new_frames_by_gap: List[Dict],
                         screenshots_dir: str, batch_size: int) -> List[Dict]:
    """Flatten all gap frames into chronological batches of <= batch_size.

    Stores rel_path (relative to video_folder); prompt emission rebuilds
    absolute paths at print time from _runtime_video_folder.
    """
    all_entries = []
    for entry in new_frames_by_gap:
        fps = entry['fps']
        for fn in entry['kept_frames']:
            ts = estimate_ts_from_gap_filename(fn, entry['range_sec'][0], fps)
            all_entries.append({
                'filename': fn,
                'timestamp_sec': ts,
                'rel_path': f"screenshots/{fn}",
                'gap_range': entry['range_sec'],
                'gap_reason': entry['reason'],
            })

    all_entries.sort(key=lambda x: x['timestamp_sec'])

    batches = []
    for i in range(0, len(all_entries), batch_size):
        chunk = all_entries[i:i + batch_size]
        batches.append({
            'index': len(batches) + 1,
            'start_sec': chunk[0]['timestamp_sec'],
            'end_sec': chunk[-1]['timestamp_sec'],
            'frame_count': len(chunk),
            'frames': chunk,
        })
    return batches


def print_round2_prompts(plan: Dict) -> None:
    n = len(plan['batches'])
    video_folder = plan['_runtime_video_folder']
    print(f"# Pass 1.5 round-2 plan — {plan['total_new_frames']} new frames in {n} batches")
    print(f"#   (from {plan['gaps_processed']} gaps; {plan['gaps_skipped']} skipped by priority)")
    print(f"# Saved: {os.path.join(video_folder, 'pass1_gaps_plan.json')}")
    if n == 0:
        print("# No round-2 batches needed.")
        return
    print(f"# Dispatch ALL {n} sub-agents in parallel (one message with {n} Agent tool calls).")
    print()

    for b in plan['batches']:
        start = format_ts(b['start_sec'])
        end = format_ts(b['end_sec'])
        print(f"=== ROUND-2 BATCH {b['index']} of {n} ===")
        print(f"Time range: {start} - {end}  ({b['frame_count']} frames)")
        print()
        print("Sub-agent prompt (paste into Agent tool, subagent_type=\"general-purpose\"):")
        print("---")
        print("You are a Pass 1.5 gap-resolver for the video-summarizer skill.")
        print("These frames were extracted to fill 'gap_suspicions' from Pass 1")
        print("— they may contain sub-topics, bullet reveals, code walk-throughs,")
        print("or other content that Pass 1 missed. Read each frame with the")
        print("Read tool and record what you see.")
        print()
        print("Frames (chronological, with their parent gap context):")
        seen_gaps = set()
        for f in b['frames']:
            rng = tuple(f['gap_range'])
            marker = ""
            if rng not in seen_gaps:
                marker = f"   [gap {format_ts(rng[0])}-{format_ts(rng[1])}: {f['gap_reason'][:80]}]"
                seen_gaps.add(rng)
            abs_path = os.path.normpath(os.path.join(video_folder, f['rel_path']))
            print(f"  {format_ts(f['timestamp_sec'])}  {abs_path}{marker}")
        print()
        print("Return ONLY a JSON object (no markdown, no prose). Same schema as")
        print("Pass 1, but gap_suspicions is usually empty (we're already")
        print("resolving gaps — only flag a nested gap if VERY obvious):")
        print("""{
  "batch_range": "<start_mmss>-<end_mmss>",
  "frames": [
    {
      "filename": "gap_XXXX_YYYY_NNN.jpg",
      "timestamp_sec": 123.4,
      "is_title_card": true | false,
      "slide_title": "<text at top of slide, or null>",
      "content_type": "title_card | bullets | diagram | code | inspector | game_footage | speaker | transition | logo",
      "transcribed_text": "<verbatim text visible on slide>",
      "notable": "<anything worth expanding in Pass 2>",
      "informative": true | false
    }
  ],
  "topic_candidates": [],
  "gap_suspicions": []
}""")
        print("---")
        print()


def main():
    parser = argparse.ArgumentParser(description='Pass 1.5 gap resolution')
    parser.add_argument('video_folder', help='Path to the video output folder')
    parser.add_argument('--max-gaps', type=int, default=20,
                        help='Process at most N gaps (default: 20)')
    parser.add_argument('--min-priority', choices=['high', 'medium', 'low'],
                        default='medium',
                        help='Only process gaps at this priority or higher')
    parser.add_argument('--default-fps', type=float, default=0.5,
                        help='Fallback fps if sub-agent did not specify (default: 0.5)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Compute the plan but skip ffmpeg execution')
    parser.add_argument('--batch-size', type=int, default=15,
                        help='Target frames per round-2 sub-agent (default: 15)')
    args = parser.parse_args()

    video_folder = os.path.abspath(args.video_folder)
    screenshots_dir = os.path.join(video_folder, 'screenshots')
    scan_path = os.path.join(video_folder, 'pass1_scan.json')

    if not os.path.isfile(scan_path):
        print(f"Error: {scan_path} not found. Run Pass 1 first and save merged "
              f"sub-agent results there.", file=sys.stderr)
        sys.exit(1)

    # Locate video file
    video_file = None
    for ext in ('mp4', 'webm', 'mkv', 'flv'):
        cand = os.path.join(video_folder, f'video.{ext}')
        if os.path.exists(cand):
            video_file = cand
            break
    if not video_file:
        print(f"Error: video.mp4/webm/mkv/flv not found in {video_folder}",
              file=sys.stderr)
        sys.exit(1)

    scan = load_json(scan_path, {})
    raw_gaps = scan.get('gap_suspicions', [])
    if not raw_gaps:
        print("No gap_suspicions in pass1_scan.json — nothing to resolve.")
        return

    # Filter by priority, then merge overlapping ranges
    gaps = [g for g in raw_gaps if passes_priority(g, args.min_priority)]
    skipped = len(raw_gaps) - len(gaps)
    gaps = dedupe_gaps(gaps)

    # Rank by priority desc then width; cap at max-gaps
    gaps.sort(key=lambda g: (
        -PRIORITY_RANK.get(g.get('priority', 'medium'), 2),
        -(g['range_sec'][1] - g['range_sec'][0])
    ))
    gaps = gaps[:args.max_gaps]

    print(f"[Pass 1.5 Gap Resolution]")
    print(f"  pass1_scan.json: {scan_path}")
    print(f"  Video: {video_file}")
    print(f"  Raw gaps: {len(raw_gaps)}, filtered+merged: {len(gaps)}, "
          f"skipped by priority: {skipped}")
    print()

    new_frames_by_gap = []
    for gap in gaps:
        start, end = gap['range_sec']
        fps = gap.get('suggested_fps') or args.default_fps
        print(f"  Gap {format_ts(start)}-{format_ts(end)} "
              f"({gap.get('priority', 'medium')}, fps={fps}): {gap.get('reason', '')[:80]}")

        new_files = extract_gap_frames(
            video_file, screenshots_dir, start, end, fps, dry_run=args.dry_run)
        if not new_files:
            continue

        kept = filter_new_frames(screenshots_dir, new_files) if not args.dry_run else new_files
        dropped = len(new_files) - len(kept)
        print(f"    extracted {len(new_files)}, kept {len(kept)} after filter "
              f"(dropped {dropped} as uninformative)")

        # Delete the dropped uninformative frames
        if not args.dry_run:
            for fn in new_files:
                if fn not in kept:
                    try:
                        os.remove(os.path.join(screenshots_dir, fn))
                    except OSError:
                        pass

        if kept:
            new_frames_by_gap.append({
                'range_sec': [start, end],
                'reason': gap.get('reason', ''),
                'priority': gap.get('priority', 'medium'),
                'fps': fps,
                'kept_frames': kept,
            })

    total_new = sum(len(e['kept_frames']) for e in new_frames_by_gap)
    print()
    print(f"  Total new informative frames: {total_new}")

    batches = build_round2_batches(new_frames_by_gap, screenshots_dir, args.batch_size)

    plan_path = os.path.join(video_folder, 'pass1_gaps_plan.json')
    # _runtime_video_folder is an anchor for print_round2_prompts() to rebuild
    # absolute paths; it is stripped before the JSON is persisted.
    plan = {
        'gaps_processed': len(new_frames_by_gap),
        'gaps_skipped': skipped,
        'total_new_frames': total_new,
        'new_frames_by_gap': new_frames_by_gap,
        'batches': batches,
        '_runtime_video_folder': video_folder,
    }
    with open(plan_path, 'w', encoding='utf-8') as f:
        persisted = {k: v for k, v in plan.items() if not k.startswith('_')}
        json.dump(persisted, f, ensure_ascii=False, indent=2)

    print()
    print_round2_prompts(plan)


if __name__ == '__main__':
    main()
