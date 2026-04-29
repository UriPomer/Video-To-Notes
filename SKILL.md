---
name: video-summarizer
description: "Download videos from Bilibili/YouTube, capture slide screenshots, and generate topic-organized notes via parallel sub-agent vision analysis."
version: 2.2.0
---

# Video Summarizer

Scripts prepare material → parallel sub-agents scan → main agent writes topic-based notes.

Reference output: `{baseDir}/examples/good_notes_phasmophobia.md` — treat it as the quality bar.

## Prerequisites

```powershell
# Windows: PowerShell only — Git Bash's python fails with exit 127
# In CodeBuddy Code, invoke the PowerShell tool, never Bash, for Python commands here.
pip install yt-dlp you-get opencv-python numpy faster-whisper
# ffmpeg must be on PATH
```

Verify faster-whisper works: `python -c "from faster_whisper import WhisperModel; print('ok')"`

**Windows GPU one-time setup** (needed if transcription crashes with exit -1073740791):

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

## Phase A — Step-by-Step (PowerShell)

### Step 1 — Create folder

```powershell
python {baseDir}/scripts/fetch/create_folder.py "<video_url>"
```

Prints folder path. 412 errors in stderr are normal for Bilibili; folder is created anyway.

### Step 2 — Download video

```powershell
python {baseDir}/scripts/fetch/download_video.py "<video_url>" "<folder>"
```

Bilibili: yt-dlp fails with 412 → you-get takes over. Both are expected. Do not retry.

### Step 3 — Transcribe audio (BLOCKING — just wait, do not background or poll)

```powershell
python -u {baseDir}/scripts/subtitle/transcribe_audio.py "<folder>"
```

Done when you see: `[transcribe_audio] mode=subtitle_primary source=whisper_local chars=XXXX ...`

- In CodeBuddy Code, use the PowerShell tool for this step with `timeout: 600000`. Never use Bash.
- GPU (large-v3, default): 2-10 min. CPU fallback: up to 30 min. Both are normal.
- Exit -1073740791 = CUDA DLLs missing → run Windows GPU setup above, retry.

Read `subtitles.json.mode` after this step to decide Step 4.

### Step 4a — Frame capture (image_primary only)

```powershell
python {baseDir}/scripts/capture/capture_ppt_frames.py "<folder>/video.mp4" "<folder>/screenshots" --scale 800
python {baseDir}/scripts/capture/filter_frames.py "<folder>/screenshots"
python {baseDir}/scripts/capture/select_key_frames.py "<folder>/screenshots"
```

### Step 4b — Skip (subtitle_primary)

No frame capture needed.

### Step 5 — Generate draft scaffold

```powershell
python {baseDir}/scripts/pass2_scaffold/generate_notes.py "<folder>" --ppt
```

Phase A complete. Proceed to Phase B.

## Core Rules

| # | Rule |
|---|---|
| R1 | **ToC is topic-based.** H2 headings come from slide title cards ("Sensor Toolkit"), never from self-introduction time ranges. |
| R2 | **Every embedded frame adds information.** Drop black, pure transitions, speaker-only, logos, near-duplicates. |
| R3 | **Transcribe visible text verbatim.** Slide titles, Inspector params, code, mind-map nodes, comparison tables. Translate non-Chinese text directly into Chinese; do not keep the original alongside. |
| R4 | **Match primitive to content.** Diagram → ASCII tree in fenced block. Params/list → table. Code → fenced code block. Before/after → 2-col table. |
| R5 | **1-5 frames per H2 section.** Pick the one or two most informative frames per sub-idea. |
| R6 | **Resolve questions or inline them.** Unresolved points go inline as `*（演讲中未展开：...）*` at the end of the relevant topic — never a standalone "待深入研究" section. |
| R7 | **Embed frames only via markdown image syntax.** Use `![meaningful caption](screenshots/xxx.jpg)`. Never surface internal filenames like `frame_NNNN_MM.jpg` or `gap_SSSS_EEEE_NNN.jpg` as headings, bullets, or labels. |

## Phase B — Pass 1

Check `subtitles.json.mode` first.

### Subtitle-primary

```powershell
python {baseDir}/scripts/pass1_subtitle/plan_batches.py "<folder>"
```

Prints ready-to-paste prompts. Dispatch all N sub-agents in parallel (one message, N `Agent` calls, `subagent_type="general-purpose"`). Each returns `{topic_candidates[], key_moments[], gap_suspicions[]}`. Merge into `pass1_scan.json`.

### Pass 1.3 — Extract frames (subtitle mode only)

```powershell
python {baseDir}/scripts/pass1_subtitle/extract_key_moments.py "<folder>"
```

Then dispatch vision sub-agents to Read each `moment_*.jpg` — **15 frames per batch max** (20+ exceeds API body limit). Each returns `frames[{filename, timestamp_sec, transcribed_text, notable, informative, content_type, slide_title}]`. Merge `frames[]` into `pass1_scan.json`.

### Image-primary

```powershell
python {baseDir}/scripts/pass1_image/plan_batches.py "<folder>" --key-frames-only --batch-size 15
```

Dispatch all N sub-agents in parallel. Each returns `{frames[], topic_candidates[], gap_suspicions[]}`. Merge into `pass1_scan.json`. A frame is eligible only if `informative: true`.

## Phase B — Pass 1.5

**Always run Pass 1.5.** Skip only if `gap_suspicions` is empty after merging all Pass 1 batches.

```powershell
python {baseDir}/scripts/pass15_gaps/resolve_gaps.py "<folder>" --min-priority medium
```

Dispatch round-2 sub-agents the same way as Pass 1. Merge their `frames[]` into `pass1_scan.json`.

## Phase B — Pass 2

**`pass1_scan.json` is the only source of truth.** Every claim must cite a `transcribed_text` entry.

For each topic:
1. Filter `frames[]` to the topic's timestamp range. Pull all `transcribed_text` and `notable`.
2. Pick 1-5 frames to embed. Re-Read only if transcription isn't enough.
3. Write the H2 section:

```markdown
## <N>. <Topic name>

### <N>.<M> <Sub-idea>

![<descriptive alt>](screenshots/frame_XXXX_YY.jpg)

<Transcribed text / table / code / ASCII diagram>

**技术要点 / 设计意图**: <synthesis>
```

Document layout: `视频简介 → 内容结构 (ToC) → ## 1..N → 总结与启发`

**Q&A**: transcribe each exchange fully — never compress to "Q&A 涉及：A、B、C 等".

**总结与启发**: cross-cutting patterns the speaker didn't make explicit. Not a re-summary.

Finalize: `Read` draft → `Write` complete final document to same path.

**Late-stage gap**: if a topic has insufficient frames during Pass 2, append to `gap_suspicions`, re-run `resolve_gaps.py`, dispatch one more sub-agent.

## Style by video type

| Type | Emphasis |
|---|---|
| Tech talk | Architecture diagrams, code transcription, Inspector params, re-usable patterns |
| Design talk | Concrete design principles, before/after iteration cases, quoted slide text |
| Tutorial | Step-by-step list, UI/keyboard actions, final-result screenshot |
| Postmortem | Timeline of decisions, what-worked / what-didn't tables |

## Self-Check

- [ ] **S0** — `python -c "from faster_whisper import WhisperModel; print('ok')"` passes.
- [ ] **S1** — Pass 1 used parallel sub-agents via `plan_batches.py`; main agent never Read frames directly.
- [ ] **S2** — ToC headings are topic names, not time ranges.
- [ ] **S3** — Every body claim traces to `transcribed_text` in `pass1_scan.json`.
- [ ] **S4** — Tables, code blocks, ASCII trees used where content demands.
- [ ] **S5** — Each Q&A exchange has question + grounded answer, not a one-line summary.
- [ ] **S6** — No "核心技术要点" pre-section; no "待深入研究". Unresolved points are inline.
- [ ] **S7** — 总结与启发 contains cross-cutting patterns, not a re-summary of topics.

## Scripts

```
scripts/
├── common/            shared helpers
├── fetch/             create_folder, download_video
├── subtitle/          transcribe_audio
├── capture/           capture_ppt_frames, filter_frames, select_key_frames  (image_primary only)
├── pass1_subtitle/    plan_batches, extract_key_moments
├── pass1_image/       plan_batches
├── pass15_gaps/       resolve_gaps
└── pass2_scaffold/    generate_notes (draft only; Pass 2 main body has no script)
```
