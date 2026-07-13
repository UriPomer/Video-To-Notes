---
name: video-summarizer
description: 将 Bilibili、YouTube 等视频整理成有证据支撑的中文结构化笔记。适用于下载视频、提取或转录字幕、分析幻灯片与画面、生成技术笔记、补齐证据缺口、校验并清理交付物；尤其适合演讲、教程和技术分享。
---

# 视频总结

本文件是唯一权威流程。目标不是“生成一份 Markdown”，而是交付一篇可独立阅读、结论可追溯、图片有信息量的中文笔记。

## 不可违反的约束

- 在 Windows PowerShell 中运行命令。
- 最终文件只能是 `<folder>/notes.md`；自动骨架写入 `notes.draft.md`，不得把草稿直接交付。
- 最终笔记不得包含“帧索引”“元数据”“核心技术要点”前置卡片、“待深入研究”、内部工作指令或占位文字。
- 最终笔记必须以主题组织 H2，不得按固定时间段切章，不得把讲者自我介绍单独成章。
- 每个正文 H2 引用 1—5 张有信息量的图片；不要使用黑屏、Logo、纯讲者、过渡页或近似重复图。
- 图片路径只能使用 `screenshots/文件名.jpg` 一类相对路径；图片说明必须描述信息，不能暴露内部帧文件名。
- 幻灯片中的参数、代码、表格、节点和非中文文字必须忠实读取；非中文内容默认翻译成中文。
- 每条事实、参数和可见文字必须能追溯到字幕或 `pass1_scan.json` 的画面记录；推导内容必须明确写成综合分析，不能伪装成讲者原话。
- `总结与启发` 必须给出跨主题规律、可迁移方法和边界条件，不能重复目录。
- 只有严格验证通过后才能声明完成。

优质成品参考：`examples/good_notes_phasmophobia.md`。

## 0. 环境与目录

从 skill 目录安装依赖：

```powershell
pip install -r requirements.txt
```

确认 `ffmpeg` 在 `PATH`。所有后续命令从仓库根目录运行，脚本路径写成 `.codebuddy\skills\video-summarizer\scripts\...`。

不要删除、重命名或重新生成已有笔记目录，除非用户明确要求。

YouTube 在 Windows 上需要 Node.js 22+ 和 EJS challenge solver。下载脚本优先读取 `%USERPROFILE%\.codex\secrets\videonotes-youtube-cookies.txt`；Cookie 失效时完全关闭 Vivaldi，再用 `--cookies-from-browser vivaldi --cookies <私密路径>` 刷新。Cookie 只能保存在用户私密目录，禁止显示、写入项目或提交 Git。不得用视频 ID 冒充正常标题。

## 1. 获取视频

```powershell
python .codebuddy\skills\video-summarizer\scripts\fetch\create_folder.py "<video_url>"
python .codebuddy\skills\video-summarizer\scripts\fetch\download_video.py "<video_url>" "<folder>"
```

需要按系列归档时，在创建阶段指定输出根目录，例如：

```powershell
python .codebuddy\skills\video-summarizer\scripts\fetch\create_folder.py "<video_url>" --output-root "notes\Unreal-Fest"
```

Bilibili 上 `yt-dlp` 遇到 412 后转由 `you-get` 处理可能是正常降级。

## 2. 获取字幕并选择路线

```powershell
python -u .codebuddy\skills\video-summarizer\scripts\subtitle\transcribe_audio.py "<folder>"
```

默认使用 `medium + CPU`。只有用户要求或环境已确认适合时才显式使用 GPU：

```powershell
python -u .codebuddy\skills\video-summarizer\scripts\subtitle\transcribe_audio.py "<folder>" --whisper-model large-v3 --device cuda
```

GPU 失败时脚本会自动回退 CPU。只要命令没有非零退出且写出了 `subtitles.json`，就等待其自然完成，不要中途重试。
转录期间脚本每分钟输出一次存活提示；该提示不表示卡死或需要重启。

读取 `subtitles.json.mode`：

- `subtitle_primary`：先分析字幕，只对关键时刻抽图。
- `image_primary`：先完成幻灯片截帧与筛选。

## 3A. 字幕优先路线

生成可恢复的字幕批次计划：

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass1_subtitle\plan_batches.py "<folder>"
```

`pass1_subtitle_plan.json` 保存完整字幕正文。重启或上下文压缩后必须从该文件恢复，不得依赖先前终端输出或记忆。

默认只打印计划摘要；只有需要复制完整代理提示时才添加 `--print-prompts`。执行计划中的全部批次；按可用并发上限分波次处理，不能只处理部分批次。每个批次必须把纯 JSON 结果写入 `<folder>/pass1_results/batch_NNN.json`，然后确定性合并：

```powershell
python .codebuddy\skills\video-summarizer\scripts\merge_results.py "<folder>" --stage pass1
```

合并器只有在 `plan_id` 一致且计划中的全部批次结果齐全时才写入 `<folder>/pass1_scan.json`。扫描文件从计划和批次结果原样保留：

- `plan_type`、`plan_id`。
- `completed_batch_indexes`：已合并的全部 batch index；最终必须与计划完全一致。

- `topic_candidates`：主题、开始时间、字幕证据。
- `key_moments`：建议截图时间、原因、内容类型、优先级。
- `gap_suspicions`：疑似存在图示或代码但字幕不足的区间、原因、优先级和状态。

根据关键时刻抽帧：

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass1_subtitle\extract_key_moments.py "<folder>"
```

该命令同时生成 `pass1_frame_plan.json`。按计划读取全部 `moment_*.jpg`，每批结果写入 `<folder>/pass1_frame_results/batch_NNN.json`，再运行：

```powershell
python .codebuddy\skills\video-summarizer\scripts\merge_results.py "<folder>" --stage keyframes
```

合并后的视觉记录位于 `pass1_scan.json.frames`。每帧至少记录：

```text
filename, timestamp_sec, transcribed_text, notable,
informative, content_type, slide_title
```

如果当前模型无法读取图片，不要丢弃已经抽出的截图。使用 `key_moments[].reason` 和邻近字幕为图片写有依据的说明，并在证据记录中标明视觉不可用。

## 3B. 图片优先路线

```powershell
python .codebuddy\skills\video-summarizer\scripts\capture\capture_ppt_frames.py "<folder>\video.mp4" "<folder>\screenshots" --scale 800
python .codebuddy\skills\video-summarizer\scripts\capture\filter_frames.py "<folder>\screenshots"
python .codebuddy\skills\video-summarizer\scripts\capture\select_key_frames.py "<folder>\screenshots"
python .codebuddy\skills\video-summarizer\scripts\pass1_image\plan_batches.py "<folder>" --key-frames-only --batch-size 15
```

默认只打印摘要；需要完整代理提示时添加 `--print-prompts`。按可用并发上限分波次执行全部批次，每批最多 15 张，将每批纯 JSON 写入 `<folder>/pass1_results/batch_NNN.json`，再运行：

```powershell
python .codebuddy\skills\video-summarizer\scripts\merge_results.py "<folder>" --stage pass1
```

合并结果包含 `{frames[], topic_candidates[], gap_suspicions[]}`、计划的 `plan_type`、`plan_id` 和完整 `completed_batch_indexes`。只有 `informative: true` 的图片可进入正文。优先保留标题页、参数页、代码、架构图、对照图和有效 Q&A 画面。

## 4. 补齐证据缺口

合并完全部 Pass 1 批次后检查 `gap_suspicions`。只要存在中、高优先级缺口就必须执行：

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass15_gaps\resolve_gaps.py "<folder>"
```

该命令默认每个缺口最多保留 6 帧、全局最多 60 帧，并使用代表性抽样限制近似重复图。只有确认确需更多证据时才显式提高 `--max-frames-per-gap` 或 `--max-total-frames`。默认只打印摘要；需要完整提示时添加 `--print-prompts`。

按 `pass1_gaps_plan.json` 读取新帧，每批结果写入 `<folder>/pass15_results/batch_NNN.json`，然后运行：

```powershell
python .codebuddy\skills\video-summarizer\scripts\merge_results.py "<folder>" --stage pass15
```

合并器校验计划身份、完整批次和精确帧集合后，才把第二轮 `frames[]` 合并回 `pass1_scan.json`：

- 证据已补齐：写入 `"status": "resolved"`。
- 确实无法确认：写入 `"status": "documented"` 和非空 `"resolution_note"`，并在相关正文内说明证据边界。

不得为了通过验证而把未处理的缺口标成 `resolved`，也不能另建“待深入研究”章节。

## 5. 写作

生成不会污染最终文件的中文骨架：

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass2_scaffold\generate_notes.py "<folder>" --ppt
```

`notes.draft.md` 是已忽略的临时文件，不得加入版本控制；完成 `notes.md` 后可保留本地草稿，但交付与提交范围只能包含成品。

阅读 `notes.draft.md`、`pass1_scan.json`、字幕和所选图片，然后完成 `notes.md`。头部必须包含来源、作者、日期、时长和标签；缺少可靠信息时明确写“未知（元数据未获取）”，禁止猜测。正文采用以下结构：

```markdown
# 视频标题

> 来源 / 作者 / 日期 / 时长 / 标签

## 视频简介

## 内容结构

## 1. 主题

### 1.1 子主题

![有意义的图片说明](screenshots/xxx.jpg)

正文、表格、代码块或 ASCII 图

**技术要点 / 设计意图**: 综合提炼

## 总结与启发
```

信息形式必须匹配内容：参数清单用表格，层级或架构图用 ASCII 树，代码用 fenced code block，前后差异用对照表。Q&A 必须写出实际问题和完整、有依据的回答。

写每个主题前，按时间范围收集对应 `frames[].transcribed_text`、`frames[].notable` 和字幕上下文；每个 H2 使用 1—5 张图，通常每个子观点选择 1—2 张最有信息量的图。

每完成一个 H2 就立即回查对应字幕与图片。若发现证据或截图不足，立即向 `gap_suspicions` 追加条目，重新运行缺口解析并合并新证据，不能用无依据概括绕过缺口。

### 按视频类型调整表达

| 类型 | 重点 |
|------|------|
| 技术分享 | 架构图、代码、参数、性能数据和可复用机制 |
| 设计分享 | 具体原则、迭代前后对照和案例证据 |
| 教程 | 有顺序的操作步骤、UI/快捷键和最终结果图 |
| 项目复盘 | 决策时间线、有效/无效方案及其原因 |

## 6. 验证、清理与完成门禁

先做写作阶段验证：

```powershell
python .codebuddy\skills\video-summarizer\scripts\validate\validate_notes.py "<folder>"
```

修完所有错误后预览未引用截图：

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass2_scaffold\prune_screenshots.py "<folder>" --dry-run
```

人工确认预览只包含未引用候选图后，才执行清理：

```powershell
python .codebuddy\skills\video-summarizer\scripts\pass2_scaffold\prune_screenshots.py "<folder>"
```

最后运行严格验证：

```powershell
python .codebuddy\skills\video-summarizer\scripts\validate\validate_notes.py "<folder>" --strict
```

严格验证失败时继续修复，不得报告完成。严格验证通过后，再汇报 `notes.md` 路径、图片数量和仍需用户判断的证据边界（如有）。

严格验证会核对 Pass 1、关键帧视觉扫描和 Pass 1.5 的计划身份及完成批次，并拒绝正文引用 `informative: false` 的图片。它不能代替人工证据检查。完成前再确认：全部批次已合并；事实与参数均可追溯；Q&A 没有压缩成主题列表；总结给出了跨主题规律而非目录复述。

严格验证依赖本地的计划和扫描 JSON，是生成阶段门禁。`notes/` 默认忽略这些 JSON，因此远程仓库只保存成品笔记和截图，不能在全新克隆中复现证据门禁；如需远程审计，必须由用户明确决定调整 `notes/.gitignore` 或另行提交证据文件。

## 恢复与幂等规则

- 已存在 `video.*`、`metadata.json` 或 `subtitles.json` 时先校验再复用，不重复下载或转录。
- `notes.md` 已存在时，生成骨架也不得覆盖它。
- 重新运行缺口解析时跳过已标记为 `resolved` 或 `documented` 的条目。
- 上下文压缩、会话中断或接手他人工作后，按文件状态恢复：`subtitles.json` → `pass1_*_plan.json` → 各阶段 `*_results/batch_NNN.json` → `pass1_scan.json` → `notes.draft.md` → `notes.md` → 严格验证。
- 中间 JSON 是证据与恢复状态，不是最终笔记内容；不要把它们复制进成品。
