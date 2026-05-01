import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'subtitle' / 'transcribe_audio.py'


def load_module():
    spec = importlib.util.spec_from_file_location('transcribe_audio_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_vtt(path: Path, text: str) -> None:
    path.write_text(
        'WEBVTT\n\n'
        '00:00:00.000 --> 00:00:01.000\n'
        f'{text}\n',
        encoding='utf-8',
    )


def test_run_whisper_falls_back_to_cpu_when_gpu_worker_fails(monkeypatch, capsys):
    module = load_module()

    def fake_run_whisper_isolated(video_file, model_size, device, compute_type):
        assert video_file == 'video.mp4'
        assert model_size == 'tiny'
        assert device == 'cuda'
        assert compute_type == 'float16'
        raise RuntimeError('gpu worker exited with code 1')

    def fake_run_whisper_in_process(video_file, model_size, device, compute_type):
        assert video_file == 'video.mp4'
        assert model_size == 'tiny'
        assert device == 'cpu'
        assert compute_type == 'int8'
        return ([{'start': 0.0, 'end': 1.0, 'text': 'CPU fallback transcript'}], 'zh')

    monkeypatch.setattr(module, '_run_whisper_isolated', fake_run_whisper_isolated)
    monkeypatch.setattr(module, '_run_whisper_in_process', fake_run_whisper_in_process)

    segments, lang = module.run_whisper('video.mp4', model_size='tiny')

    captured = capsys.readouterr()
    assert lang == 'zh'
    assert segments == [{'start': 0.0, 'end': 1.0, 'text': 'CPU fallback transcript'}]
    assert 'continuing on CPU; no retry needed' in captured.err


def test_transcribe_prefers_platform_subtitle_before_whisper(tmp_path, monkeypatch):
    module = load_module()
    video_folder = tmp_path / 'video'
    video_folder.mkdir()
    (video_folder / 'video.mp4').write_bytes(b'not-a-real-video')
    write_vtt(video_folder / 'video.zh-Hans.vtt', '平台字幕内容足够长，确保会走 subtitle_primary。')

    def fail_if_called(*args, **kwargs):
        raise AssertionError('run_whisper should not be called when platform subtitles exist')

    monkeypatch.setattr(module, 'run_whisper', fail_if_called)
    monkeypatch.setattr(module, 'probe_duration', lambda _: 0.0)

    payload = module.transcribe(str(video_folder), whisper_model='tiny')

    assert payload['source'] == 'platform_cc'
    assert payload['mode'] == 'subtitle_primary'
    assert payload['segments'][0]['text'] == '平台字幕内容足够长，确保会走 subtitle_primary。'


def test_transcribe_uses_image_primary_when_whisper_is_unavailable(tmp_path, monkeypatch, capsys):
    module = load_module()
    video_folder = tmp_path / 'video'
    video_folder.mkdir()
    (video_folder / 'video.mp4').write_bytes(b'not-a-real-video')

    monkeypatch.setattr(module, 'probe_duration', lambda _: 60.0)

    def missing_whisper(*args, **kwargs):
        raise RuntimeError('faster-whisper not installed. Run: pip install faster-whisper')

    monkeypatch.setattr(module, 'run_whisper', missing_whisper)

    payload = module.transcribe(str(video_folder), whisper_model='tiny')

    captured = capsys.readouterr()
    assert payload['mode'] == 'image_primary'
    assert payload['source'] == 'none'
    assert 'ACTION REQUIRED' in captured.err
