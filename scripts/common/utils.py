"""Shared utilities across video-summarizer pipeline stages.

Anything imported by more than one script lives here so phase modules
don't need to cross-import from each other.
"""

import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional


# ----------------------------------------------------------------------
# Video file helpers
# ----------------------------------------------------------------------

VIDEO_EXTENSIONS = ('mp4', 'webm', 'mkv', 'flv')


def locate_video_file(video_folder: str) -> Optional[str]:
    """Find video.* in the given folder, trying common extensions."""
    for ext in VIDEO_EXTENSIONS:
        p = os.path.join(video_folder, f'video.{ext}')
        if os.path.exists(p):
            return p
    return None


def probe_duration(video_file: str) -> float:
    """Use ffprobe to get video duration in seconds. Returns 0.0 on failure."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_file,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 0.0


def capture_frame_ffmpeg(video_path: str, ts: float, output_file: str,
                         scale: int = 0) -> bool:
    """Capture a single frame using ffmpeg.

    If scale > 0, output is resized to that width; otherwise original size.
    """
    cmd = [
        'ffmpeg', '-y', '-ss', str(ts),
        '-i', video_path,
        '-vframes', '1',
    ]
    if scale > 0:
        cmd += ['-vf', f'scale={scale}:-1', '-q:v', '1']
    else:
        cmd += ['-q:v', '2']
    cmd.append(output_file)
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return os.path.exists(output_file)
    except subprocess.CalledProcessError:
        return False


# ----------------------------------------------------------------------
# Timestamp + JSON helpers
# ----------------------------------------------------------------------

def format_ts(sec: float) -> str:
    """Format seconds as H:MM:SS or MM:SS."""
    sec = int(sec)
    hrs = sec // 3600
    mins = (sec % 3600) // 60
    secs = sec % 60
    if hrs:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def load_json(path: str, default):
    """Read JSON, return `default` if the file doesn't exist."""
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------
# Filename timestamp parsing
# ----------------------------------------------------------------------

_FRAME_TS_RE = re.compile(r'frame_(\d+)_(\d+)')
_FRAME_TS_SIMPLE_RE = re.compile(r'frame_(\d+)')


def parse_frame_timestamp(filename: str) -> Optional[float]:
    """Extract timestamp in seconds from a screenshot filename.

    Supports: frame_NNNN_MM.jpg, frame_NNNN.jpg, gap_SSSS_EEEE_NNN.jpg
    """
    m = _FRAME_TS_RE.search(filename)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 100.0
    m = _FRAME_TS_SIMPLE_RE.search(filename)
    if m:
        return float(m.group(1))
    # gap_0320_0400_003.jpg — approximate for sort ordering
    gm = re.match(r'gap_(\d+)_(\d+)_(\d+)\.jpg$', filename)
    if gm:
        start = int(gm.group(1))
        idx = int(gm.group(3))
        return float(start) + (idx - 1) * 2
    return None


# ----------------------------------------------------------------------
# Image classification helpers
# Lazy-import opencv/numpy so pure-text scripts don't pay the import cost.
# ----------------------------------------------------------------------

# Tuned against the Phasmophobia / Nikki sample sets.
BLACK_MEAN = 15.0       # 0-255: below this = very dark
BLACK_STD = 10.0        # low std on top of low mean = flat black
LOW_VAR_STD = 8.0       # overall std: blank slide, single-color card
LOW_EDGE = 4.0          # mean |Sobel|: no text / line art
DUP_DIFF = 2.5          # mean abs diff vs previous non-skipped frame
DOWNSCALE_WIDTH = 320   # analysis resolution (speed)


def _require_cv2():
    try:
        import cv2  # noqa: F401
        import numpy as np  # noqa: F401
    except ImportError as e:
        print(f"Error: opencv-python and numpy are required ({e})", file=sys.stderr)
        sys.exit(1)


def load_gray(path: str, width: int = DOWNSCALE_WIDTH):
    """Read image as grayscale, downscale for fast analysis."""
    _require_cv2()
    import cv2
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape
    if w > width:
        scale = width / w
        img = cv2.resize(img, (width, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _edge_magnitude(gray) -> float:
    import cv2
    import numpy as np
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    return float(mag.mean())


def classify(gray, prev_gray) -> List[str]:
    """Return list of reasons this frame is uninformative (empty = keep)."""
    import numpy as np
    reasons: List[str] = []

    mean = float(gray.mean())
    std = float(gray.std())
    if mean < BLACK_MEAN and std < BLACK_STD:
        reasons.append("black")
    if std < LOW_VAR_STD:
        reasons.append("low_variance")

    edge = _edge_magnitude(gray)
    if edge < LOW_EDGE:
        reasons.append("low_edge")

    if prev_gray is not None and prev_gray.shape == gray.shape:
        diff = float(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)).mean())
        if diff < DUP_DIFF:
            reasons.append("near_duplicate")

    return reasons
