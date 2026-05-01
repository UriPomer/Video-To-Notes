# video-summarizer

## 项目简介

`video-summarizer` 用来把 Bilibili / YouTube 视频整理成结构化笔记。
它适合技术分享、演讲、教程类视频：先下载视频与元数据，再优先使用平台字幕或本地语音转录，最后生成可继续加工的笔记草稿。

## 能做什么

- 从 Bilibili / YouTube 下载视频和元数据
- 优先使用平台字幕；没有字幕时自动转录音频
- 根据字幕密度判断走字幕优先还是图片优先流程
- 为后续笔记整理生成 `subtitles.json`、截图目录和 `notes.md` 草稿

## 环境

推荐在 Windows PowerShell 下运行 Python 命令。

依赖安装：

```powershell
pip install yt-dlp you-get opencv-python numpy faster-whisper
```

额外要求：

- `ffmpeg` 需要在 PATH 中
- Windows 下不要用 Git Bash 跑这里的 Python 命令
- 如果 GPU 转录失败，脚本会自动回退到 CPU，无需手动重试

## 快速开始

### 1. 创建输出目录

```powershell
python scripts/fetch/create_folder.py "<video_url>"
```

记下输出的 `<folder>` 路径。

### 2. 下载视频

```powershell
python scripts/fetch/download_video.py "<video_url>" "<folder>"
```

### 3. 提取字幕 / 转录音频

```powershell
python -u scripts/subtitle/transcribe_audio.py "<folder>"
```

执行完成后会写出 `subtitles.json`。

### 4. 生成笔记草稿

```powershell
python scripts/pass2_scaffold/generate_notes.py "<folder>" --ppt
```

如果 `subtitles.json.mode` 是 `image_primary`，需要先按 `SKILL_zh.md` 里的 Step 4a 进行截帧，再生成草稿。

更完整的流程说明见：

- `SKILL_zh.md`
- `SKILL.md`

## 输入与输出文件

### 输入

- 视频链接：Bilibili 或 YouTube URL

### 主要中间文件

在 `<folder>` 下会产生：

- `video.mp4`（或 `video.webm` / `video.mkv` / `video.flv`）
- `metadata.json`
- `subtitles.json`
- `screenshots/`（图片优先流程或后续抽帧时使用）

### 输出

- `notes.md`：生成的笔记草稿
