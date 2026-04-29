#!/usr/bin/env python3
"""
Create a sanitized folder for video download based on URL.
Usage: python create_folder.py <video_url>
"""

import sys
import os
import re
import json
import urllib.parse
import urllib.request


def sanitize_filename(name: str) -> str:
    """Remove invalid characters for folder names."""
    # Remove/replace invalid chars
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', '_', name)
    name = name.strip('._')
    # Limit length
    if len(name) > 100:
        name = name[:100]
    return name


def extract_video_id(url: str) -> str:
    """Extract video ID from Bilibili or YouTube URL.
    Supports short links by following redirects.
    """
    # Handle short links by following redirects
    if 'b23.tv' in url or 't.cn' in url or 'bit.ly' in url:
        try:
            req = urllib.request.Request(url, method='HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=10) as resp:
                url = resp.geturl()
        except Exception:
            pass  # Fall through to try original URL

    parsed = urllib.parse.urlparse(url)

    # Bilibili
    if 'bilibili.com' in parsed.netloc or 'b23.tv' in parsed.netloc:
        match = re.search(r'BV\w+', url)
        if match:
            return match.group(0)
        match = re.search(r'av(\d+)', url)
        if match:
            return f"av{match.group(1)}"

    # YouTube
    if 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc:
        if parsed.netloc == 'youtu.be':
            return parsed.path.strip('/')
        query = urllib.parse.parse_qs(parsed.query)
        if 'v' in query:
            return query['v'][0]

    return "unknown"


def get_project_root() -> str:
    """Find project root by looking for .codebuddy directory."""
    current = os.path.dirname(os.path.abspath(__file__))
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, '.codebuddy')):
            return current
        current = os.path.dirname(current)
    return os.getcwd()


def extract_title_with_youget(url: str) -> str | None:
    """Try to get video title using you-get --json."""
    import shutil
    import subprocess
    import json

    if not shutil.which('you-get'):
        return None

    try:
        result = subprocess.run(
            ['you-get', '--json', url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        if isinstance(data, dict):
            return data.get('title')
        elif isinstance(data, list) and len(data) > 0:
            return data[0].get('title')
    except Exception:
        pass
    return None


def create_folder(url: str) -> str:
    """Create folder and return its path."""
    video_id = extract_video_id(url)

    # Try to get title: yt-dlp first, then you-get fallback
    title = None
    try:
        import yt_dlp
        ydl_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title')
    except Exception:
        pass

    if not title:
        title = extract_title_with_youget(url)

    if not title:
        title = video_id

    # Build folder name: first 30 chars of title + video_id
    title_part = sanitize_filename(title)[:30]
    folder_name = f"{title_part}_{video_id}"

    # Create folder in notes/ directory (project root level)
    project_root = get_project_root()
    notes_dir = os.path.join(project_root, 'notes')
    os.makedirs(notes_dir, exist_ok=True)
    folder_path = os.path.join(notes_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Save URL for later use
    with open(os.path.join(folder_path, 'url.txt'), 'w', encoding='utf-8') as f:
        f.write(url)

    print(folder_path)
    return folder_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python create_folder.py <video_url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    create_folder(url)
