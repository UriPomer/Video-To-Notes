#!/usr/bin/env python3
"""
Generate Pass 1 sub-agent batches driven by subtitles (no frames).

Reads <video_folder>/subtitles.json (must have mode=subtitle_primary),
splits segments into chronological chunks of roughly equal character count,
and prints a ready-to-paste prompt for each batch. Each sub-agent returns
topic_candidates[], key_moments[] (timestamps where frames should be
extracted later), and gap_suspicions[] — all purely text-based output.

Usage:
  python plan_subtitle_pass1.py <video_folder> [options]

Options:
  --target-chars N     Aim for this many chars per batch (default: 2500)
  --max-batches N      Hard cap on batch count (default: 12)
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

from common.utils import format_ts  # noqa: E402


def split_segments(segments: List[Dict], target_chars: int, max_batches: int) -> List[List[Dict]]:
    """Greedy chronological split: accumulate until chunk reaches target_chars."""
    if not segments:
        return []

    total_chars = sum(len(s['text']) for s in segments)
    # Respect the cap: if target_chars would produce too many batches, grow it.
    need = max(1, (total_chars + target_chars - 1) // target_chars)
    if need > max_batches:
        target_chars = (total_chars + max_batches - 1) // max_batches

    batches: List[List[Dict]] = []
    current: List[Dict] = []
    current_chars = 0
    for seg in segments:
        current.append(seg)
        current_chars += len(seg['text'])
        if current_chars >= target_chars:
            batches.append(current)
            current = []
            current_chars = 0
    if current:
        batches.append(current)
    return batches


def build_plan(video_folder: str, target_chars: int, max_batches: int) -> Dict:
    video_folder = os.path.abspath(video_folder)
    sub_path = os.path.join(video_folder, 'subtitles.json')
    if not os.path.exists(sub_path):
        print(f"Error: {sub_path} not found. Run transcribe_audio.py first.", file=sys.stderr)
        sys.exit(1)

    with open(sub_path, 'r', encoding='utf-8') as f:
        subs = json.load(f)

    if subs.get('mode') != 'subtitle_primary':
        print(f"Error: subtitles.json mode is '{subs.get('mode')}', expected 'subtitle_primary'. "
              f"Use plan_pass1_batches.py for image-primary mode.", file=sys.stderr)
        sys.exit(2)

    segments = subs.get('segments', [])
    batches_raw = split_segments(segments, target_chars, max_batches)

    batches = []
    for i, chunk in enumerate(batches_raw):
        batches.append({
            'index': i + 1,
            'start_sec': chunk[0]['start'],
            'end_sec': chunk[-1]['end'],
            'char_count': sum(len(s['text']) for s in chunk),
            'segment_count': len(chunk),
            'segments': chunk,
        })

    plan = {
        'plan_type': 'subtitle',
        'plan_id': hashlib.sha256(
            json.dumps(batches, ensure_ascii=False, sort_keys=True).encode('utf-8')
        ).hexdigest()[:16],
        'total_segments': len(segments),
        'total_chars': sum(len(s['text']) for s in segments),
        'n_batches': len(batches),
        'lang': subs.get('lang', 'unknown'),
        'source': subs.get('source', 'unknown'),
        'batches': batches,
    }

    plan_path = os.path.join(video_folder, 'pass1_subtitle_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as f:
        # 保留批次正文，重启后无需依赖已滚出上下文的终端输出。
        json.dump(plan, f, ensure_ascii=False, indent=2)

    plan['_runtime_video_folder'] = video_folder
    return plan


def print_prompts(plan: Dict) -> None:
    n = plan['n_batches']
    print(f"# Pass 1 (subtitle-driven) — {plan['total_chars']} chars in {n} batches")
    print(f"# Plan ID: {plan['plan_id']}")
    print(f"# Language: {plan['lang']}  Source: {plan['source']}")
    print(f"# Process ALL {n} batches; use available concurrency in waves.")
    print()

    for b in plan['batches']:
        start = format_ts(b['start_sec'])
        end = format_ts(b['end_sec'])
        result_path = os.path.join(
            plan['_runtime_video_folder'], 'pass1_results', f"batch_{b['index']:03d}.json")
        print(f"=== BATCH {b['index']} of {n} ===")
        print(f"Time range: {start} - {end}  ({b['segment_count']} segments, {b['char_count']} chars)")
        print()
        print("Sub-agent prompt (paste into Agent tool, subagent_type=\"general-purpose\"):")
        print("---")
        print("You are a Pass 1 subtitle scanner for the video-summarizer skill.")
        print(f"Below are the speaker's transcribed subtitles for the {start} - {end}")
        print("segment. No frames yet — your job is to read the text and decide where")
        print("to place screenshots, which topics are covered, and where visual content")
        print("was likely shown but not captioned.")
        print()
        print("Subtitle segments (one per line, prefixed with MM:SS):")
        for seg in b['segments']:
            ts = format_ts(seg['start'])
            text_one_line = seg['text'].replace('\n', ' ').strip()
            print(f"  [{ts}] {text_one_line}")
        print()
        print(f"Write exactly one JSON object to: {result_path}")
        print("{")
        print(f'  "plan_id": "{plan["plan_id"]}",')
        print(f'  "batch_index": {b["index"]},')
        print("""  "batch_range": "<start_mmss>-<end_mmss>",
  "topic_candidates": [
    { "start_sec": 125.0, "title": "Sensor Toolkit", "evidence_text": "first mentioned here..." }
  ],
  "key_moments": [
    {
      "timestamp_sec": 345.0,
      "reason": "speaker enumerates LOS Sensor inspector params (AngleThreshold, MaxDistance, ...)",
      "content_type": "inspector | diagram | code | game_footage | comparison | title_card",
      "priority": "high | medium | low"
    }
  ],
  "gap_suspicions": [
    {
      "range_sec": [320, 400],
      "reason": "speaker says 'as you can see in this diagram...' but no visual cue text — diagram likely on screen",
      "priority": "high | medium | low"
    }
  ]
}""")
        print()
        print("CRITICAL — write the result file directly:")
        print("  - Use apply_patch to create only the JSON file at the exact path above")
        print("  - Write valid JSON without markdown fences or surrounding prose")
        print("  - Do not modify any other file")
        print("  - In your final response, only confirm the batch index and result path")
        print()
        print("Guidance for key_moments:")
        print("  - Mark timestamps where a screenshot would materially help the reader:")
        print("    concrete params, code walk-throughs, diagrams, before/after comparisons,")
        print("    title cards of new topics, audience-question Q&A peaks.")
        print("  - Aim for roughly 1 key_moment per 60-90s of subtitle — not every line.")
        print("  - Use HIGH priority for irreplaceable visuals (code, Inspector, diagrams);")
        print("    MEDIUM for illustrative footage; LOW for nice-to-have.")
        print()
        print("Guidance for gap_suspicions:")
        print("  - Trigger on subtitle phrases like 'this diagram', 'as you see',")
        print("    'here's the code', 'on the left/right' without enough verbal detail.")
        print("  - Trigger when topic clearly shifts but no evidence in text (probably")
        print("    the speaker was pointing at a slide).")
        print("---")
        print()


def print_summary(plan: Dict, video_folder: str) -> None:
    plan_path = os.path.join(os.path.abspath(video_folder), 'pass1_subtitle_plan.json')
    print(f"Pass 1 字幕计划已保存: {plan_path}")
    print(f"Plan ID: {plan['plan_id']}; 批次: {plan['n_batches']}; 字符: {plan['total_chars']}")
    print("将每批结果写入 pass1_results\\batch_NNN.json，再运行 merge_results.py --stage pass1。")
    print("需要查看完整代理提示时重新运行并添加 --print-prompts。")


def main():
    parser = argparse.ArgumentParser(description='Plan Pass 1 subtitle-driven sub-agent batches')
    parser.add_argument('video_folder', help='Path to the video output folder (containing subtitles.json)')
    parser.add_argument('--target-chars', type=int, default=2500,
                        help='Target chars per batch (default: 2500)')
    parser.add_argument('--max-batches', type=int, default=12,
                        help='Hard cap on batch count (default: 12)')
    parser.add_argument('--print-prompts', action='store_true',
                        help='打印全部代理提示；默认只输出计划摘要')
    args = parser.parse_args()

    plan = build_plan(args.video_folder, args.target_chars, args.max_batches)
    os.makedirs(os.path.join(os.path.abspath(args.video_folder), 'pass1_results'), exist_ok=True)
    if args.print_prompts:
        print_prompts(plan)
    else:
        print_summary(plan, args.video_folder)


if __name__ == '__main__':
    main()
