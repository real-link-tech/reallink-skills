---
name: video-summary
description: This skill should be used when the user asks to "总结视频" (summarize video), "分析视频" (analyze video), "视频讲了什么" (what does video say), "summarize this video", or when they share YouTube/Bilibili links. Extracts subtitles and provides comprehensive summaries with segmented analysis and macro review.
version: 0.1.0
---

# Video Summary Skill

## Overview

Extract subtitles from YouTube and Bilibili videos and generate comprehensive summaries with key points. This skill processes existing subtitles only (no audio transcription) and uses a segmented approach for long videos followed by a macro review.

## When to Use

Trigger this skill when users:
- Ask to "总结视频" (summarize video)
- Ask to "分析视频" (analyze video)
- Say "视频讲了什么" (what does this video say)
- Share YouTube or Bilibili links
- Ask for "视频总结" (video summary)
- Request "summarize this video" or "video summary"

## Quick Reference

### Supported Platforms
- **YouTube**: youtube.com, youtu.be
- **Bilibili**: bilibili.com, b23.tv

### Workflow
1. Detect video platform from URL
2. Extract video metadata and subtitles using Python scripts
3. Segment subtitles by time windows
4. Summarize each segment
5. Generate macro review from all segments
6. Output structured summary

## Execution Steps

### Step 1: URL Detection

Identify the platform from the URL pattern:
- YouTube: `youtube.com/watch?v=`, `youtu.be/`
- Bilibili: `bilibili.com/video/BV`, `b23.tv/`

### Step 2: Extract Video Information

Execute the extraction script:

```bash
python scripts/extract_video_info.py "<video_url>"
```

The script returns JSON with:
- `platform`: Video platform (youtube/bilibili)
- `title`: Video title
- `author`: Channel/UP主 name
- `duration`: Duration in seconds
- `duration_formatted`: Human-readable duration
- `subtitles`: Array of subtitle segments with text and timestamps
- `segments`: Pre-segmented subtitle chunks for processing

### Step 3: Process Video Data

Parse the JSON output:
- Check if subtitles exist (if empty, inform user no subtitles available)
- Calculate number of segments based on duration
- Prepare segments for individual summarization

Segmentation rules:
- <10 minutes: 1 segment
- 10-30 minutes: 2-3 segments
- >30 minutes: 1 segment per 10 minutes, max 8-10 segments

### Step 4: Summarize Segments

For each segment, generate a summary covering:
- Main topics discussed
- Key points and arguments
- Important quotes or data

Use the summarization script if needed:

```bash
python scripts/summarize_text.py --segments '<json_segments>'
```

Or perform summarization directly using LLM capabilities.

### Step 5: Generate Macro Review

Combine all segment summaries into a comprehensive macro review:
- Overall theme and purpose
- Key narrative arc
- Core arguments and conclusions
- Target audience and value proposition

Reference `references/summarization-guide.md` for macro review strategies.

### Step 6: Output Structured Summary

Present results in this format:

```markdown
## 📺 视频总结

**标题：** [Video Title]
**作者：** [Author/Channel]
**时长：** [Duration]
**平台：** [YouTube/Bilibili]

### 📝 整体概述
[Macro review - 200-300 words comprehensive overview]

### ⏱️ 分段要点

**00:00 - 05:00** [Section Theme]
- Key point 1
- Key point 2
- ...

**05:00 - 10:00** [Section Theme]
- ...

### 💡 核心观点
1. [Core insight 1]
2. [Core insight 2]
3. [Core insight 3]

### 🏷️ 关键词
[Keyword 1], [Keyword 2], [Keyword 3]
```

## Bilibili Authentication

Bilibili videos require authentication to access subtitles. You need to provide your Bilibili SESSDATA.

### Get SESSDATA

**Method 1: Follow the documentation**
1. Visit: https://nemo2011.github.io/bilibili-api/#/get-credential
2. Follow the instructions to get your SESSDATA
3. Copy the SESSDATA and provide it when prompted

**Method 2: Browser DevTools**
1. Login to bilibili.com in your browser
2. Press F12 to open Developer Tools
3. Go to: Application → Cookies → https://www.bilibili.com
4. Find the "SESSDATA" field and copy its value

### First-time Setup

When you run the script for the first time with a Bilibili URL, it will prompt you for SESSDATA:

```bash
python scripts/extract_video_info.py "https://bilibili.com/video/BVxxx"
# Script will ask: "请粘贴 SESSDATA: "
```

Just paste your SESSDATA and it will be saved to `config/auth.json` for future use.

### Security Note

- SESSDATA is your login credential, **never share it with others**
- Credentials are stored locally in `config/auth.json` (excluded from git via .gitignore)
- Delete `config/auth.json` at any time to clear credentials

## Error Handling

### No Subtitles Available
If the video has no subtitles or closed captions:
```
⚠️ 该视频没有可用的字幕。此技能仅处理带有字幕或CC字幕的视频。

建议：
1. 检查视频是否开启CC字幕
2. 寻找带字幕的版本
3. 使用其他支持音频转录的工具
```

### Bilibili Authentication Required
If Bilibili authentication is needed:
```
⚠️  需要 Bilibili 登录认证

该视频的字幕需要登录后才能访问。

获取 SESSDATA 的方法:
1. 访问: https://nemo2011.github.io/bilibili-api/#/get-credential
2. 或浏览器 F12 → Application → Cookies → bilibili.com → 复制 SESSDATA
3. 重新运行脚本并粘贴 SESSDATA
```

### Invalid URL
```
❌ 无法识别该链接。请提供有效的 YouTube 或 Bilibili 视频链接。

支持的格式：
- YouTube: https://youtube.com/watch?v=XXX 或 https://youtu.be/XXX
- Bilibili: https://bilibili.com/video/BVXXX 或 https://b23.tv/XXX
```

### Video Unavailable
```
❌ 无法访问该视频。可能的原因：
- 视频已删除或设为私有
- 地区限制
- 网络连接问题
```

## Additional Resources

### Reference Files

- **`references/platform-apis.md`** - Detailed API documentation for YouTube (yt-dlp) and Bilibili subtitle extraction
- **`references/summarization-guide.md`** - Long text summarization strategies, segmentation approaches, and macro review methodologies

### Scripts

- **`scripts/extract_video_info.py`** - Main video information extraction script supporting both platforms
- **`scripts/summarize_text.py`** - Text summarization utility for processing segments
- **`scripts/requirements.txt`** - Python dependencies (yt-dlp, bilibili-api-python)

## Best Practices

1. **Always verify subtitle availability** before attempting summarization
2. **Use time-based segmentation** to maintain context and narrative flow
3. **Generate macro review last** after all segments are processed
4. **Preserve timestamps** in output for user reference
5. **Handle errors gracefully** with clear, actionable messages

## Limitations

- Requires existing subtitles/CC (no audio transcription)
- YouTube: Requires video to have manual captions or auto-generated CC
- Bilibili: 
  - Some videos require Bilibili login (sessdata) to access subtitles
  - Official videos and premium content often have this restriction
  - Skill will detect this and provide clear error message
- Very long videos (>2 hours) may hit token limits; consider summarizing in chunks
