#!/usr/bin/env python3
"""
Flag uninformative frames so the agent can drop them before embedding in notes.

Heuristics (each frame failing any of these is flagged):
  - "black": mean luminance < BLACK_MEAN and luminance std < BLACK_STD
            (pure black / very dark transition)
  - "low_variance": grayscale std < LOW_VAR_STD
            (near-uniform slide: blank transition, solid color, or end card)
  - "low_edge": Sobel edge magnitude mean < LOW_EDGE
            (no text or line art; typically speaker-only shot or blurred frame)
  - "near_duplicate": SSIM-ish crude diff vs previous non-skipped frame < DUP_DIFF
            (adjacent frames showing the same slide)

Outputs <screenshots>/frames_to_skip.json:
  {
    "folder": "...",
    "total": 200,
    "skipped": 37,
    "skip": {
      "frame_0000_00.jpg": ["black"],
      "frame_1230_00.jpg": ["low_variance", "near_duplicate"],
      ...
    },
    "keep_count": 163,
    "thresholds": {...}
  }

Usage:
  python filter_uninformative_frames.py <screenshots_folder>
"""

import argparse
import json
import os
import sys
from typing import Dict, List

# Add scripts/ root to sys.path so common/ is importable both when run
# directly (python phase_a_prep/filter_uninformative_frames.py ...) and
# when imported as phase_a_prep.filter_uninformative_frames.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_ROOT = os.path.dirname(_HERE)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from common.utils import (  # noqa: E402
    BLACK_MEAN, BLACK_STD, LOW_VAR_STD, LOW_EDGE, DUP_DIFF,
    classify, load_gray,
)


def filter_frames(screenshots_dir: str) -> Dict:
    screenshots_dir = os.path.abspath(screenshots_dir)
    if not os.path.isdir(screenshots_dir):
        print(f"Error: not a directory: {screenshots_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        f for f in os.listdir(screenshots_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if not files:
        print("Error: no images found", file=sys.stderr)
        sys.exit(1)

    print(f"[Filter Uninformative Frames]")
    print(f"  Folder: {screenshots_dir}")
    print(f"  Total frames: {len(files)}")

    skip: Dict[str, List[str]] = {}
    prev_gray = None

    for fn in files:
        gray = load_gray(os.path.join(screenshots_dir, fn))
        if gray is None:
            skip[fn] = ["unreadable"]
            continue

        reasons = classify(gray, prev_gray)
        if reasons:
            skip[fn] = reasons
        else:
            # Only update the baseline when we keep the frame;
            # otherwise a run of identical bad frames would all look "different".
            prev_gray = gray

    result = {
        "folder": os.path.basename(screenshots_dir),  # relative: folder name only
        "total": len(files),
        "skipped": len(skip),
        "keep_count": len(files) - len(skip),
        "skip": skip,
        "thresholds": {
            "black_mean": BLACK_MEAN,
            "black_std": BLACK_STD,
            "low_variance_std": LOW_VAR_STD,
            "low_edge": LOW_EDGE,
            "dup_diff": DUP_DIFF,
        },
    }

    out_path = os.path.join(screenshots_dir, "frames_to_skip.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Summary by reason
    reason_counts: Dict[str, int] = {}
    for reasons in skip.values():
        for r in reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1

    print(f"\n[Done]")
    print(f"  Output: {out_path}")
    print(f"  Skipped: {len(skip)} / {len(files)} ({100 * len(skip) / len(files):.1f}%)")
    for reason, n in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"    {reason}: {n}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Flag uninformative frames")
    parser.add_argument("screenshots_dir", help="Path to screenshots folder")
    args = parser.parse_args()
    filter_frames(args.screenshots_dir)


if __name__ == "__main__":
    main()
