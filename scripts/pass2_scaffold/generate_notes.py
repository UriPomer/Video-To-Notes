#!/usr/bin/env python3
"""生成供 agent 完成的合法中文笔记草稿，不覆盖最终 notes.md。"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_ROOT = os.path.dirname(_HERE)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from common.utils import format_ts  # noqa: E402


def generate_notes(folder_path: str, ppt_mode: bool = False) -> str:
    """写入 notes.draft.md；已有 notes.md 永远不受影响。"""
    folder_path = os.path.abspath(folder_path)
    metadata_path = os.path.join(folder_path, 'metadata.json')
    metadata = {}
    if os.path.isfile(metadata_path):
        with open(metadata_path, 'r', encoding='utf-8') as handle:
            metadata = json.load(handle)

    title = metadata.get('title') or '视频标题（待核对）'
    url = metadata.get('webpage_url') or metadata.get('url') or ''
    uploader = metadata.get('uploader') or '待核对'
    upload_date = metadata.get('upload_date') or '待核对'
    duration = metadata.get('duration') or 0
    duration_text = format_ts(duration) if duration else '待核对'
    tags = metadata.get('tags') or []
    tag_text = '、'.join(tags[:8]) if tags else '待提炼'

    draft = f"""# {title}

> **来源**: [{url}]({url})
> **作者**: {uploader} | **日期**: {upload_date} | **时长**: {duration_text}
> **标签**: {tag_text}

## 视频简介

（根据字幕、画面和演讲主张提炼 2—3 句话；不要照抄视频简介。）

## 内容结构

| 章节 | 核心问题 | 主要证据 |
|------|----------|----------|
| 1. 主题名称 | 本节回答的问题 | 字幕时间段或关键画面 |

## 1. 主题名称

### 1.1 子主题名称

![说明图片传达的技术信息](screenshots/选择一张实际存在的图片.jpg)

（忠实整理可见文字、参数、代码、表格或图示，并结合字幕解释其设计意图。）

**技术要点 / 设计意图**: （提炼机制、取舍和适用条件。）

## 总结与启发

（提炼跨章节规律、可迁移方法和边界条件，不要重复目录。）
"""

    draft_path = os.path.join(folder_path, 'notes.draft.md')
    with open(draft_path, 'w', encoding='utf-8') as handle:
        handle.write(draft)

    print(f"已生成中文笔记草稿: {draft_path}")
    print("请基于证据完成并另存为 notes.md；notes.draft.md 不能作为最终交付。")
    print(f"截图模式: {'PPT/幻灯片' if ppt_mode else '标准'}")
    return draft_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python generate_notes.py <视频目录> [--ppt]', file=sys.stderr)
        sys.exit(1)
    generate_notes(sys.argv[1], '--ppt' in sys.argv)
