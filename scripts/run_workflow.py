#!/usr/bin/env python3
"""
Complete workflow: download video, capture frames, select key frames, generate notes.
Supports standard interval capture and PPT-focused capture.

Usage:
  python run_workflow.py <video_url> [options]

Options:
  --ppt           Use PPT-focused capture mode (recommended for tech talks)
  --interval N    Screenshot interval in seconds for standard mode (default: 30)
  --threshold F   PPT change threshold (default: 0.03)
  --max-depth N   Max recursion depth for PPT mode (default: 6)
  --initial N     Initial sampling interval for PPT mode (default: 10)
  --key-frames N  Number of key frames to select for LLM analysis (default: 100)
  --no-key-select Skip key frame selection, use all captured frames
"""

import sys
import os
import argparse

# Add script directory to path so fetch / subtitle / capture / pass2_scaffold
# sub-packages can be imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch.create_folder import create_folder
from fetch.download_video import download_video
from subtitle.transcribe_audio import transcribe
from capture.capture_frames import capture_frames_fixed as capture_frames
from capture.capture_ppt_frames import capture_ppt_frames
from capture.filter_frames import filter_frames
from capture.select_key_frames import select_key_frames
from pass2_scaffold.generate_notes import generate_notes


def run_workflow(url: str, ppt_mode: bool = False, interval: int = 30,
                 threshold: float = 0.03, max_depth: int = 6,
                 initial_interval: int = 10, key_frames: int = 100,
                 no_key_select: bool = False, no_filter: bool = False,
                 whisper_model: str = 'large-v3', force_image_mode: bool = False):
    """Run complete video summarization workflow.

    Two possible paths, decided by subtitles.json.mode:
      - subtitle_primary: skip frame capture/filter/select; Pass 1 reads text
      - image_primary:    current pipeline unchanged
    """
    print("=" * 60)
    print("Video Summarizer Workflow")
    print("=" * 60)

    # Step 1: Create folder
    print("\n[1/7] Creating folder...")
    folder = create_folder(url)
    print(f"Folder: {folder}")

    # Step 2: Download video (yt-dlp now also fetches subtitles if available)
    print("\n[2/7] Downloading video and metadata...")
    metadata = download_video(url, folder)

    # Find video file
    video_file = None
    for ext in ['mp4', 'webm', 'mkv', 'flv']:
        candidate = os.path.join(folder, f'video.{ext}')
        if os.path.exists(candidate):
            video_file = candidate
            break

    if not video_file:
        print("Error: Video file not found after download", file=sys.stderr)
        sys.exit(1)

    # Step 3: Transcribe — platform CC or whisper fallback; decides mode
    print("\n[3/7] Transcribing audio / reading subtitles...")
    subs = transcribe(folder, whisper_model=whisper_model)
    mode = subs['mode']
    if force_image_mode and mode == 'subtitle_primary':
        print("  --force-image-mode set: overriding subtitle_primary → image_primary")
        mode = 'image_primary'

    if mode == 'subtitle_primary':
        # Subtitle path: no bulk frame capture. Pass 1 is text-only; frames
        # are extracted on demand in Pass 1.3 via extract_key_moments.py.
        print("\n[4/7] mode=subtitle_primary — skipping capture/filter/select")
        print(f"      Next: dispatch Pass 1 with plan_subtitle_pass1.py \"{folder}\"")
        print(f"      (Frames will be extracted on demand from key_moments.)")
        screenshots_dir = os.path.join(folder, 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)  # Pass 1.3 writes here
        print("\n[5/7] (skipped) filter_uninformative_frames")
        print("[6/7] (skipped) select_key_frames")
    else:
        # Image path: original pipeline
        if subs.get('sparse_reason'):
            print(f"  subtitles sparse ({subs['sparse_reason']}) — falling back to image_primary")
        if ppt_mode:
            print(f"\n[4/7] Capturing PPT-focused screenshots...")
            print(f"  Mode: PPT region detection")
            print(f"  Threshold: {threshold}")
            print(f"  Max depth: {max_depth}")
            screenshots_dir = os.path.join(folder, 'screenshots')
            frames = capture_ppt_frames(
                video_file, screenshots_dir,
                threshold=threshold,
                max_depth=max_depth,
                initial_interval=initial_interval
            )
            print(f"  Captured {len(frames)} frames")
        else:
            print(f"\n[4/7] Capturing screenshots (every {interval}s)...")
            screenshots_dir = os.path.join(folder, 'screenshots')
            capture_frames(video_file, screenshots_dir, interval)

        if not no_filter:
            print(f"\n[5/7] Flagging uninformative frames...")
            filter_frames(screenshots_dir)
        else:
            print(f"\n[5/7] Skipping uninformative-frame filter")

        if not no_key_select:
            print(f"\n[6/7] Selecting top {key_frames} key frames for LLM analysis...")
            select_key_frames(screenshots_dir, count=key_frames)
        else:
            print(f"\n[6/7] Skipping key frame selection (using all frames)")

    # Step 7: Generate draft scaffold (mode-agnostic)
    print("\n[7/7] Generating notes scaffold...")
    notes_path = generate_notes(folder, ppt_mode=ppt_mode)

    print("\n" + "=" * 60)
    print("Workflow complete!")
    print(f"Mode: {mode}")
    print(f"Output folder: {folder}")
    print(f"Notes scaffold: {notes_path}")
    if mode == 'subtitle_primary':
        print(f"Next step: python plan_subtitle_pass1.py \"{folder}\"")
    else:
        print(f"Next step: python plan_pass1_batches.py \"{folder}\"")
    print("=" * 60)

    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Video summarizer workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard mode (fixed interval)
  python run_workflow.py "https://www.youtube.com/watch?v=..."

  # PPT mode (recommended for tech talks)
  python run_workflow.py "https://www.bilibili.com/video/..." --ppt

  # High-sensitivity PPT mode
  python run_workflow.py "<url>" --ppt --threshold 0.02 --max-depth 8

  # Select only 50 key frames
  python run_workflow.py "<url>" --ppt --key-frames 50
        """
    )
    parser.add_argument('url', help='Video URL (Bilibili or YouTube)')
    parser.add_argument('--ppt', action='store_true',
                        help='Use PPT-focused capture mode')
    parser.add_argument('--interval', type=int, default=30,
                        help='Screenshot interval for standard mode (default: 30)')
    parser.add_argument('--threshold', type=float, default=0.03,
                        help='PPT change threshold (default: 0.03)')
    parser.add_argument('--max-depth', type=int, default=6,
                        help='Max recursion depth for PPT mode (default: 6)')
    parser.add_argument('--initial', type=int, default=10,
                        help='Initial sampling interval for PPT mode (default: 10)')
    parser.add_argument('--key-frames', type=int, default=100,
                        help='Number of key frames for LLM analysis (default: 100)')
    parser.add_argument('--no-key-select', action='store_true',
                        help='Skip key frame selection, use all frames')
    parser.add_argument('--no-filter', action='store_true',
                        help='Skip uninformative-frame filter step')
    parser.add_argument('--whisper-model', default='large-v3',
                        help='faster-whisper model size if subtitle falls back to ASR (default: large-v3)')
    parser.add_argument('--force-image-mode', action='store_true',
                        help='Ignore subtitles and force the image-primary pipeline')

    args = parser.parse_args()
    run_workflow(
        args.url,
        ppt_mode=args.ppt,
        interval=args.interval,
        threshold=args.threshold,
        max_depth=args.max_depth,
        initial_interval=args.initial,
        key_frames=args.key_frames,
        no_key_select=args.no_key_select,
        no_filter=args.no_filter,
        whisper_model=args.whisper_model,
        force_image_mode=args.force_image_mode,
    )
