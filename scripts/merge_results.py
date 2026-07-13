#!/usr/bin/env python3
"""校验并合并 Pass 1、关键帧视觉扫描或 Pass 1.5 的批次结果。"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


STAGES = {
    'pass1': ('pass1_results', None),
    'keyframes': ('pass1_frame_results', 'pass1_frame_plan.json'),
    'pass15': ('pass15_results', 'pass1_gaps_plan.json'),
}

FRAME_FIELDS = {
    'filename', 'timestamp_sec', 'transcribed_text', 'notable',
    'informative', 'content_type', 'slide_title',
}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'无法读取 JSON: {path}: {exc}') from exc


def _pass1_plan(folder: Path) -> Tuple[Path, Dict]:
    candidates = [folder / 'pass1_subtitle_plan.json', folder / 'pass1_plan.json']
    existing = [path for path in candidates if path.is_file()]
    if len(existing) != 1:
        raise ValueError('Pass 1 必须且只能存在一个计划文件')
    return existing[0], _read_json(existing[0])


def _load_results(results_dir: Path) -> List[Dict]:
    if not results_dir.is_dir():
        raise ValueError(f'结果目录不存在: {results_dir}')
    results: List[Dict] = []
    for path in sorted(results_dir.glob('batch_*.json')):
        payload = _read_json(path)
        if isinstance(payload, list):
            results.extend(payload)
        elif isinstance(payload, dict):
            results.append(payload)
        else:
            raise ValueError(f'批次结果必须是 JSON 对象或对象数组: {path}')
    if not results:
        raise ValueError(f'结果目录没有 batch_*.json: {results_dir}')
    return results


def _validate_results(plan: Dict, results: List[Dict], require_frames: bool) -> List[Dict]:
    if not plan.get('plan_id'):
        raise ValueError('计划缺少 plan_id，不能证明批次结果属于当前计划')
    expected = {batch.get('index') for batch in plan.get('batches', [])}
    if not expected or None in expected:
        raise ValueError('计划缺少有效批次索引')

    by_index: Dict[int, Dict] = {}
    for result in results:
        if result.get('plan_id') != plan.get('plan_id'):
            raise ValueError('批次结果 plan_id 与计划不一致')
        index = result.get('batch_index')
        if index in by_index:
            raise ValueError(f'批次结果重复: {index}')
        by_index[index] = result

    actual = set(by_index)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError(f'缺少批次: {missing}')
    if extra:
        raise ValueError(f'存在计划外批次: {extra}')

    ordered = [by_index[index] for index in sorted(expected)]
    for result in ordered:
        for field in ('topic_candidates', 'gap_suspicions'):
            if not isinstance(result.get(field), list):
                raise ValueError(f'批次 {result["batch_index"]} 缺少 {field} 数组')
        if not require_frames and not isinstance(result.get('key_moments'), list):
            raise ValueError(f'批次 {result["batch_index"]} 缺少 key_moments 数组')
    if require_frames:
        plan_batches = {batch['index']: batch for batch in plan['batches']}
        for result in ordered:
            index = result['batch_index']
            expected_files = {
                Path(frame['filename']).name
                for frame in plan_batches[index].get('frames', [])
            }
            frames = result.get('frames')
            if not isinstance(frames, list):
                raise ValueError(f'批次 {index} 缺少 frames 数组')
            actual_files = {Path(frame.get('filename', '')).name for frame in frames}
            if actual_files != expected_files or len(frames) != len(expected_files):
                raise ValueError(f'批次 {index} 的帧集合与计划不一致')
            for frame in frames:
                missing_fields = FRAME_FIELDS - set(frame)
                if missing_fields:
                    raise ValueError(f'批次 {index} 的 {frame.get("filename")} 缺少字段: {sorted(missing_fields)}')
                if not isinstance(frame.get('informative'), bool):
                    raise ValueError(f'批次 {index} 的 informative 必须是布尔值')
    return ordered


def _flatten(results: Iterable[Dict], key: str) -> List[Dict]:
    return [item for result in results for item in result.get(key, [])]


def _merge_frames(scan: Dict, plan: Dict, results: List[Dict]) -> None:
    planned = {
        Path(frame['filename']).name
        for batch in plan.get('batches', [])
        for frame in batch.get('frames', [])
    }
    existing = [
        frame for frame in scan.get('frames', [])
        if Path(frame.get('filename', '')).name not in planned
    ]
    scan['frames'] = existing + _flatten(results, 'frames')


def _ranges_overlap(left: List[float], right: List[float]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def merge_results(video_folder: str, stage: str) -> Dict:
    if stage not in STAGES:
        raise ValueError(f'未知阶段: {stage}')
    folder = Path(video_folder).resolve()
    results_name, fixed_plan_name = STAGES[stage]
    if fixed_plan_name:
        plan_path = folder / fixed_plan_name
        if not plan_path.is_file():
            raise ValueError(f'计划文件不存在: {plan_path}')
        plan = _read_json(plan_path)
    else:
        plan_path, plan = _pass1_plan(folder)

    results = _load_results(folder / results_name)
    ordered = _validate_results(plan, results, require_frames=stage != 'pass1' or plan.get('plan_type') == 'image')
    indexes = [result['batch_index'] for result in ordered]
    scan_path = folder / 'pass1_scan.json'

    if stage == 'pass1':
        scan = {
            'plan_type': plan.get('plan_type'),
            'plan_id': plan.get('plan_id'),
            'completed_batch_indexes': indexes,
            'source': plan.get('source', plan.get('plan_type', 'unknown')),
            'language': plan.get('lang', 'unknown'),
            'batch_count': len(indexes),
            'topic_candidates': _flatten(ordered, 'topic_candidates'),
            'key_moments': _flatten(ordered, 'key_moments'),
            'gap_suspicions': _flatten(ordered, 'gap_suspicions'),
            'frames': _flatten(ordered, 'frames'),
        }
    else:
        if not scan_path.is_file():
            raise ValueError('合并视觉结果前缺少 pass1_scan.json')
        scan = _read_json(scan_path)
        _merge_frames(scan, plan, ordered)
        prefix = 'keyframe' if stage == 'keyframes' else 'pass15'
        scan[f'{prefix}_plan_id'] = plan.get('plan_id')
        scan[f'{prefix}_completed_batch_indexes'] = indexes
        if stage == 'pass15':
            processed_ranges = [entry['range_sec'] for entry in plan.get('new_frames_by_gap', [])]
            evidence_frames = [
                frame for frame in _flatten(ordered, 'frames')
                if frame.get('informative') is True
                and (frame.get('transcribed_text') or frame.get('notable'))
            ]
            for gap in scan.get('gap_suspicions', []):
                gap_range = gap.get('range_sec')
                has_processed_range = gap_range and any(
                    _ranges_overlap(gap_range, current) for current in processed_ranges)
                has_evidence = gap_range and any(
                    gap_range[0] <= frame.get('timestamp_sec', -1) <= gap_range[1]
                    for frame in evidence_frames
                )
                if has_processed_range and has_evidence:
                    gap['status'] = 'resolved'

    scan_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding='utf-8')
    return scan


def main() -> int:
    parser = argparse.ArgumentParser(description='校验并合并视频总结批次结果')
    parser.add_argument('video_folder')
    parser.add_argument('--stage', choices=sorted(STAGES), required=True)
    args = parser.parse_args()
    try:
        scan = merge_results(args.video_folder, args.stage)
    except ValueError as exc:
        print(f'合并失败: {exc}', file=os.sys.stderr)
        return 1
    print(f"合并完成: {Path(args.video_folder).resolve() / 'pass1_scan.json'}")
    print(f"阶段: {args.stage}; frames={len(scan.get('frames', []))}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
