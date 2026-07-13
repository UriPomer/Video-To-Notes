#!/usr/bin/env python3
"""
Generate the Pass 1 sub-agent batch plan.

Scans every informative JPG in <video_folder>/screenshots/ (optionally
restricted to frames in key_frames.json), drops entries listed in
frames_to_skip.json, splits the rest into chronological batches, and
prints ready-to-paste sub-agent prompts.

Usage:
  python plan_pass1_batches.py <video_folder> [options]

Options:
  --batches N             Force a specific batch count (default: auto = ceil(frame_count / batch_size))
  --batch-size M          Target frames per batch when auto-computing (default: 15)
  --key-frames-only       Restrict to key_frames.json (legacy, smaller shortlist)

Output:
  - Stdout: ready-to-paste sub-agent prompts, one per batch
  - <video_folder>/pass1_plan.json: full batch structure for main-agent reference
"""

import argparse
import hashlib
import json
import os
import sys
from typing import Dict, List

# Add scripts/ root so common.utils is importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_ROOT = os.path.dirname(_HERE)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from common.utils import format_ts, load_json, parse_frame_timestamp  # noqa: E402



def build_batches(video_folder: str, n_batches: int, use_all_frames: bool = True) -> Dict:
    video_folder = os.path.abspath(video_folder)
    screenshots_dir = os.path.join(video_folder, 'screenshots')

    if not os.path.isdir(screenshots_dir):
        print(f"Error: {screenshots_dir} not found.", file=sys.stderr)
        sys.exit(1)

    skip_path = os.path.join(screenshots_dir, 'frames_to_skip.json')
    skip_data = load_json(skip_path, {'skip': {}})
    skip_set = set(skip_data.get('skip', {}).keys())

    if use_all_frames:
        # Default: scan EVERY informative frame on disk, not just key_frames.json.
        # Rationale: key_frames.json is a ~100-frame shortlist for LLM budget
        # reasons; on disk there are typically ~200 frames (capture_ppt_frames
        # max-frames). Skipping the other ~100 can miss short-lived slides.
        all_files = [
            fn for fn in os.listdir(screenshots_dir)
            if fn.lower().endswith('.jpg') and fn not in skip_set
        ]
        frames = []
        for fn in all_files:
            ts = parse_frame_timestamp(fn)
            if ts is None:
                continue
            frames.append({'filename': fn, 'timestamp': ts})
    else:
        # Legacy: only frames selected by select_key_frames.py
        key_frames_path = os.path.join(video_folder, 'key_frames.json')
        if not os.path.exists(key_frames_path):
            print(f"Error: {key_frames_path} not found. "
                  f"Run select_key_frames.py first, or use --all-frames.", file=sys.stderr)
            sys.exit(1)
        key_data = load_json(key_frames_path, {})
        frames = [f for f in key_data.get('frames', []) if f['filename'] not in skip_set]

    frames.sort(key=lambda x: x['timestamp'])

    if not frames:
        print("Error: no informative frames after skip filter", file=sys.stderr)
        sys.exit(1)

    # Chronological split: even count per batch, not even duration.
    # JSON stores relative paths (screenshots/<filename>), anchored to the
    # video_folder where pass1_plan.json sits. Sub-agent prompts rebuild
    # absolute paths at print time so sub-agents can Read regardless of CWD.
    per_batch = max(1, (len(frames) + n_batches - 1) // n_batches)
    batches = []
    for i in range(0, len(frames), per_batch):
        chunk = frames[i:i + per_batch]
        batches.append({
            'index': len(batches) + 1,
            'start_sec': chunk[0]['timestamp'],
            'end_sec': chunk[-1]['timestamp'],
            'frame_count': len(chunk),
            'frames': [
                {
                    'filename': f['filename'],
                    'timestamp_sec': f['timestamp'],
                    'rel_path': f"screenshots/{f['filename']}",
                }
                for f in chunk
            ],
        })

    total = len(batches)
    # Absolute paths are kept only as a runtime anchor so print_prompts() can
    # rebuild them; they are NOT intended for consumers of the JSON.
    plan = {
        'plan_type': 'image',
        'plan_id': hashlib.sha256(
            json.dumps(batches, ensure_ascii=False, sort_keys=True).encode('utf-8')
        ).hexdigest()[:16],
        'total_frames': len(frames),
        'n_batches': total,
        'batches': batches,
        '_runtime_video_folder': video_folder,  # internal: anchor for prompts
    }

    plan_path = os.path.join(video_folder, 'pass1_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as f:
        # Strip the runtime-only key before persisting
        persisted = {k: v for k, v in plan.items() if not k.startswith('_')}
        json.dump(persisted, f, ensure_ascii=False, indent=2)

    return plan


def print_prompts(plan: Dict) -> None:
    n = plan['n_batches']
    video_folder = plan['_runtime_video_folder']
    print(f"# Pass 1 batch plan — {plan['total_frames']} frames in {n} batches")
    print(f"# Plan ID: {plan['plan_id']}")
    print(f"# Saved: {os.path.join(video_folder, 'pass1_plan.json')}")
    print(f"# Process ALL {n} batches; use available concurrency in waves.")
    print()

    for b in plan['batches']:
        start = format_ts(b['start_sec'])
        end = format_ts(b['end_sec'])
        result_path = os.path.join(
            video_folder, 'pass1_results', f"batch_{b['index']:03d}.json")
        print(f"=== BATCH {b['index']} of {n} ===")
        print(f"Time range: {start} - {end}  ({b['frame_count']} frames)")
        print()
        print("Sub-agent prompt (paste into Agent tool, subagent_type=\"general-purpose\"):")
        print("---")
        print(f"You are a Pass 1 scanner for the video-summarizer skill.")
        print(f"Read each of the following {b['frame_count']} frames (time range "
              f"{start} - {end}) using the Read tool. For EACH frame, record what you see.")
        print()
        print("Frames to scan (chronological order):")
        for f in b['frames']:
            abs_path = os.path.normpath(os.path.join(video_folder, f['rel_path']))
            print(f"  {format_ts(f['timestamp_sec'])}  {abs_path}")
        print()
        print("Reference example (the output style you're aiming for):")
        print("  .codebuddy/skills/video-summarizer/examples/good_notes_phasmophobia.md")
        print()
        print("IMPORTANT — gap_suspicions:")
        print("  Beyond transcribing frames, flag 'suspicious gaps' between")
        print("  consecutive frames where you think valuable content was likely")
        print("  missed. Examples:")
        print("    - frame A shows a section title, frame B (80s later) jumps")
        print("      straight into a specific Inspector config — sub-topics")
        print("      probably happened in between.")
        print("    - frame A shows bullets 1-2 on a slide, frame B (30s later)")
        print("      shows bullets 1-5 — bullets 3-4 were revealed mid-gap.")
        print("    - frame A shows 'before' game footage, frame B shows 'after'")
        print("      with no transition captured.")
        print("    - Speaker discusses code for a long time but no code frame")
        print("      was captured in that window.")
        print("  Do NOT flag gaps that are clearly just speaker talk on the same")
        print("  slide with no visual change, or gaps < 20 seconds.")
        print()
        print(f"Write exactly one JSON object to: {result_path}")
        print("{")
        print(f'  "plan_id": "{plan["plan_id"]}",')
        print(f'  "batch_index": {b["index"]},')
        print("""  "batch_range": "<start_mmss>-<end_mmss>",
  "frames": [
    {
      "filename": "frame_XXXX_YY.jpg",
      "timestamp_sec": 123.4,
      "is_title_card": true | false,
      "slide_title": "<text at top of slide, or null>",
      "content_type": "title_card | bullets | diagram | code | inspector | game_footage | speaker | transition | logo",
      "transcribed_text": "<verbatim text visible on slide, preserve English terms; use \\n for line breaks>",
      "notable": "<diagrams/code/params worth expanding in Pass 2, or null>",
      "informative": true | false
    }
  ],
  "topic_candidates": [
    { "start_sec": 125.0, "title": "Sensor Toolkit", "evidence_frame": "frame_0125_00.jpg" }
  ],
  "gap_suspicions": [
    {
      "between": ["frame_0320_00.jpg", "frame_0400_00.jpg"],
      "range_sec": [320, 400],
      "reason": "frame_0320 shows 'Sensor Toolkit' title, frame_0400 jumps to LOS Sensor Inspector with specific params — sub-topics likely happened between",
      "priority": "high | medium | low",
      "suggested_fps": 0.5
    }
  ]
}""")
        print()
        print("CRITICAL — write the result file directly:")
        print("  - Use apply_patch to create only the JSON file at the exact path above")
        print("  - Write valid JSON without markdown fences or surrounding prose")
        print("  - Do not modify any other file")
        print("  - In your final response, only confirm the batch index and result path")
        print("---")
        print()


def print_summary(plan: Dict) -> None:
    video_folder = plan['_runtime_video_folder']
    print(f"Pass 1 图片计划已保存: {os.path.join(video_folder, 'pass1_plan.json')}")
    print(f"Plan ID: {plan['plan_id']}; 批次: {plan['n_batches']}; 帧: {plan['total_frames']}")
    print("将每批结果写入 pass1_results\\batch_NNN.json，再运行 merge_results.py --stage pass1。")
    print("需要查看完整代理提示时重新运行并添加 --print-prompts。")


def main():
    parser = argparse.ArgumentParser(description='Plan Pass 1 sub-agent batches')
    parser.add_argument('video_folder', help='Path to the video output folder (containing key_frames.json)')
    parser.add_argument('--batches', type=int, default=None,
                        help='Number of batches (default: auto = ceil(frame_count / batch_size))')
    parser.add_argument('--batch-size', type=int, default=15,
                        help='Target frames per batch when auto-computing batches (default: 15)')
    parser.add_argument('--key-frames-only', action='store_true',
                        help='Only use frames from key_frames.json (default: scan all JPGs on disk)')
    parser.add_argument('--print-prompts', action='store_true',
                        help='打印全部代理提示；默认只输出计划摘要')
    args = parser.parse_args()

    use_all = not args.key_frames_only

    # Auto-compute batch count if not supplied: keep per-batch size at ~20 to
    # stay well under the request-body limit.
    if args.batches is None:
        video_folder = os.path.abspath(args.video_folder)
        screenshots_dir = os.path.join(video_folder, 'screenshots')
        skip_path = os.path.join(screenshots_dir, 'frames_to_skip.json')
        skip_data = load_json(skip_path, {'skip': {}})
        skip_set = set(skip_data.get('skip', {}).keys())
        if use_all and os.path.isdir(screenshots_dir):
            count = sum(
                1 for fn in os.listdir(screenshots_dir)
                if fn.lower().endswith('.jpg') and fn not in skip_set
            )
        else:
            key_data = load_json(os.path.join(video_folder, 'key_frames.json'), {})
            count = sum(1 for f in key_data.get('frames', []) if f['filename'] not in skip_set)
        n_batches = max(1, (count + args.batch_size - 1) // args.batch_size)
    else:
        n_batches = args.batches

    plan = build_batches(args.video_folder, n_batches, use_all_frames=use_all)
    os.makedirs(os.path.join(os.path.abspath(args.video_folder), 'pass1_results'), exist_ok=True)
    if args.print_prompts:
        print_prompts(plan)
    else:
        print_summary(plan)


if __name__ == '__main__':
    main()
