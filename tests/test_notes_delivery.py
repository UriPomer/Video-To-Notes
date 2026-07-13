import importlib.util
import json
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(relative_path: str, name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_valid_note(folder: Path) -> None:
    screenshots = folder / 'screenshots'
    screenshots.mkdir()
    (screenshots / 'architecture.jpg').write_bytes(b'image')
    summary = (
        '跨章节可以归纳出一条通用规律：先用约束缩小问题空间，再用可观测数据验证瓶颈，'
        '最后才针对高收益路径优化。该方法能够迁移到其他实时系统，但前提是指标定义稳定。'
    )
    (folder / 'notes.md').write_text(
        '# 测试\n\n'
        '> **来源**: [示例](https://example.com/video)\n'
        '> **演讲者**: 测试作者 | **日期**: 2025-01-01 | **时长**: 10:00\n'
        '> **标签**: 架构、性能\n\n'
        '## 视频简介\n\n本文介绍系统设计。\n\n'
        '## 内容结构\n\n| 章节 | 内容 |\n|---|---|\n| 1 | 架构 |\n\n'
        '## 1. 架构设计\n\n### 1.1 数据流\n\n'
        '![运行时数据流与模块边界](screenshots/architecture.jpg)\n\n'
        '系统将采集、计算和呈现分层处理。\n\n'
        '**设计意图**: 降低模块耦合并保留降级能力。\n\n'
        f'## 总结与启发\n\n{summary}\n', encoding='utf-8')


def write_subtitle_plan(folder: Path, plan_id: str = 'test-plan', batches: int = 1) -> None:
    (folder / 'pass1_subtitle_plan.json').write_text(json.dumps({
        'plan_type': 'subtitle',
        'plan_id': plan_id,
        'n_batches': batches,
        'batches': [{'index': index} for index in range(1, batches + 1)],
    }), encoding='utf-8')


def test_scaffold_is_chinese_and_never_overwrites_final_notes(tmp_path):
    module = load_module('scripts/pass2_scaffold/generate_notes.py', 'generate_notes_under_test')
    (tmp_path / 'metadata.json').write_text(
        json.dumps({'title': '测试视频', 'uploader': '作者'}, ensure_ascii=False), encoding='utf-8')
    final = tmp_path / 'notes.md'
    final.write_text('用户已有笔记', encoding='utf-8')

    result = Path(module.generate_notes(str(tmp_path), ppt_mode=True))

    assert result.name == 'notes.draft.md'
    assert final.read_text(encoding='utf-8') == '用户已有笔记'
    draft = result.read_text(encoding='utf-8')
    assert '## 视频简介' in draft
    assert '## 帧索引' not in draft
    assert '## 元数据' not in draft
    assert 'DRAFT SCAFFOLD' not in draft


def test_validator_accepts_complete_strict_note(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_notes_valid')
    write_valid_note(tmp_path)
    write_subtitle_plan(tmp_path)
    (tmp_path / 'pass1_scan.json').write_text(
        json.dumps({
            'plan_type': 'subtitle',
            'plan_id': 'test-plan',
            'completed_batch_indexes': [1],
            'topic_candidates': [{'title': '架构设计', 'start_sec': 0}],
            'frames': [{
                'filename': 'architecture.jpg',
                'informative': True,
                'transcribed_text': '运行时数据流',
            }],
            'gap_suspicions': [{'priority': 'high', 'status': 'resolved'}],
        }), encoding='utf-8')

    errors = module.validate(str(tmp_path), strict=True)

    assert errors == []


def test_validator_rejects_old_scaffold_tail_and_placeholders(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_notes_invalid')
    (tmp_path / 'notes.md').write_text(
        '# 测试\n\n## 视频简介\n\n介绍\n\n## 内容结构\n\n目录\n\n'
        '## 核心技术要点\n\n重复内容\n\n## 1. 主题名称\n\n正文\n\n'
        '## 总结与启发\n\n很短\n\n## 帧索引（Frame Index）\n\n## 元数据\n', encoding='utf-8')

    errors = module.validate(str(tmp_path))

    joined = '\n'.join(errors)
    assert '帧索引' in joined
    assert '元数据章节' in joined
    assert '核心技术要点前置章节' in joined
    assert '头部缺少字段' in joined
    assert '草稿占位内容' in joined
    assert '应引用 1—5 张图片' in joined


def test_validator_rejects_empty_or_unexplained_evidence(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_notes_evidence')
    write_valid_note(tmp_path)
    write_subtitle_plan(tmp_path)
    scan_path = tmp_path / 'pass1_scan.json'

    scan_path.write_text(json.dumps({
        'plan_type': 'subtitle', 'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
    }), encoding='utf-8')
    errors = module.validate(str(tmp_path), strict=True)
    assert any('topic_candidates' in error for error in errors)
    assert any('frames 证据' in error for error in errors)

    scan_path.write_text(json.dumps({
        'plan_type': 'subtitle', 'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
        'topic_candidates': [{'title': '架构设计'}],
        'frames': [{
            'filename': 'architecture.jpg', 'informative': True,
            'notable': '展示架构图',
        }],
        'gap_suspicions': [{'priority': 'medium', 'status': 'documented'}],
    }), encoding='utf-8')
    errors = module.validate(str(tmp_path), strict=True)
    assert any('resolution_note' in error for error in errors)

    scan_path.write_text(json.dumps({
        'plan_type': 'subtitle', 'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
        'topic_candidates': [{'title': '架构设计'}],
        'frames': [{
            'filename': 'architecture.jpg', 'informative': True,
            'notable': '展示架构图',
        }],
        'gap_suspicions': [{
            'priority': 'medium', 'status': 'documented',
            'resolution_note': '画面与字幕均未给出该参数的具体数值',
        }],
    }, ensure_ascii=False), encoding='utf-8')
    assert module.validate(str(tmp_path), strict=True) == []


def test_subtitle_plan_persists_text_and_stable_identity(tmp_path, capsys):
    module = load_module('scripts/pass1_subtitle/plan_batches.py', 'plan_batches_under_test')
    (tmp_path / 'subtitles.json').write_text(json.dumps({
        'mode': 'subtitle_primary', 'lang': 'zh', 'source': 'platform_cc',
        'segments': [
            {'start': 0.0, 'end': 1.0, 'text': '第一段字幕'},
            {'start': 1.0, 'end': 2.0, 'text': '第二段字幕'},
        ],
    }, ensure_ascii=False), encoding='utf-8')

    plan = module.build_plan(str(tmp_path), target_chars=100, max_batches=3)
    persisted = json.loads((tmp_path / 'pass1_subtitle_plan.json').read_text(encoding='utf-8'))

    first = persisted['batches'][0]['segments'][0]
    assert first['text'] == '第一段字幕'
    assert persisted['plan_type'] == 'subtitle'
    assert len(persisted['plan_id']) == 16
    assert module.build_plan(str(tmp_path), target_chars=100, max_batches=3)['plan_id'] == plan['plan_id']

    module.print_prompts(plan)
    output = capsys.readouterr().out
    assert f'"plan_id": "{plan["plan_id"]}"' in output
    assert '"batch_index": 1' in output
    assert 'pass1_results' in output
    assert 'NO file writes' not in output


def test_image_plan_has_identity(tmp_path):
    module = load_module('scripts/pass1_image/plan_batches.py', 'image_plan_under_test')
    screenshots = tmp_path / 'screenshots'
    screenshots.mkdir()
    (screenshots / 'frame_0000.jpg').write_bytes(b'image')
    (tmp_path / 'key_frames.json').write_text(json.dumps({
        'frames': [{'filename': 'frame_0000.jpg', 'timestamp': 0.0}],
    }), encoding='utf-8')

    plan = module.build_batches(str(tmp_path), n_batches=1, use_all_frames=False)

    persisted = json.loads((tmp_path / 'pass1_plan.json').read_text(encoding='utf-8'))
    assert plan['plan_type'] == persisted['plan_type'] == 'image'
    assert plan['plan_id'] == persisted['plan_id']
    assert len(plan['plan_id']) == 16


def test_strict_validator_rejects_partial_foreign_evidence_and_external_image(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_notes_adversarial')
    write_valid_note(tmp_path)
    write_subtitle_plan(tmp_path, batches=2)
    notes_path = tmp_path / 'notes.md'
    notes_path.write_text(
        notes_path.read_text(encoding='utf-8').replace(
            '## 1. 架构设计',
            '## 1. 架构设计\n\n![外部示意图](https://example.com/external.png)',
        ),
        encoding='utf-8',
    )
    (tmp_path / 'pass1_scan.json').write_text(json.dumps({
        'plan_type': 'subtitle',
        'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
        'topic_candidates': [{'title': '无关主题'}],
        'frames': [{
            'filename': 'other.jpg', 'informative': True,
            'transcribed_text': '无关证据',
        }],
        'gap_suspicions': [],
    }), encoding='utf-8')

    errors = module.validate(str(tmp_path), strict=True)
    joined = '\n'.join(errors)
    assert '图片必须使用 screenshots/' in joined
    assert '批次未完整合并' in joined
    assert '正文图片不在 pass1_scan.json.frames' in joined


def test_skill_keeps_visual_quality_contract():
    text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')

    assert '--key-frames-only --batch-size 15' in text
    assert '每批最多 15 张' in text
    assert 'pass1_scan.json.frames' in text
    assert 'completed_batch_indexes' in text
    assert '无法读取图片' in text
    assert '最终正文通常不超过 15 张图' not in text


def test_strict_validator_rejects_noninformative_referenced_frame(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_noninformative')
    write_valid_note(tmp_path)
    write_subtitle_plan(tmp_path)
    (tmp_path / 'pass1_scan.json').write_text(json.dumps({
        'plan_type': 'subtitle',
        'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
        'topic_candidates': [{'title': '架构设计'}],
        'frames': [{
            'filename': 'architecture.jpg',
            'informative': False,
            'notable': '纯过渡页',
        }, {
            'filename': 'other.jpg',
            'informative': True,
            'notable': '其他有效证据',
        }],
        'gap_suspicions': [],
    }, ensure_ascii=False), encoding='utf-8')

    errors = module.validate(str(tmp_path), strict=True)

    assert any('非信息帧' in error for error in errors)


def test_strict_validator_requires_complete_pass15_plan(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_pass15')
    write_valid_note(tmp_path)
    write_subtitle_plan(tmp_path)
    (tmp_path / 'pass1_gaps_plan.json').write_text(json.dumps({
        'plan_type': 'gaps',
        'plan_id': 'gap-plan',
        'batches': [
            {'index': 1, 'frames': [{'filename': 'gap_1.jpg'}]},
            {'index': 2, 'frames': [{'filename': 'gap_2.jpg'}]},
        ],
    }), encoding='utf-8')
    (tmp_path / 'pass1_scan.json').write_text(json.dumps({
        'plan_type': 'subtitle',
        'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
        'pass15_plan_id': 'gap-plan',
        'pass15_completed_batch_indexes': [1],
        'topic_candidates': [{'title': '架构设计'}],
        'frames': [{
            'filename': 'architecture.jpg',
            'informative': True,
            'notable': '有效架构图',
        }],
        'gap_suspicions': [{'priority': 'high', 'status': 'resolved'}],
    }, ensure_ascii=False), encoding='utf-8')

    errors = module.validate(str(tmp_path), strict=True)

    assert any('Pass 1.5 批次未完整合并' in error for error in errors)


def test_strict_validator_rejects_pass15_plan_without_identity(tmp_path):
    module = load_module('scripts/validate/validate_notes.py', 'validate_pass15_identity')
    write_valid_note(tmp_path)
    write_subtitle_plan(tmp_path)
    (tmp_path / 'pass1_gaps_plan.json').write_text(json.dumps({
        'batches': [{'index': 1, 'frames': []}],
    }), encoding='utf-8')
    (tmp_path / 'pass1_scan.json').write_text(json.dumps({
        'plan_type': 'subtitle',
        'plan_id': 'test-plan',
        'completed_batch_indexes': [1],
        'pass15_completed_batch_indexes': [1],
        'topic_candidates': [{'title': '架构设计'}],
        'frames': [{
            'filename': 'architecture.jpg',
            'informative': True,
            'notable': '有效架构图',
        }],
        'gap_suspicions': [],
    }, ensure_ascii=False), encoding='utf-8')

    errors = module.validate(str(tmp_path), strict=True)

    assert any('Pass 1.5 的 plan_id' in error for error in errors)


def test_merge_results_builds_pass1_scan_and_rejects_partial_batches(tmp_path):
    module = load_module('scripts/merge_results.py', 'merge_results_under_test')
    write_subtitle_plan(tmp_path, plan_id='merge-plan', batches=2)
    results = tmp_path / 'pass1_results'
    results.mkdir()
    (results / 'batch_001.json').write_text(json.dumps({
        'plan_id': 'merge-plan', 'batch_index': 1,
        'topic_candidates': [{'title': '主题一'}],
        'key_moments': [], 'gap_suspicions': [],
    }, ensure_ascii=False), encoding='utf-8')

    try:
        module.merge_results(str(tmp_path), 'pass1')
    except ValueError as exc:
        assert '缺少批次' in str(exc)
    else:
        raise AssertionError('partial pass1 results should fail')

    (results / 'batch_002.json').write_text(json.dumps({
        'plan_id': 'merge-plan', 'batch_index': 2,
        'topic_candidates': [{'title': '主题二'}],
        'key_moments': [], 'gap_suspicions': [],
    }, ensure_ascii=False), encoding='utf-8')

    scan = module.merge_results(str(tmp_path), 'pass1')

    assert scan['completed_batch_indexes'] == [1, 2]
    assert [item['title'] for item in scan['topic_candidates']] == ['主题一', '主题二']


def test_merge_results_pass15_requires_evidence_before_resolving_gap(tmp_path):
    module = load_module('scripts/merge_results.py', 'merge_pass15_under_test')
    (tmp_path / 'pass1_scan.json').write_text(json.dumps({
        'frames': [],
        'gap_suspicions': [{'range_sec': [10, 20], 'priority': 'high'}],
    }), encoding='utf-8')
    (tmp_path / 'pass1_gaps_plan.json').write_text(json.dumps({
        'plan_type': 'gaps',
        'plan_id': 'gap-plan',
        'new_frames_by_gap': [{'range_sec': [10, 20]}],
        'batches': [{'index': 1, 'frames': [{'filename': 'gap_0010_0020_001.jpg'}]}],
    }), encoding='utf-8')
    results = tmp_path / 'pass15_results'
    results.mkdir()

    def write_result(informative, notable):
        (results / 'batch_001.json').write_text(json.dumps({
            'plan_id': 'gap-plan',
            'batch_index': 1,
            'topic_candidates': [],
            'gap_suspicions': [],
            'frames': [{
                'filename': 'gap_0010_0020_001.jpg',
                'timestamp_sec': 15,
                'transcribed_text': '',
                'notable': notable,
                'informative': informative,
                'content_type': 'diagram',
                'slide_title': None,
            }],
        }, ensure_ascii=False), encoding='utf-8')

    write_result(False, '')
    scan = module.merge_results(str(tmp_path), 'pass15')
    assert 'status' not in scan['gap_suspicions'][0]

    write_result(True, '补齐了架构关系')
    scan = module.merge_results(str(tmp_path), 'pass15')
    assert scan['gap_suspicions'][0]['status'] == 'resolved'


def test_gap_frame_budget_keeps_representatives_within_limits():
    module = load_module('scripts/pass15_gaps/resolve_gaps.py', 'gap_budget_under_test')
    entries = [
        {'priority': 'high', 'kept_frames': [f'a_{index}.jpg' for index in range(10)]},
        {'priority': 'medium', 'kept_frames': [f'b_{index}.jpg' for index in range(10)]},
        {'priority': 'medium', 'kept_frames': [f'c_{index}.jpg' for index in range(10)]},
    ]

    limited = module.apply_frame_budget(entries, max_per_gap=4, max_total=9)

    assert sum(len(entry['kept_frames']) for entry in limited) == 9
    assert all(1 <= len(entry['kept_frames']) <= 4 for entry in limited)
    assert limited[0]['kept_frames'][0] == 'a_0.jpg'
    assert limited[0]['kept_frames'][-1] == 'a_9.jpg'


def test_create_folder_supports_output_root(tmp_path, monkeypatch):
    module = load_module('scripts/fetch/create_folder.py', 'create_folder_under_test')
    monkeypatch.setattr(module, 'get_project_root', lambda: str(tmp_path))
    monkeypatch.setattr(module, 'extract_title_with_youget', lambda _url: '测试视频')
    monkeypatch.setattr(module, 'extract_title_from_webpage', lambda _url: None)
    monkeypatch.setattr(module, 'extract_youtube_oembed_title', lambda _url: None)
    target = tmp_path / 'notes' / 'Unreal-Fest'

    folder = Path(module.create_folder('https://example.com/video/BV123', output_root=str(target)))

    assert folder.parent == target
    assert (folder / 'url.txt').is_file()
    assert (target / '.last_folder.txt').read_text(encoding='utf-8') == str(folder)


def test_transcription_heartbeat_emits_periodic_status(capsys):
    module = load_module('scripts/subtitle/transcribe_audio.py', 'transcribe_heartbeat')
    stop = threading.Event()
    thread = threading.Thread(
        target=module.emit_heartbeat,
        args=(stop, '测试任务', 0.01),
        daemon=True,
    )
    thread.start()
    time.sleep(0.03)
    stop.set()
    thread.join(timeout=1)

    assert '测试任务仍在运行' in capsys.readouterr().out
