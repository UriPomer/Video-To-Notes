---
name: video-summarizer-zh
description: "从 Bilibili/YouTube 下载视频，截取幻灯片，通过并行 sub-agent 视觉分析生成主题化笔记。"
version: 2.2.0
---

# 视频摘要器

脚本准备素材 → 并行 sub-agent 扫描 → 主 agent 写主题化笔记。

参考成品：`{baseDir}/examples/good_notes_phasmophobia.md` — 以此为质量标准。

## 依赖

```powershell
# Windows：用 PowerShell，不要用 Git Bash（Git Bash 的 python 返回 exit 127）
# 在 CodeBuddy Code 里，这里的 Python 命令必须调用 PowerShell tool，不能用 Bash tool。
pip install yt-dlp you-get opencv-python numpy faster-whisper
# ffmpeg 需要在 PATH 上
```

验证：`python -c "from faster_whisper import WhisperModel; print('ok')"`

**Windows GPU 一次性配置**（转录崩溃 exit -1073740791 时执行）：

```powershell
pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 nvidia-cufft-cu12

python -c "
import glob, os, shutil, site
ct2 = next(d for d in [os.path.join(s, 'ctranslate2') for s in site.getsitepackages()] if os.path.isdir(d))
copied = []
for s in site.getsitepackages():
    for dll in glob.glob(os.path.join(s, 'nvidia', '*', 'bin', '*.dll')):
        dst = os.path.join(ct2, os.path.basename(dll))
        if not os.path.exists(dst):
            shutil.copy2(dll, dst)
            copied.append(os.path.basename(dll))
print('copied:', copied or 'nothing (already done)')
"
```

## Phase A — 逐步操作（PowerShell）

### Step 1 — 创建文件夹

```powershell
python {baseDir}/scripts/fetch/create_folder.py "<video_url>"
```

打印文件夹路径。B 站视频 stderr 里 412 错误是正常的，文件夹仍然创建。

### Step 2 — 下载视频

```powershell
python {baseDir}/scripts/fetch/download_video.py "<video_url>" "<folder>"
```

B 站：yt-dlp 报 412 → you-get 接管，两者都是正常流程，不要重试。

### Step 3 — 转录音频（阻塞命令，等待完成，不要后台或轮询）

```powershell
python -u {baseDir}/scripts/subtitle/transcribe_audio.py "<folder>"
```

完成时输出：`[transcribe_audio] mode=subtitle_primary source=whisper_local chars=XXXX ...`

- 在 CodeBuddy Code 里，这一步必须用 PowerShell tool，并设置 `timeout: 600000`。不要用 Bash。
- GPU（large-v3，默认）：2-10 分钟。CPU fallback：最多 30 分钟。两者都正常。
- Exit -1073740791 = CUDA DLL 未配置 → 执行上方 GPU 配置后重试。

完成后读 `subtitles.json.mode`，决定 Step 4。

### Step 4a — 截帧（仅 image_primary）

```powershell
python {baseDir}/scripts/capture/capture_ppt_frames.py "<folder>/video.mp4" "<folder>/screenshots" --scale 800
python {baseDir}/scripts/capture/filter_frames.py "<folder>/screenshots"
python {baseDir}/scripts/capture/select_key_frames.py "<folder>/screenshots"
```

### Step 4b — 跳过（subtitle_primary）

无需截帧。

### Step 5 — 生成草稿骨架

```powershell
python {baseDir}/scripts/pass2_scaffold/generate_notes.py "<folder>" --ppt
```

Phase A 完成，进入 Phase B。

## 核心规则

| # | 规则 |
|---|---|
| R1 | **目录按主题划分。** H2 标题来自幻灯片 title card（"Sensor Toolkit"），绝不用时间段。 |
| R2 | **每张嵌入的图都要承载信息。** 黑屏、纯过场、仅讲者、logo、近似重复——丢弃。 |
| R3 | **原文转写。** 幻灯片标题、Inspector 参数、代码、思维导图节点。非中文直接翻译为中文，不保留原文。 |
| R4 | **按内容选 primitive。** 架构图 → ASCII 树。参数/列表 → 表格。代码 → fenced block。前/后 → 双列表格。 |
| R5 | **每个 H2 章节 1-5 张图。** 每个子观点挑最有信息量的一到二张。 |
| R6 | **解决问题或 inline 标注。** 未展开的点写 `*（演讲中未展开：...）*`，不另起"待深入研究"章节。 |
| R7 | **图片只通过 markdown 语法嵌入。** `![描述](screenshots/xxx.jpg)`。绝不把 `frame_*.jpg` 或 `gap_*.jpg` 当标题或说明文字。 |

## Phase B — Pass 1

先读 `subtitles.json.mode`。

### 字幕模式

```powershell
python {baseDir}/scripts/pass1_subtitle/plan_batches.py "<folder>"
```

打印可直接粘贴的 prompt。并行派发所有 N 个 sub-agent（一条消息，N 个 `Agent` 调用，`subagent_type="general-purpose"`）。每个返回 `{topic_candidates[], key_moments[], gap_suspicions[]}`。合并到 `pass1_scan.json`。

### Pass 1.3 — 抽帧（仅字幕模式）

```powershell
python {baseDir}/scripts/pass1_subtitle/extract_key_moments.py "<folder>"
```

派 vision sub-agent Read 每个 `moment_*.jpg`——**每批最多 15 帧**（20+ 帧超 API body 限制）。每个返回 `frames[{filename, timestamp_sec, transcribed_text, notable, informative, content_type, slide_title}]`。合并 `frames[]` 到 `pass1_scan.json`。

### 图片模式

```powershell
python {baseDir}/scripts/pass1_image/plan_batches.py "<folder>" --key-frames-only --batch-size 15
```

并行派发所有 N 个 sub-agent。每个返回 `{frames[], topic_candidates[], gap_suspicions[]}`。合并到 `pass1_scan.json`。只有 `informative: true` 的帧才可后续嵌入。

## Phase B — Pass 1.5

**必须执行。** 唯一例外：合并所有批次后 `gap_suspicions` 为空。

```powershell
python {baseDir}/scripts/pass15_gaps/resolve_gaps.py "<folder>" --min-priority medium
```

像 Pass 1 一样派发第二轮 sub-agent，把 `frames[]` 合并回 `pass1_scan.json`。

## Phase B — Pass 2

**`pass1_scan.json` 是唯一真相来源。** 正文每条都要对应 `transcribed_text`。

对每个 topic：
1. 过滤 `frames[]` 到该 topic 时间范围，拉出所有 `transcribed_text` 和 `notable`。
2. 挑 1-5 帧嵌入。只有需要转写之外的视觉细节时才 Re-Read。
3. 写 H2 章节：

```markdown
## <N>. <主题名>

### <N>.<M> <子观点>

![<描述性 alt>](screenshots/frame_XXXX_YY.jpg)

<从 slide 转写的原文 / 表格 / 代码 / ASCII 图>

**技术要点 / 设计意图**: <综合分析>
```

文档结构：`视频简介 → 内容结构（ToC）→ ## 1..N → 总结与启发`

**Q&A**：每组问答完整转写，不压缩成"Q&A 涉及：A、B、C 等"。

**总结与启发**：讲者未显式说出的跨章节规律，不是对正文的复述。

收尾：`Read` 草稿 → `Write` 完整终稿覆盖同路径。

**晚期 gap 补救**：Pass 2 发现帧不足时，往 `gap_suspicions` 追加条目，重跑 `resolve_gaps.py`，再派一个 sub-agent。

## 视频类型 → 风格

| 类型 | 重点 |
|---|---|
| 技术分享 | 架构图、代码转写、Inspector 参数、可复用模式 |
| 设计分享 | 具体设计原则、前/后迭代案例、引用 slide 原文 |
| 教程 | 分步列表、UI/键盘操作、最终成果图 |
| 复盘 | 决策时间线、what-worked / what-didn't 表格 |

## 自检清单

- [ ] **S0** — `python -c "from faster_whisper import WhisperModel; print('ok')"` 通过。
- [ ] **S1** — Pass 1 通过 `plan_batches.py` 并行 sub-agent 完成；主 agent 没有自己读帧。
- [ ] **S2** — ToC 标题是主题名，不是时间段。
- [ ] **S3** — 正文每条都能对应 `pass1_scan.json` 的 `transcribed_text`。
- [ ] **S4** — 按需使用表格、code block、ASCII 树。
- [ ] **S5** — 每组 Q&A 有完整问题和有依据的答案，不是一句总结。
- [ ] **S6** — 没有"核心技术要点"前置 section；没有"待深入研究"；未解问题都 inline。
- [ ] **S7** — 总结与启发是跨章节规律，不是对正文的复述。

## 脚本

```
scripts/
├── common/            共用函数
├── fetch/             create_folder, download_video
├── subtitle/          transcribe_audio
├── capture/           capture_ppt_frames, filter_frames, select_key_frames（仅 image_primary）
├── pass1_subtitle/    plan_batches, extract_key_moments
├── pass1_image/       plan_batches
├── pass15_gaps/       resolve_gaps
└── pass2_scaffold/    generate_notes（草稿；Pass 2 主体无脚本）
```
