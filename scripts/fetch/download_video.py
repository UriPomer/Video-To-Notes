#!/usr/bin/env python3
"""
Download video and metadata from Bilibili/YouTube.
Uses yt-dlp by default, falls back to you-get for Bilibili (avoids 412 errors).

Usage: python download_video.py <video_url> <output_folder>
"""

import sys
import os
import json
import re
import subprocess
import shutil


def download_with_ytdlp(url: str, output_folder: str) -> dict:
    """Download using yt-dlp."""
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp not installed")

    os.makedirs(output_folder, exist_ok=True)

    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(output_folder, 'video.%(ext)s'),
        'writeinfojson': True,
        'writethumbnail': True,
        # Subtitles: try manual CC first, then auto-generated; saved as .vtt
        # next to video.mp4. transcribe_audio.py picks these up before
        # falling back to faster-whisper.
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['zh-Hans', 'zh', 'zh-CN', 'en', 'en-US'],
        'subtitlesformat': 'vtt',
        'quiet': False,
        'no_warnings': False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        metadata = {
            'title': info.get('title', ''),
            'description': info.get('description', ''),
            'uploader': info.get('uploader', ''),
            'uploader_id': info.get('uploader_id', ''),
            'upload_date': info.get('upload_date', ''),
            'duration': info.get('duration', 0),
            'view_count': info.get('view_count', 0),
            'like_count': info.get('like_count', 0),
            'webpage_url': info.get('webpage_url', url),
            'thumbnail': info.get('thumbnail', ''),
            'tags': info.get('tags', []),
            'categories': info.get('categories', []),
        }

        metadata_path = os.path.join(output_folder, 'metadata.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # Find video file
        video_file = None
        for ext in ['mp4', 'webm', 'mkv', 'flv']:
            candidate = os.path.join(output_folder, f'video.{ext}')
            if os.path.exists(candidate):
                video_file = candidate
                break

        # Rename thumbnail
        for ext in ['jpg', 'webp', 'png']:
            thumb_src = os.path.join(output_folder, f'video.{ext}')
            if os.path.exists(thumb_src):
                thumb_dst = os.path.join(output_folder, 'thumbnail.jpg')
                os.rename(thumb_src, thumb_dst)
                break

        return metadata, video_file


def download_with_youget(url: str, output_folder: str) -> dict:
    """Download Bilibili video using you-get."""
    if not shutil.which('you-get'):
        raise RuntimeError("you-get not installed. Run: pip install you-get")

    os.makedirs(output_folder, exist_ok=True)

    # Download with you-get
    cmd = [
        'you-get',
        '--format=dash-flv480-AVC',
        '-o', output_folder,
        '-O', 'video',
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"you-get failed: {result.stderr}")

    # you-get may produce multiple segments, merge them
    video_file = merge_video_segments(output_folder)

    # Try to get metadata from yt-dlp without downloading
    metadata = extract_metadata_only(url)
    metadata_path = os.path.join(output_folder, 'metadata.json')
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return metadata, video_file


def merge_video_segments(output_folder: str) -> str:
    """Merge video[00].mp4, video[01].mp4 etc into video.mp4."""
    segments = sorted([
        f for f in os.listdir(output_folder)
        if re.match(r'video\[\d+\]\.mp4', f)
    ])

    if not segments:
        # Check if video.mp4 already exists
        direct = os.path.join(output_folder, 'video.mp4')
        if os.path.exists(direct):
            return direct
        return None

    if len(segments) == 1:
        src = os.path.join(output_folder, segments[0])
        dst = os.path.join(output_folder, 'video.mp4')
        os.rename(src, dst)
        return dst

    # Multiple segments - use ffmpeg concat
    concat_file = os.path.join(output_folder, 'concat_list.txt')
    with open(concat_file, 'w', encoding='utf-8') as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    output_file = os.path.join(output_folder, 'video.mp4')
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', concat_file, '-c', 'copy', output_file
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: just use first segment
        src = os.path.join(output_folder, segments[0])
        os.rename(src, output_file)

    # Cleanup
    if os.path.exists(concat_file):
        os.remove(concat_file)
    for seg in segments:
        seg_path = os.path.join(output_folder, seg)
        if os.path.exists(seg_path) and seg_path != output_file:
            os.remove(seg_path)

    return output_file


def extract_metadata_only(url: str) -> dict:
    """Extract metadata without downloading."""
    try:
        import yt_dlp
        ydl_opts = {'quiet': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', ''),
                'description': info.get('description', ''),
                'uploader': info.get('uploader', ''),
                'uploader_id': info.get('uploader_id', ''),
                'upload_date': info.get('upload_date', ''),
                'duration': info.get('duration', 0),
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
                'webpage_url': info.get('webpage_url', url),
                'thumbnail': info.get('thumbnail', ''),
                'tags': info.get('tags', []),
                'categories': info.get('categories', []),
            }
    except Exception:
        return {
            'title': '', 'description': '', 'uploader': '',
            'webpage_url': url, 'tags': []
        }


def download_video(url: str, output_folder: str) -> dict:
    """Download video with automatic fallback."""
    is_bilibili = 'bilibili.com' in url or 'b23.tv' in url

    # Try yt-dlp first for YouTube, but for Bilibili likely to fail
    if not is_bilibili:
        try:
            print("Trying yt-dlp...")
            metadata, video_file = download_with_ytdlp(url, output_folder)
            print(f"Downloaded: {video_file}")
            return metadata
        except Exception as e:
            print(f"yt-dlp failed: {e}")

    # For Bilibili, try you-get directly
    if is_bilibili:
        try:
            print("Using you-get for Bilibili...")
            metadata, video_file = download_with_youget(url, output_folder)
            print(f"Downloaded: {video_file}")
            return metadata
        except Exception as e:
            print(f"you-get failed: {e}")

    # Last resort: try yt-dlp anyway
    try:
        print("Trying yt-dlp as fallback...")
        metadata, video_file = download_with_ytdlp(url, output_folder)
        print(f"Downloaded: {video_file}")
        return metadata
    except Exception as e:
        print(f"All download methods failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    import re
    if len(sys.argv) < 3:
        print("Usage: python download_video.py <video_url> <output_folder>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    output_folder = sys.argv[2]
    download_video(url, output_folder)
