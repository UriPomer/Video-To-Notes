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
        'total_segments': len(segments),
        'total_chars': sum(len(s['text']) for s in segments),
        'n_batches': len(batches),
        'lang': subs.get('lang', 'unknown'),
        'source': subs.get('source', 'unknown'),
        'batches': batches,
    }

    plan_path = os.path.join(video_folder, 'pass1_subtitle_plan.json')
    # Persist without the inline segment text duplicates — the source of
    # truth is subtitles.json. Keep segment timestamps + indices only.
    persisted = {
        **plan,
        'batches': [
            {**b, 'segments': [{'start': s['start'], 'end': s['end']} for s in b['segments']]}
            for b in batches
        ],
    }
    with open(plan_path, 'w', encoding='utf-8') as f:
        json.dump(persisted, f, ensure_ascii=False, indent=2)

    return plan


def print_prompts(plan: Dict) -> None:
    n = plan['n_batches']
    print(f"# Pass 1 (subtitle-driven) — {plan['total_chars']} chars in {n} batches")
    print(f"# Language: {plan['lang']}  Source: {plan['source']}")
    print(f"# Dispatch ALL {n} sub-agents in parallel (one message with {n} Agent tool calls).")
    print()

    for b in plan['batches']:
        start = format_ts(b['start_sec'])
        end = format_ts(b['end_sec'])
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
        print("Return ONLY a JSON object (no markdown, no prose):")
        print("""{
  "batch_range": "<start_mmss>-<end_mmss>",
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


def main():
    parser = argparse.ArgumentParser(description='Plan Pass 1 subtitle-driven sub-agent batches')
    parser.add_argument('video_folder', help='Path to the video output folder (containing subtitles.json)')
    parser.add_argument('--target-chars', type=int, default=2500,
                        help='Target chars per batch (default: 2500)')
    parser.add_argument('--max-batches', type=int, default=12,
                        help='Hard cap on batch count (default: 12)')
    args = parser.parse_args()

    plan = build_plan(args.video_folder, args.target_chars, args.max_batches)
    print_prompts(plan)


if __name__ == '__main__':
    main()
