# Long Text Summarization Guide

This document outlines strategies for summarizing long video content through segmentation and macro review.

## Summarization Strategy

### Overview

For videos longer than 10 minutes, we use a multi-stage summarization approach:

1. **Segmentation** - Divide video into time-based segments
2. **Segment Summarization** - Summarize each segment independently
3. **Macro Review** - Synthesize all segment summaries into a comprehensive overview

This approach ensures we capture both detailed content and the big picture.

---

## Segmentation Strategy

### Time-Based Segmentation

Segment videos based on duration:

| Video Duration | Segments | Segment Duration |
|----------------|----------|------------------|
| < 10 minutes | 1 | Full video |
| 10-30 minutes | 2-3 | ~10 min each |
| 30-60 minutes | 3-6 | ~10 min each |
| 60-120 minutes | 6-10 | ~10 min each |
| > 120 minutes | 8-10 | ~10-15 min each |

### Why Time-Based?

- **Preserves narrative flow** - Content is usually organized temporally
- **Consistent workload** - Each segment has similar token count
- **Easy to reference** - Users can navigate by timestamps
- **Natural breaks** - Videos often have logical breaks every 10-15 minutes

### Alternative Segmentation (Not Implemented)

Other possible approaches:
- **Topic-based**: Use NLP to detect topic shifts
- **Scene-based**: Detect visual/audio transitions
- **Chapter-based**: Use video's built-in chapters (if available)

Time-based is preferred for simplicity and reliability.

---

## Segment Summarization Prompts

### Template for Individual Segments

```
请总结以下视频片段的内容（{start_time} - {end_time}）：

{segment_text}

请提供：
1. 本段主题（一句话）
2. 主要要点（3-5个bullet points）
3. 关键信息（如有数据、引用、重要结论）

用中文回答，保持简洁。
```

### Segment Summary Structure

Each segment summary should include:

1. **Time Range** - When this segment occurs in the video
2. **Theme** - One-sentence description of the segment's focus
3. **Key Points** - 3-5 bullet points covering main content
4. **Notable Information** - Specific data, quotes, or insights

### Example Segment Summary

```
时间段：00:00 - 10:00
主题：介绍AI技术的历史发展和当前状态

主要要点：
• AI概念最早在1950年代由图灵提出
• 经历了两次AI寒冬和当前的第三次浪潮
• 深度学习在2012年ImageNet竞赛后爆发
• 当前大语言模型成为主流技术方向

关键信息：
- 图灵测试是判断机器智能的重要标准
- 2022年ChatGPT发布标志着消费级AI应用的突破
```

---

## Macro Review Strategy

### Purpose

The macro review synthesizes all segment summaries to create:
- A coherent narrative of the entire video
- Identification of overarching themes
- Core arguments and conclusions
- Value proposition for viewers

### Macro Review Prompt Template

```
基于以下视频片段总结，生成整体宏观回顾：

视频信息：
- 标题：{title}
- 作者：{author}
- 时长：{duration}

片段总结：
{segment_summaries}

请生成：

1. **整体概述**（200-300字）：
   - 视频的核心主题和目的
   - 主要叙事线索
   - 整体结构和逻辑

2. **核心观点**（3-5个）：
   - 视频传达的主要论点
   - 重要的发现和结论
   - 对观众的价值

3. **内容框架**（简述）：
   - 视频如何组织内容
   - 各部分之间的关系

用中文回答，语气客观，突出视频的核心价值。
```

### Macro Review Elements

#### 1. Overall Overview (200-300 words)

Include:
- **Hook** - What captures attention in the first 30 seconds
- **Context** - Background information provided
- **Main content** - What the video primarily discusses
- **Structure** - How the video is organized
- **Conclusion** - What viewers should take away

#### 2. Core Insights (3-5 points)

Identify:
- Central thesis or argument
- Key supporting evidence
- Important conclusions
- Practical applications
- Unique perspectives or data

#### 3. Content Framework

Describe:
- Introduction methodology
- Body organization (sequential, thematic, comparative, etc.)
- Conclusion approach
- Transitions between sections

---

## Final Output Structure

### Structured Summary Format

```markdown
## 📺 视频总结

**标题：** {title}
**作者：** {author}
**时长：** {duration}
**平台：** {platform}

### 📝 整体概述
{macro_review_overview}

### ⏱️ 分段要点

**{time_range_1}** {theme_1}
• {point_1}
• {point_2}
• {point_3}

**{time_range_2}** {theme_2}
• {point_1}
• {point_2}
• {point_3}

[... more segments ...]

### 💡 核心观点
1. {core_insight_1}
2. {core_insight_2}
3. {core_insight_3}

### 🏷️ 关键词
{keyword_1}, {keyword_2}, {keyword_3}
```

### Design Rationale

- **Emoji headers** - Visual distinction for scanability
- **Hierarchical structure** - Easy to navigate
- **Time markers** - Reference points for users
- **Bullet points** - Scannable content
- **Consistent format** - Predictable across all summaries

---

## Token Management

### Estimating Token Usage

Approximate tokens needed:

| Component | Tokens (approx) |
|-----------|----------------|
| Video metadata | 100-200 |
| Segment text (per 10 min) | 1000-2000 |
| Segment summary | 200-400 |
| All segment summaries | 500-2000 |
| Macro review | 300-500 |
| Final output | 500-1000 |

### Handling Long Videos

For videos approaching token limits:

1. **Reduce segment detail** - Fewer bullet points per segment
2. **Compress segment text** - Remove filler words, focus on content
3. **Selective summarization** - Focus on most important segments
4. **Chunked processing** - Process in multiple passes if needed

### Token-Saving Strategies

```python
# Remove timestamps from subtitle text (keep in metadata)
clean_text = re.sub(r'\[\d{2}:\d{2}:\d{2}\]', '', text)

# Remove filler words
fillers = ['um', 'uh', 'like', 'you know', 'sort of']
for filler in fillers:
    text = text.replace(filler, '')

# Remove duplicate content
lines = text.split('\n')
unique_lines = list(dict.fromkeys(lines))
text = '\n'.join(unique_lines)
```

---

## Quality Guidelines

### Good Summaries Should

✅ Capture the main ideas and arguments
✅ Include specific data or quotes when relevant
✅ Maintain the video's tone and perspective
✅ Provide context for technical terms
✅ Highlight unique insights or perspectives
✅ Be concise but comprehensive
✅ Use clear, accessible language

### Avoid

❌ Simply listing topics without explaining significance
❌ Adding personal opinions or interpretations
❌ Omitting important conclusions or caveats
❌ Being overly verbose or too brief
❌ Misrepresenting the video's arguments
❌ Including every minor detail

---

## Language Considerations

### Source Language Detection

Check subtitle language:
- YouTube: Check `language` field in subtitle data
- Bilibili: Check `lan` field in subtitle info

### Translation Strategy

If video is not in Chinese:

1. **Keep subtitles in original language** - More accurate for technical terms
2. **Summarize in Chinese** - Standard output language
3. **Note the original language** - In the output header

Example:
```
**原始语言：** English
**总结语言：** 中文
```

### Code-Switching

Some videos mix languages (e.g., English technical terms in Chinese content):

- Preserve technical terms in original language
- Provide translations in parentheses if needed
- Maintain consistency within the summary

---

## Special Cases

### No Subtitles

Handle gracefully:
```
⚠️ 该视频没有可用的字幕。

可能原因：
• UP主/创作者未上传字幕
• 自动字幕功能未开启
• 视频被设为私密或删除

建议：
• 检查视频是否开启CC字幕（YouTube）或AI字幕（Bilibili）
• 寻找其他带字幕的版本
```

### Partial Subtitles

If subtitles exist but are incomplete:
- Note the coverage percentage
- Summarize available portions
- Mention gaps in coverage

### Multi-language Subtitles

If multiple subtitle languages available:
- Prioritize based on user preference or video content
- Chinese > English > Other
- Note which language was used

---

## Testing Checklist

Before deploying, test with:

- [ ] Short video (< 5 min) - Single segment
- [ ] Medium video (10-20 min) - 2-3 segments
- [ ] Long video (30+ min) - Multiple segments
- [ ] YouTube video with manual subtitles
- [ ] YouTube video with auto-generated subtitles
- [ ] Bilibili video with subtitles
- [ ] Video with no subtitles (error handling)
- [ ] Non-English video
- [ ] Video with technical/scientific content
- [ ] Video with rapid topic changes
