#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Text Summarization Utility
Processes segmented video subtitles and generates summaries with macro review.
"""

import json
import sys
from typing import List, Dict


def create_segment_summary_prompt(segment: Dict) -> str:
    """
    Create a prompt for summarizing a single segment.
    """
    start_time = segment.get('start_formatted', '00:00')
    end_time = segment.get('end_formatted', '00:00')
    text = segment.get('text', '')
    
    if not text.strip():
        return None
    
    prompt = f"""请总结以下视频片段的内容（{start_time} - {end_time}）：

{text}

请提供：
1. 本段主题（一句话）
2. 主要要点（3-5个bullet points）
3. 关键信息（如有数据、引用、重要结论）

用中文回答，保持简洁。"""
    
    return prompt


def create_macro_review_prompt(segment_summaries: List[str], video_info: Dict) -> str:
    """
    Create a prompt for generating macro review from all segment summaries.
    """
    title = video_info.get('title', 'Unknown Video')
    author = video_info.get('author', 'Unknown')
    duration = video_info.get('duration_formatted', '00:00')
    
    summaries_text = "\n\n".join([
        f"=== 片段 {i+1} ===\n{summary}"
        for i, summary in enumerate(segment_summaries)
    ])
    
    prompt = f"""基于以下视频片段总结，生成整体宏观回顾：

视频信息：
- 标题：{title}
- 作者：{author}
- 时长：{duration}

片段总结：
{summaries_text}

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

用中文回答，语气客观，突出视频的核心价值。"""
    
    return prompt


def create_structured_output_prompt(video_info: Dict, segment_summaries: List[str], macro_review: str) -> str:
    """
    Create a prompt for generating the final structured output.
    """
    title = video_info.get('title', 'Unknown')
    author = video_info.get('author', 'Unknown')
    duration = video_info.get('duration_formatted', '00:00')
    platform = video_info.get('platform', 'unknown')
    
    # Parse segment summaries to extract key points
    segments_formatted = []
    for i, summary in enumerate(segment_summaries):
        segments_formatted.append(f"\n**片段 {i+1}**\n{summary}")
    
    prompt = f"""请基于以下信息，生成结构化的视频总结：

视频信息：
- 标题：{title}
- 作者：{author}
- 时长：{duration}
- 平台：{platform}

整体回顾：
{macro_review}

片段要点：
{''.join(segments_formatted)}

请按照以下格式输出：

## 📺 视频总结

**标题：** {title}
**作者：** {author}
**时长：** {duration}
**平台：** {platform.capitalize()}

### 📝 整体概述
[基于整体回顾，撰写200-300字的流畅概述]

### ⏱️ 分段要点

[为每个时间段生成简洁的总结，每个时间段3-5个要点]

### 💡 核心观点
1. [核心观点1]
2. [核心观点2]
3. [核心观点3]

### 🏷️ 关键词
[提取3-5个关键词，用逗号分隔]

请确保内容准确、简洁、结构清晰。"""
    
    return prompt


def process_segments(segments: List[Dict]) -> List[str]:
    """
    Process segments and generate prompts for each.
    Returns list of prompts that should be sent to LLM.
    """
    prompts = []
    
    for segment in segments:
        prompt = create_segment_summary_prompt(segment)
        if prompt:
            prompts.append({
                'time_range': f"{segment.get('start_formatted', '00:00')} - {segment.get('end_formatted', '00:00')}",
                'prompt': prompt,
                'text_length': len(segment.get('text', ''))
            })
    
    return prompts


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python summarize_text.py --segments '<json_segments>'", file=sys.stderr)
        sys.exit(1)
    
    # Parse arguments
    if sys.argv[1] == '--segments' and len(sys.argv) >= 3:
        try:
            segments_data = json.loads(sys.argv[2])
            
            if isinstance(segments_data, dict) and 'segments' in segments_data:
                segments = segments_data['segments']
                video_info = {
                    'title': segments_data.get('title', 'Unknown'),
                    'author': segments_data.get('author', 'Unknown'),
                    'duration_formatted': segments_data.get('duration_formatted', '00:00'),
                    'platform': segments_data.get('platform', 'unknown')
                }
            else:
                segments = segments_data
                video_info = {}
            
            # Generate prompts for each segment
            prompts = process_segments(segments)
            
            # Output as JSON
            output = {
                'video_info': video_info,
                'segment_count': len(segments),
                'segment_prompts': prompts,
                'next_step': 'Send each segment_prompt to LLM for summarization, then use macro_review_prompt for final synthesis'
            }
            
            print(json.dumps(output, ensure_ascii=False, indent=2))
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Invalid arguments. Use --segments '<json>'", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
