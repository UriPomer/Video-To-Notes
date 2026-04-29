#!/usr/bin/env python3
"""
Generate rich notes from video metadata and key frames.
Uses LLM visual analysis via key_frames.json (no OCR dependency).

Usage: python generate_notes.py <folder_path> [--ppt]
"""

import sys
import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    seconds = int(seconds)
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def parse_frame_timestamp(filename: str) -> Optional[float]:
    match = re.search(r'frame_(\d+)_(\d+)', filename)
    if match:
        secs = int(match.group(1))
        cents = int(match.group(2))
        return secs + cents / 100.0
    match = re.search(r'frame_(\d+)', filename)
    if match:
        return float(match.group(1))
    return None


def load_key_frames(folder_path: str) -> Optional[Dict]:
    """Load key_frames.json if available."""
    key_frames_path = os.path.join(folder_path, 'key_frames.json')
    if os.path.exists(key_frames_path):
        with open(key_frames_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def list_all_screenshots(folder_path: str, ppt_mode: bool = False) -> List[Dict]:
    """List all screenshots with metadata."""
    if ppt_mode:
        screenshots_dir = os.path.join(folder_path, 'screenshots')
    else:
        screenshots_dir = os.path.join(folder_path, 'screenshots')

    if not os.path.exists(screenshots_dir):
        return []

    screenshots = []
    for f in sorted(os.listdir(screenshots_dir)):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            filepath = os.path.join(screenshots_dir, f)
            ts = parse_frame_timestamp(f)
            rel_path = os.path.join(
                os.path.basename(screenshots_dir), f
            ).replace('\\', '/')
            screenshots.append({
                'filename': f,
                'filepath': filepath,
                'rel_path': rel_path,
                'timestamp': ts if ts is not None else 0,
            })

    return screenshots


def generate_notes(folder_path: str, ppt_mode: bool = False) -> str:
    """Generate notes template. Uses key_frames if available, otherwise all screenshots."""
    metadata_path = os.path.join(folder_path, 'metadata.json')

    # Load metadata
    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

    # Try to load key frames (LLM-optimized selection)
    key_frames_data = load_key_frames(folder_path)

    # Build a filename -> score map for the frame index (if available)
    score_map: Dict[str, Dict] = {}
    if key_frames_data:
        for f in key_frames_data.get('frames', []):
            score_map[f['filename']] = f

    # Load filter_uninformative_frames.py output if present (filename -> reasons)
    skip_map: Dict[str, List[str]] = {}
    # skip list lives under <folder>/screenshots/frames_to_skip.json
    skip_json = os.path.join(folder_path, 'screenshots', 'frames_to_skip.json')
    if os.path.exists(skip_json):
        try:
            with open(skip_json, 'r', encoding='utf-8') as f:
                sdata = json.load(f)
            skip_map = sdata.get('skip', {})
        except Exception:
            pass

    # Determine which screenshots to include
    if key_frames_data:
        screenshots_dir = key_frames_data.get('folder', '')
        key_filenames = {f['filename'] for f in key_frames_data.get('frames', [])}
        all_screenshots = list_all_screenshots(folder_path, ppt_mode)
        screenshots = [s for s in all_screenshots if s['filename'] in key_filenames]
        screenshots.sort(key=lambda x: x['timestamp'])
        selection_info = f"Key frames ({len(screenshots)} selected from {key_frames_data.get('total_frames', 0)})"
    else:
        screenshots = list_all_screenshots(folder_path, ppt_mode)
        selection_info = f"All frames ({len(screenshots)})"

    # Extract info
    title = metadata.get('title', 'Unknown Title')
    description = metadata.get('description', '')
    uploader = metadata.get('uploader', 'Unknown')
    upload_date = metadata.get('upload_date', '')
    duration = metadata.get('duration', 0)
    webpage_url = metadata.get('webpage_url', '')
    tags = metadata.get('tags', [])
    duration_str = format_timestamp(duration) if duration else "Unknown"

    # Generate notes
    notes = f"""# {title}

> **来源**: [{webpage_url}]({webpage_url})
> **作者**: {uploader} | **日期**: {upload_date} | **时长**: {duration_str}
> **标签**: {', '.join(tags) if tags else 'None'}

<!--
================================================================================
DRAFT SCAFFOLD — AGENT MUST REWRITE THIS FILE.

Do NOT ship notes in this skeleton form. Follow the Three-Pass workflow in
`.codebuddy/skills/video-summarizer/SKILL.md`:

  Pass 1  : plan_pass1_batches.py + N parallel sub-agents → pass1_scan.json
  Pass 1.5: resolve_gaps.py + round-2 sub-agents (for gap_suspicions)
  Pass 2  : write one H2 per topic, flat structure, finish with a
            meta-level 总结与启发.

Hard rules (violating any of these == BAD notes):
  - Flat document layout: 视频简介 → 内容结构 → topics → 总结与启发.
    NO "核心技术要点" card list between ToC and 正文 (duplicates content).
  - No "待深入研究的问题" section (R6). Resolve questions yourself, or
    inline them as *（演讲中未展开：...）* inside the relevant topic.
  - 总结与启发 is meta-level only: cross-cutting patterns, abstractions,
    reusable rules — not a re-summary of the topics above.

Reference example (ships with the skill):
  .codebuddy/skills/video-summarizer/examples/good_notes_phasmophobia.md

Anti-patterns and self-check list: SKILL.md.
================================================================================
-->

---

## 视频简介

<!-- 2-3 句话的核心信息。不要直接粘贴 description，要提炼演讲的真实主张。 -->

原始描述（供参考，通常需要重写）：

{description}

---

## 内容结构

<!--
使用 TOPIC-BASED 章节，不要使用统一的 5 分钟时间段。
扫描下方 Frame Index 表，找到 slide title cards（如 "Sensor Toolkit"、"AutoProp"），
用它们作为本表和下方 H2 小节的标题。
-->

| 章节（按演讲主题） | 起止时间 | 关键 frame |
|------|----------|----------|
| 1. <主题名> | MM:SS - MM:SS | frame_XXXX |
| 2. <主题名> | MM:SS - MM:SS | frame_XXXX |
| 3. <主题名> | MM:SS - MM:SS | frame_XXXX |

---

## 正文

<!--
按上方「内容结构」的 TOPIC-BASED 章节写作。每个 H2 小节包含：
  - 1-5 张最有信息量的截图（Pass 1 中筛选过的）
  - 从截图转写的原文（slide 标题、Inspector 参数、代码、思维导图节点等）
  - 末尾一段 **技术要点 / 设计意图** 综合

文档结构保持「扁平」——不要在 ToC 和正文之间插入「核心技术要点」卡片列表，
那会重复正文和「总结与启发」的内容（R-anti-pattern 7 / S9）。

示例：

## 2. Sensor Toolkit（传感器工具包）

### 2.1 系统概览

![Sensor toolkit 总览](screenshots/frame_0320_00.jpg)

幻灯片列出的核心特性：

| 特性 | 说明 |
|------|------|
| AI and equipment | 同时为 AI 与装备提供感知 |
| No triggers required | 不依赖 Unity 触发器 |
| ... | ... |

**设计意图**: 将持续碰撞检测改为脉冲式查询，显著降低 CPU 开销 ...
-->

（开始撰写正文……）

---

## 总结与启发

<!--
Meta 级观察——不是正文的再次复述。列出：
  - 讲者没有显式说出的横截面规律（跨越多个 topic 的共性）
  - 可复用抽象，格式："当 X 场景时，做 Y，因为 Z"（不只是技术名字）
  - 将讲者的经验迁移到其他领域的方式

如果写出来的每一条都在正文里已经原文出现过——就重写。

⚠️ 不要创建「待深入研究 / Open Questions / Future Work」小节（R6）。
如果演讲中有疑问，要么当场解决（再 Read 几帧 / 跑 resolve_gaps），
要么就在对应 topic 末尾用 *（演讲中未展开：…）* 一行标注。
-->

（开始撰写总结……）

---

## 帧索引（Frame Index）

<!--
本表按时间顺序列出所有候选帧，附带 select_key_frames.py 计算的分数：
  - diff      = 与前一帧的变化幅度（slide 换片时高）
  - density   = 基于文件大小估算的文字/细节密度
  - score     = diff * density，越高越值得看
  - skip?     = filter_uninformative_frames.py 标记的黑屏/重复/低边缘帧

Pass 1 建议顺序：
  1. 先看 skip? 为空、score 最高的前 20-30 帧 → 往往是 slide title cards
  2. 再按时间顺序浏览剩余帧，补齐每个 topic 的细节
  3. 标 skip? 的帧默认 **不要嵌入正文**；确认后可移除本表对应行
-->

| 时间戳 | 文件名 | score | diff | density | skip? |
|--------|--------|-------|------|---------|-------|
"""

    for ss in screenshots:
        ts = ss['timestamp']
        time_str = format_timestamp(ts)
        s = score_map.get(ss['filename'], {})
        score = s.get('combined_score', '')
        diff = s.get('diff_score', '')
        density = s.get('text_density', '')
        skip_reasons = skip_map.get(ss['filename'], [])
        skip_cell = ', '.join(skip_reasons) if skip_reasons else ''
        notes += (
            f"| `{time_str}` | [{ss['filename']}]({ss['rel_path']}) "
            f"| {score} | {diff} | {density} | {skip_cell} |\n"
        )

    notes += f"""

---

## 元数据

- **笔记生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **截图模式**: {'PPT区域检测' if ppt_mode else '固定间隔'}
- **候选帧数量**: {len(screenshots)}
- **帧选择策略**: {selection_info}
- **视频时长**: {duration_str}

---

*本笔记的骨架由 Video Summarizer Skill 自动生成；正文由 agent 基于截图视觉分析撰写。*
"""

    # Write notes
    notes_path = os.path.join(folder_path, 'notes.md')
    with open(notes_path, 'w', encoding='utf-8') as f:
        f.write(notes)

    print(f"Notes generated: {notes_path}")
    print(f"  Screenshots: {len(screenshots)}")
    print(f"  Selection: {selection_info}")
    print(f"  Mode: {'PPT-focused' if ppt_mode else 'Standard'}")
    return notes_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python generate_notes.py <folder_path> [--ppt]", file=sys.stderr)
        sys.exit(1)

    folder_path = sys.argv[1]
    ppt_mode = '--ppt' in sys.argv
    generate_notes(folder_path, ppt_mode)
