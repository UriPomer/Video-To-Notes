#!/usr/bin/env python3
"""验证 notes.md 是否达到 video-summarizer 的确定性交付标准。"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

ALL_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)', re.IGNORECASE)
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\((screenshots[/\\][^)]+)\)', re.IGNORECASE)
TOPIC_RE = re.compile(r'^##\s+\d+\.\s+.+$', re.MULTILINE)
H2_RE = re.compile(r'^##\s+.+$', re.MULTILINE)
FORBIDDEN = (
    ('帧索引', re.compile(r'^##\s+.*帧索引', re.MULTILINE | re.IGNORECASE)),
    ('元数据章节', re.compile(r'^##\s+元数据\s*$', re.MULTILINE)),
    ('待深入研究章节', re.compile(r'^##\s+.*待深入研究', re.MULTILINE)),
    ('草稿内部指令', re.compile(r'DRAFT SCAFFOLD|AGENT MUST REWRITE|Agent Write Contract', re.IGNORECASE)),
)
PLACEHOLDERS = (
    '视频标题（待核对）', '（根据字幕、画面和演讲主张提炼',
    '主题名称', '子主题名称', '选择一张实际存在的图片.jpg',
    '（忠实整理', '（提炼机制', '（提炼跨章节规律',
)
HEADER_FIELDS = ('来源', '作者', '日期', '时长', '标签')


def _sections(text: str) -> List[Tuple[str, str]]:
    matches = list(H2_RE.finditer(text))
    return [
        (match.group(0), text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)])
        for i, match in enumerate(matches)
    ]


def _check_header(text: str, errors: List[str]) -> None:
    header = text.split('## 视频简介', 1)[0]
    for field in HEADER_FIELDS:
        names = '作者|演讲者' if field == '作者' else field
        match = re.search(rf'(?:\*\*)?(?:{names})(?:\*\*)?\s*[:：]\s*([^\n|]+)', header)
        if not match or not match.group(1).strip():
            errors.append(f'头部缺少字段或值为空: {field}')
        elif match.group(1).strip() in ('待核对', '待提炼'):
            errors.append(f'头部仍包含草稿占位值: {field}')


def _check_scan(scan: dict, plan: dict, referenced: set, errors: List[str]) -> None:
    if scan.get('plan_type') != plan.get('plan_type'):
        errors.append('pass1_scan.json 的 plan_type 与当前计划不一致')
    if not scan.get('plan_id') or scan.get('plan_id') != plan.get('plan_id'):
        errors.append('pass1_scan.json 的 plan_id 与当前计划不一致')

    expected = {batch.get('index') for batch in plan.get('batches', [])}
    completed = set(scan.get('completed_batch_indexes', []))
    if not expected or completed != expected:
        errors.append(
            f'Pass 1 批次未完整合并: 计划 {sorted(expected)}, 已完成 {sorted(completed)}'
        )

    topics = scan.get('topic_candidates', [])
    frames = scan.get('frames', [])
    if not topics:
        errors.append('pass1_scan.json 缺少非空 topic_candidates')
    has_frame_evidence = any(
        frame.get('informative') is True
        and (frame.get('transcribed_text') or frame.get('notable'))
        for frame in frames
    )
    if not has_frame_evidence:
        errors.append('pass1_scan.json 缺少可用 frames 证据')

    evidence_filenames = {
        Path(frame.get('filename', '')).name for frame in frames
        if frame.get('filename')
    }
    informative_filenames = {
        Path(frame.get('filename', '')).name for frame in frames
        if frame.get('filename') and frame.get('informative') is True
    }
    missing_evidence = sorted(referenced - evidence_filenames)
    if missing_evidence:
        errors.append(f'有 {len(missing_evidence)} 张正文图片不在 pass1_scan.json.frames 中')
    noninformative = sorted((referenced & evidence_filenames) - informative_filenames)
    if noninformative:
        errors.append(f'有 {len(noninformative)} 张正文图片被标记为非信息帧')

    pending = []
    invalid_documented = []
    for gap in scan.get('gap_suspicions', []):
        if gap.get('priority', 'medium') not in ('high', 'medium'):
            continue
        status = gap.get('status')
        if status not in ('resolved', 'documented'):
            pending.append(gap)
        elif status == 'documented' and not gap.get('resolution_note'):
            invalid_documented.append(gap)
    if pending:
        errors.append(f'仍有 {len(pending)} 个中/高优先级证据缺口未终结')
    if invalid_documented:
        errors.append(f'有 {len(invalid_documented)} 个 documented 缺口缺少 resolution_note')


def _check_frame_stage(scan: dict, plan: dict, prefix: str, label: str,
                       errors: List[str]) -> None:
    expected = {batch.get('index') for batch in plan.get('batches', [])}
    if not expected:
        return
    plan_id = plan.get('plan_id')
    if not plan_id or scan.get(f'{prefix}_plan_id') != plan_id:
        errors.append(f'{label} 的 plan_id 与计划不一致')
    completed = set(scan.get(f'{prefix}_completed_batch_indexes', []))
    if completed != expected:
        errors.append(f'{label} 批次未完整合并: 计划 {sorted(expected)}, 已完成 {sorted(completed)}')
    expected_frames = {
        Path(frame.get('filename', '')).name
        for batch in plan.get('batches', [])
        for frame in batch.get('frames', [])
        if frame.get('filename')
    }
    actual_frames = {
        Path(frame.get('filename', '')).name
        for frame in scan.get('frames', [])
        if frame.get('filename')
    }
    missing = sorted(expected_frames - actual_frames)
    if missing:
        errors.append(f'{label} 有 {len(missing)} 张计划帧未写入 pass1_scan.json.frames')


def validate(folder: str, strict: bool = False) -> List[str]:
    folder_path = Path(folder).resolve()
    notes_path = folder_path / 'notes.md'
    errors: List[str] = []
    if not notes_path.is_file():
        return [f'缺少最终笔记: {notes_path}']

    text = notes_path.read_text(encoding='utf-8')
    _check_header(text, errors)
    for heading in ('## 视频简介', '## 内容结构', '## 总结与启发'):
        if not re.search(rf'^{re.escape(heading)}\s*$', text, re.MULTILINE):
            errors.append(f'缺少必需章节: {heading}')
    topic_headings = TOPIC_RE.findall(text)
    if not topic_headings:
        errors.append('至少需要一个“## 1. 主题”形式的正文主题章节')
    for heading in topic_headings:
        if re.search(r'\d{1,2}:\d{2}|自我介绍|讲者介绍', heading):
            errors.append(f'正文 H2 必须使用主题名，不能使用时间段或讲者介绍: {heading}')
    for label, pattern in FORBIDDEN:
        if pattern.search(text):
            errors.append(f'包含禁止内容: {label}')
    core_heading = re.search(r'^##\s+核心技术要点', text, re.MULTILINE)
    first_topic = TOPIC_RE.search(text)
    if core_heading and (not first_topic or core_heading.start() < first_topic.start()):
        errors.append('包含禁止内容: 核心技术要点前置章节')
    for placeholder in PLACEHOLDERS:
        if placeholder in text:
            errors.append(f'仍包含草稿占位内容: {placeholder}')

    referenced = set()
    for alt, raw_path in ALL_IMAGE_RE.findall(text):
        normalized = raw_path.strip().replace('\\', '/')
        if not re.fullmatch(r'screenshots/[^/]+', normalized, re.IGNORECASE):
            errors.append(f'图片必须使用 screenshots/ 下的相对路径: {raw_path}')
            continue
        filename = normalized.split('/')[-1]
        referenced.add(filename)
        if not alt.strip() or re.search(r'(moment|frame|gap)_?\d|\.(jpg|png)', alt, re.IGNORECASE):
            errors.append(f'图片说明缺少语义或暴露内部文件名: {raw_path}')
        if not (folder_path / Path(normalized)).is_file():
            errors.append(f'图片文件不存在: {raw_path}')

    for heading, body in _sections(text):
        if TOPIC_RE.match(heading):
            count = len(IMAGE_RE.findall(body))
            if count < 1 or count > 5:
                errors.append(f'{heading} 应引用 1—5 张图片，当前为 {count} 张')

    summary_match = re.search(r'^##\s+总结与启发\s*$([\s\S]*)', text, re.MULTILINE)
    if summary_match:
        summary_plain = re.sub(r'[#>*_`\-|\s]', '', summary_match.group(1))
        if not summary_plain:
            errors.append('“总结与启发”为空')

    if strict:
        scan_path = folder_path / 'pass1_scan.json'
        if not scan_path.is_file():
            errors.append('严格验证需要 pass1_scan.json 作为证据扫描记录')
        else:
            try:
                scan = json.loads(scan_path.read_text(encoding='utf-8'))
                plan_names = {
                    'subtitle': 'pass1_subtitle_plan.json',
                    'image': 'pass1_plan.json',
                }
                plan_name = plan_names.get(scan.get('plan_type'))
                if not plan_name or not (folder_path / plan_name).is_file():
                    errors.append('严格验证缺少与 pass1_scan.json 对应的 Pass 1 计划文件')
                else:
                    plan = json.loads((folder_path / plan_name).read_text(encoding='utf-8'))
                    _check_scan(scan, plan, referenced, errors)
                    for aux_name, prefix, label in (
                        ('pass1_frame_plan.json', 'keyframe', '关键帧视觉扫描'),
                        ('pass1_gaps_plan.json', 'pass15', 'Pass 1.5'),
                    ):
                        aux_path = folder_path / aux_name
                        if aux_path.is_file():
                            aux_plan = json.loads(aux_path.read_text(encoding='utf-8'))
                            _check_frame_stage(scan, aux_plan, prefix, label, errors)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f'无法读取 pass1_scan.json: {exc}')

        screenshots_dir = folder_path / 'screenshots'
        existing = {
            path.name for path in screenshots_dir.iterdir()
            if path.is_file() and path.suffix.lower() in ('.jpg', '.jpeg', '.png')
        } if screenshots_dir.is_dir() else set()
        unused = sorted(existing - referenced)
        if unused:
            errors.append(f'screenshots/ 仍有 {len(unused)} 张未引用图片；先 dry-run 确认后清理')

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description='验证最终视频笔记')
    parser.add_argument('video_folder', help='包含 notes.md 的视频目录')
    parser.add_argument('--strict', action='store_true', help='同时检查证据缺口和未引用截图')
    args = parser.parse_args()
    errors = validate(args.video_folder, strict=args.strict)
    if errors:
        print(f'验证失败（{len(errors)} 项）:', file=sys.stderr)
        for error in errors:
            print(f'  - {error}', file=sys.stderr)
        return 1
    print(f"验证通过: {os.path.join(os.path.abspath(args.video_folder), 'notes.md')}")
    print('模式: 严格交付验证' if args.strict else '模式: 写作阶段验证')
    return 0


if __name__ == '__main__':
    sys.exit(main())
