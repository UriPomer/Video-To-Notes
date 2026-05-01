#!/usr/bin/env python3
"""
Produce subtitles.json for a downloaded video.

Three-level fallback:
  1. Use yt-dlp-downloaded CC (video.*.vtt) if present.
  2. Run faster-whisper on video.mp4's audio track if CC is absent.
  3. Write an empty subtitles.json with mode=image_primary if both fail.

Also computes sparsity signals and sets `mode` at the top of the JSON so
run_workflow.py can branch:
  - subtitle_primary: enough content, skip frame capture, drive Pass 1 from text
  - image_primary:    sparse/missing subtitles, fall back to frame-driven flow

Usage:
  python -u transcribe_audio.py <video_folder> [--whisper-model large-v3]

Output: <video_folder>/subtitles.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple


# Sparsity thresholds — promoted to constants for future tuning.
# Density is the main signal: very quiet videos or music videos fall below.
# Coverage catches the edge case where subtitles exist only in intro/outro.
MIN_CHAR_DENSITY_PER_MIN = 100
MIN_COVERAGE_RATIO = 0.5


def enable_live_logs() -> None:
    """Flush stdout/stderr line by line when output is captured by a tool."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(line_buffering=True, write_through=True)


# ----------------------------------------------------------------------
# VTT parsing
# ----------------------------------------------------------------------

_VTT_TIME_RE = re.compile(
    r'(\d+):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[.,](\d{3})'
)


def _ts_to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(path: str) -> List[Dict]:
    """Parse a WebVTT/SRT file into [{start, end, text}]. Stripped of styling."""
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()

    segments: List[Dict] = []
    # VTT/SRT share the cue header line; iterate on blank-line separated blocks
    for block in re.split(r'\n\s*\n', raw):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_line = None
        for i, ln in enumerate(lines):
            if _VTT_TIME_RE.search(ln):
                time_line = i
                break
        if time_line is None:
            continue
        m = _VTT_TIME_RE.search(lines[time_line])
        if not m:
            continue
        start = _ts_to_sec(*m.group(1, 2, 3, 4))
        end = _ts_to_sec(*m.group(5, 6, 7, 8))
        text_lines = lines[time_line + 1:]
        # Strip WebVTT cue tags like <c.colorFFFFFF>, <v Speaker>, etc.
        text = '\n'.join(text_lines)
        text = re.sub(r'<[^>]+>', '', text).strip()
        if not text:
            continue
        segments.append({'start': start, 'end': end, 'text': text})

    # Deduplicate consecutive same-text cues (yt-dlp auto-subs often repeat
    # the previous line as the new line rolls in).
    deduped: List[Dict] = []
    for seg in segments:
        if deduped and deduped[-1]['text'] == seg['text']:
            deduped[-1]['end'] = seg['end']
            continue
        deduped.append(seg)
    return deduped


# ----------------------------------------------------------------------
# Subtitle discovery
# ----------------------------------------------------------------------

def find_platform_subtitle(video_folder: str) -> Optional[Tuple[str, str, str]]:
    """Return (vtt_path, source_tag, lang) if yt-dlp left a subtitle file.

    Prefers manual CC over auto-generated; prefers Chinese over English.
    """
    # yt-dlp names: video.<lang>.vtt, video.<lang>.srt
    # Auto-generated ones usually have lang like 'en-orig' or 'zh-Hans-en'
    candidates: List[Tuple[str, str]] = []  # (path, lang)
    for fn in os.listdir(video_folder):
        m = re.match(r'video\.([\w-]+)\.(vtt|srt)$', fn)
        if m:
            candidates.append((os.path.join(video_folder, fn), m.group(1)))

    if not candidates:
        return None

    # Priority order: manual Chinese, manual English, any auto-CC
    def score(lang: str) -> int:
        lang_lower = lang.lower()
        if lang_lower.startswith('zh'):
            return 100 if 'auto' not in lang_lower else 80
        if lang_lower.startswith('en'):
            return 60 if 'auto' not in lang_lower else 50
        return 10

    candidates.sort(key=lambda p: score(p[1]), reverse=True)
    best_path, best_lang = candidates[0]
    source = 'platform_cc'
    return best_path, source, best_lang


# ----------------------------------------------------------------------
# Whisper fallback
# ----------------------------------------------------------------------

def _run_whisper_in_process(
    video_file: str,
    model_size: str,
    device: str,
    compute_type: str,
) -> Tuple[List[Dict], str]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip install faster-whisper"
        ) from e

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        video_file, beam_size=5,
        vad_filter=True,
        vad_parameters={'min_silence_duration_ms': 500},
    )

    segs: List[Dict] = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        segs.append({'start': float(seg.start), 'end': float(seg.end), 'text': text})
    return segs, info.language



def _run_whisper_isolated(
    video_file: str,
    model_size: str,
    device: str,
    compute_type: str,
) -> Tuple[List[Dict], str]:
    fd, output_json = tempfile.mkstemp(prefix='whisper_', suffix='.json')
    os.close(fd)
    try:
        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            '--internal-whisper',
            '--video-file',
            video_file,
            '--whisper-model',
            model_size,
            '--device',
            device,
            '--compute-type',
            compute_type,
            '--output-json',
            output_json,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
                or f'worker exited with code {result.returncode}'
            )
            raise RuntimeError(detail)

        with open(output_json, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        return payload['segments'], payload['language']
    finally:
        if os.path.exists(output_json):
            os.unlink(output_json)



def run_whisper(video_file: str, model_size: str = 'large-v3') -> Tuple[List[Dict], str]:
    """Transcribe video audio with faster-whisper.

    Returns (segments, detected_language).

    Raises RuntimeError if faster-whisper isn't installed or ffmpeg extract
    fails. Caller decides whether to fall back to image_primary.
    """
    # GPU failures on Windows can terminate the Python process inside native
    # code before Python raises an exception. Run the GPU path in an isolated
    # worker so the parent process can always fall back to CPU cleanly.
    print(f"[transcribe_audio] loading whisper model on GPU ({model_size})...", flush=True)
    try:
        return _run_whisper_isolated(video_file, model_size, 'cuda', 'float16')
    except RuntimeError as gpu_err:
        print(
            f"[transcribe_audio] GPU failed ({gpu_err}); continuing on CPU; no retry needed.",
            file=sys.stderr,
            flush=True,
        )
        print(f"[transcribe_audio] loading whisper model on CPU ({model_size})...", flush=True)
        return _run_whisper_in_process(video_file, model_size, 'cpu', 'int8')


# ----------------------------------------------------------------------
# Video duration (for coverage math)
# ----------------------------------------------------------------------

def probe_duration(video_file: str) -> float:
    """Use ffprobe to get video duration in seconds."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_file,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


# ----------------------------------------------------------------------
# Sparsity evaluation
# ----------------------------------------------------------------------

def evaluate_sparsity(segments: List[Dict], duration_sec: float) -> Dict:
    """Compute density, coverage; decide mode."""
    total_chars = sum(len(s['text']) for s in segments)
    covered_sec = sum(max(0.0, s['end'] - s['start']) for s in segments)

    duration_min = max(1e-6, duration_sec / 60.0)
    density = total_chars / duration_min
    coverage = (covered_sec / duration_sec) if duration_sec > 0 else 0.0

    reasons = []
    if density < MIN_CHAR_DENSITY_PER_MIN:
        reasons.append(f"density {density:.1f} < {MIN_CHAR_DENSITY_PER_MIN}")
    if coverage < MIN_COVERAGE_RATIO:
        reasons.append(f"coverage {coverage:.2f} < {MIN_COVERAGE_RATIO}")

    mode = 'image_primary' if reasons else 'subtitle_primary'
    return {
        'mode': mode,
        'total_chars': total_chars,
        'duration_sec': duration_sec,
        'char_density_per_min': round(density, 1),
        'coverage_ratio': round(coverage, 3),
        'sparse_reason': '; '.join(reasons) if reasons else None,
    }


# ----------------------------------------------------------------------
# Entry
# ----------------------------------------------------------------------

def locate_video_file(video_folder: str) -> Optional[str]:
    for ext in ('mp4', 'webm', 'mkv', 'flv'):
        p = os.path.join(video_folder, f'video.{ext}')
        if os.path.exists(p):
            return p
    return None


def transcribe(video_folder: str, whisper_model: str = 'large-v3') -> Dict:
    enable_live_logs()
    video_folder = os.path.abspath(video_folder)
    video_file = locate_video_file(video_folder)

    duration = probe_duration(video_file) if video_file else 0.0

    segments: List[Dict] = []
    source = 'none'
    lang = 'unknown'

    # Level 1: platform CC
    platform = find_platform_subtitle(video_folder)
    if platform:
        vtt_path, source, lang = platform
        print(f"[transcribe_audio] using platform subtitle: {os.path.basename(vtt_path)}", flush=True)
        segments = parse_vtt(vtt_path)

    # Level 2: faster-whisper if nothing found
    if not segments and video_file:
        print(f"[transcribe_audio] no platform subtitle; running whisper ({whisper_model})...", flush=True)
        try:
            segments, lang = run_whisper(video_file, model_size=whisper_model)
            source = 'whisper_local'
        except RuntimeError as e:
            print(f"[transcribe_audio] whisper unavailable: {e}", file=sys.stderr, flush=True)
            print(
                "[transcribe_audio] ACTION REQUIRED: install faster-whisper to enable ASR transcription.\n"
                "  pip install faster-whisper\n"
                "Bilibili videos almost never have CC subtitles, so faster-whisper is the\n"
                "primary subtitle source for them. Without it, the pipeline falls back to\n"
                "image_primary mode which consumes ~3-4x more tokens.",
                file=sys.stderr,
                flush=True,
            )
            source = 'none'

    # If ffprobe couldn't read duration (e.g. missing video file), fall back
    # to the last segment timestamp. Without this, density is divided by
    # near-zero and explodes.
    if duration <= 0 and segments:
        duration = max(s['end'] for s in segments)

    # Level 3: nothing worked → empty subtitles, force image_primary
    stats = evaluate_sparsity(segments, duration)
    if source == 'none':
        stats['mode'] = 'image_primary'
        stats['sparse_reason'] = (stats.get('sparse_reason') or '') + '; no subtitle source'
        stats['sparse_reason'] = stats['sparse_reason'].lstrip('; ')

    payload = {
        'mode': stats['mode'],
        'source': source,
        'lang': lang,
        'total_chars': stats['total_chars'],
        'duration_sec': stats['duration_sec'],
        'char_density_per_min': stats['char_density_per_min'],
        'coverage_ratio': stats['coverage_ratio'],
        'sparse_reason': stats['sparse_reason'],
        'segments': segments,
    }

    out_path = os.path.join(video_folder, 'subtitles.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[transcribe_audio] mode={payload['mode']} source={source} "
          f"chars={payload['total_chars']} density={payload['char_density_per_min']} "
          f"coverage={payload['coverage_ratio']}", flush=True)
    print(f"[transcribe_audio] wrote {out_path}", flush=True)
    return payload


def main():
    parser = argparse.ArgumentParser(description='Produce subtitles.json with mode decision')
    parser.add_argument('video_folder', nargs='?', help='Folder containing video.mp4 and (optional) video.<lang>.vtt')
    parser.add_argument('--whisper-model', default='large-v3',
                        help='faster-whisper model size (tiny/base/small/medium/large-v3). Default: large-v3')
    parser.add_argument('--internal-whisper', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--video-file', help=argparse.SUPPRESS)
    parser.add_argument('--device', help=argparse.SUPPRESS)
    parser.add_argument('--compute-type', help=argparse.SUPPRESS)
    parser.add_argument('--output-json', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.internal_whisper:
        if not all([args.video_file, args.device, args.compute_type, args.output_json]):
            parser.error('--internal-whisper requires --video-file, --device, --compute-type, and --output-json')
        segments, language = _run_whisper_in_process(
            args.video_file,
            args.whisper_model,
            args.device,
            args.compute_type,
        )
        with open(args.output_json, 'w', encoding='utf-8') as f:
            json.dump({'segments': segments, 'language': language}, f, ensure_ascii=False)
        return

    if not args.video_folder:
        parser.error('video_folder is required unless --internal-whisper is set')
    transcribe(args.video_folder, whisper_model=args.whisper_model)


if __name__ == '__main__':
    main()
