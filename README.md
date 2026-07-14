# video-summarizer

## 项目简介

`video-summarizer` 用来把 Bilibili / YouTube 视频整理成结构化笔记。
它适合技术分享、演讲、教程类视频：先下载视频与元数据，再优先使用平台字幕或本地语音转录，最后生成可继续加工的笔记草稿。

## 能做什么

- 从 Bilibili / YouTube 下载视频和元数据
- 优先使用平台字幕；没有字幕时自动转录音频
- 根据字幕密度判断走字幕优先还是图片优先流程
- 为后续笔记整理生成 `subtitles.json`、截图目录和 `notes.draft.md` 草稿
- 用严格验证器阻止草稿占位、违规章节、缺图和未解决证据缺口进入最终交付

## 环境

推荐在 Windows PowerShell 下运行 Python 命令。

以下流程命令均从 workspace 根目录（包含 `.codebuddy/` 和 `notes/` 的目录）运行。

依赖安装：

```powershell
pip install yt-dlp you-get opencv-python numpy faster-whisper
```

额外要求：

- `ffmpeg` 需要在 PATH 中
- Windows 下不要用 Git Bash 跑这里的 Python 命令
- 转录默认自动检测 CUDA：可用时使用 GPU，否则使用 CPU
- 如果 GPU 转录失败，脚本会自动回退到 CPU，无需手动重试

## 快速开始

### 1. 创建输出目录

```powershell
python .codebuddy\skills\video-summarizer\scripts\fetch\create_folder.py "<video_url>"
```

记下输出的 `<folder>` 路径。
需要归档到指定系列目录时添加 `--output-root "notes\Unreal-Fest"`。

### 2. 下载视频

```powershell
python .codebuddy\skills\video-summarizer\scripts\fetch\download_video.py "<video_url>" "<folder>"
```

### 3. 提取字幕 / 转录音频

```powershell
python -u .codebuddy\skills\video-summarizer\scripts\subtitle\transcribe_audio.py "<folder>"
```

执行完成后会写出 `subtitles.json`。
长时间转录会每分钟输出存活提示；GPU 失败时仍会自动回退 CPU。

### 4. 生成笔记草稿

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass2_scaffold\generate_notes.py "<folder>" --ppt
```

如果 `subtitles.json.mode` 是 `image_primary`，需要先按 `SKILL.md` 的图片优先路线截帧，再生成草稿。

生成 `notes.draft.md` 只表示素材准备完成，不是工作流完成。必须继续执行 `SKILL.md` 中的 Pass 1、证据缺口处理、最终写作和严格验证，才能交付 `notes.md`。

Pass 1、关键帧视觉扫描和 Pass 1.5 都采用“计划 JSON → 每批固定结果文件 → `merge_results.py` 确定性合并”的恢复协议。计划脚本默认只输出摘要，需要完整代理提示时显式添加 `--print-prompts`。

更完整的流程说明见：

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

- `notes.draft.md`：自动生成的中文写作骨架，不得直接交付
- `notes.md`：人工基于字幕与图片证据完成并通过严格验证的最终笔记
