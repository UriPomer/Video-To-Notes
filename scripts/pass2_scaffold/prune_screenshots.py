#!/usr/bin/env python3
"""
Prune unreferenced screenshots — keep only images embedded in notes.md.

After Pass 2 writes notes.md, the screenshots/ folder often contains far more
frames than the notes actually reference. This script reads notes.md, extracts
every `![…](screenshots/xxx.jpg)` path, and deletes any .jpg in screenshots/
that is NOT in that set.

Usage:
  python prune_screenshots.py <video_folder>

Arguments:
  video_folder   Path to the video output folder (contains notes.md + screenshots/)

Options:
  --dry-run      Print what would be deleted, but don't delete anything
  --verbose      Print every deleted filename

Example:
  python prune_screenshots.py notes/My_Video_BV12345
  python prune_screenshots.py notes/My_Video_BV12345 --dry-run
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Set


# ---------------------------------------------------------------------------
# Regex: match ![any text](screenshots/filename.jpg)
# Handles both forward-slash and backslash, with or without quotes.
# ---------------------------------------------------------------------------
_IMG_RE = re.compile(
    r'!\[.*?\]\(screenshots[/\\](.*?\.jpg)\)',
    re.IGNORECASE,
)


def referenced_images(notes_path: str) -> Set[str]:
    """Return the set of image filenames referenced in notes.md."""
    with open(notes_path, 'r', encoding='utf-8') as fh:
        text = fh.read()

    # Extract just the filename portion (strip any residual path)
    names: Set[str] = set()
    for match in _IMG_RE.findall(text):
        # match is e.g. "frame_0020_00.jpg" (already just filename,
        # but be safe and strip any path separators)
        names.add(os.path.basename(match))
    return names


def existing_screenshots(screenshots_dir: str) -> Set[str]:
    """Return the set of .jpg filenames that exist in screenshots/."""
    if not os.path.isdir(screenshots_dir):
        return set()
    return {
        f for f in os.listdir(screenshots_dir)
        if f.lower().endswith('.jpg')
    }


def prune(video_folder: str, dry_run: bool = False, verbose: bool = False) -> None:
    notes_path = os.path.join(video_folder, 'notes.md')
    screenshots_dir = os.path.join(video_folder, 'screenshots')

    # --- validate ---
    if not os.path.isfile(notes_path):
        print(f"Error: notes.md not found in {video_folder}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(screenshots_dir):
        print(f"Error: screenshots/ not found in {video_folder}", file=sys.stderr)
        sys.exit(1)

    # --- collect ---
    referenced = referenced_images(notes_path)
    existing = existing_screenshots(screenshots_dir)
    to_delete = existing - referenced

    # --- report ---
    print(f"notes.md references : {len(referenced)} images")
    print(f"screenshots/ contains: {len(existing)} images")
    print(f"unreferenced         : {len(to_delete)} images")

    if not to_delete:
        print("Nothing to prune.")
        return

    # --- delete ---
    deleted = 0
    for fname in sorted(to_delete):
        fpath = os.path.join(screenshots_dir, fname)
        if dry_run:
            print(f"  [dry-run] would delete: {fname}")
        else:
            try:
                os.remove(fpath)
                deleted += 1
                if verbose:
                    print(f"  deleted: {fname}")
            except OSError as exc:
                print(f"  Error deleting {fname}: {exc}", file=sys.stderr)

    if dry_run:
        print(f"[dry-run] Would delete {len(to_delete)} unreferenced images.")
    else:
        print(f"Deleted {deleted} unreferenced images, kept {len(referenced)} referenced.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Prune unreferenced screenshots from a video notes folder.'
    )
    parser.add_argument('video_folder', help='Path to the video output folder')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be deleted without deleting')
    parser.add_argument('--verbose', action='store_true',
                        help='Print every deleted filename')
    args = parser.parse_args()

    prune(args.video_folder, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == '__main__':
    main()
