# Platform APIs Reference

This document provides detailed information about the APIs and tools used for extracting video information from YouTube and Bilibili.

## YouTube - yt-dlp

### Overview

yt-dlp is a feature-rich command-line audio/video downloader that supports extracting subtitles from YouTube videos. It can download both manually uploaded subtitles and auto-generated captions.

### Installation

```bash
pip install yt-dlp
```

### Basic Usage

Extract video metadata:
```bash
yt-dlp --dump-json --skip-download "VIDEO_URL"
```

Download subtitles:
```bash
yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs "zh,en" "VIDEO_URL"
```

### Key Options

| Option | Description |
|--------|-------------|
| `--dump-json` | Output video metadata as JSON |
| `--skip-download` | Don't download the video file |
| `--write-subs` | Write subtitle file |
| `--write-auto-subs` | Write auto-generated subtitles |
| `--sub-langs` | Specify subtitle languages (comma-separated) |
| `--list-subs` | List available subtitles for a video |

### Subtitle Languages

Common language codes for YouTube:
- `zh` - Chinese (general)
- `zh-CN` - Chinese (Simplified)
- `zh-TW` - Chinese (Traditional)
- `en` - English
- `ja` - Japanese
- `ko` - Korean

### JSON Output Fields

Key fields in yt-dlp JSON output:

```json
{
  "id": "video_id",
  "title": "Video Title",
  "uploader": "Channel Name",
  "duration": 1234,
  "subtitles": {
    "en": [{"url": "...", "ext": "vtt"}]
  },
  "automatic_captions": {
    "en": [{"url": "...", "ext": "vtt"}]
  }
}
```

### Subtitle Format

YouTube provides subtitles in WebVTT (.vtt) format:

```
WEBVTT

00:00:01.000 --> 00:00:05.000
This is the first subtitle

00:00:05.000 --> 00:00:10.000
This is the second subtitle
```

### Common Issues

**No subtitles available:**
- Check if video has subtitles enabled
- Try `--list-subs` to see available options
- Some videos don't have any subtitles

**Region restrictions:**
- Use `--geo-bypass` to attempt bypassing geo-restrictions
- May require proxy configuration

**Rate limiting:**
- YouTube may rate-limit requests
- Add delays between requests if processing multiple videos

---

## Bilibili - bilibili-api-python

### Overview

bilibili-api-python is a Python library that provides access to Bilibili's API. It allows extracting video information, subtitles, and other metadata.

### Installation

```bash
pip install bilibili-api-python
```

### Basic Usage

```python
from bilibili_api import video, ass
import asyncio

async def main():
    # Create video object with BV number
    v = video.Video(bvid="BV1xx411c7mD")
    
    # Get video info (needed for CID)
    info = await v.get_info()
    print(f"Title: {info['title']}")
    print(f"Duration: {info['duration']} seconds")
    print(f"CID: {info['cid']}")
    
    # Method 1: Get subtitles using video.get_subtitle()
    subtitle_info = await v.get_subtitle()
    print(subtitle_info)
    
    # Method 2: Get subtitles using ass module (alternative)
    # This is useful when get_subtitle() doesn't return data
    cid = info['cid']
    subtitle_data = await ass.get_subtitle(bvid="BV1xx411c7mD", cid=cid)
    print(subtitle_data)

asyncio.run(main())
```

### Video Class

#### Constructor Parameters

- `bvid` - BV号 (e.g., "BV1xx411c7mD")
- `aid` - AV号 (alternative to bvid)
- `credential` - Optional credential object for authenticated requests

#### Key Methods

| Method | Description |
|--------|-------------|
| `get_info()` | Get basic video information |
| `get_subtitle()` | Get subtitle information |
| `get_download_url()` | Get video download URLs |

### Video Info Response

```python
{
    "bvid": "BV1xx411c7mD",
    "aid": 12345678,
    "title": "视频标题",
    "desc": "视频描述",
    "duration": 300,
    "owner": {
        "name": "UP主名称",
        "mid": 12345
    },
    "stat": {
        "view": 10000,
        "like": 500,
        "coin": 100
    }
}
```

### Subtitle Response

```python
{
    "subtitles": [
        {
            "id": 123456,
            "lan": "zh-CN",
            "lan_doc": "中文（中国）",
            "is_lock": False,
            "subtitle_url": "https://...",
            "type": 0
        }
    ]
}
```

### Subtitle Format

Bilibili subtitles are provided in JSON format:

```json
{
  "font_size": 0.4,
  "font_color": "#FFFFFF",
  "background_alpha": 0.5,
  "background_color": "#9C27B0",
  "Stroke": "none",
  "body": [
    {
      "from": 0.5,
      "to": 3.5,
      "location": 2,
      "content": "字幕内容"
    }
  ]
}
```

### ASS Module (Alternative Subtitle Access)

The `ass` module provides an alternative way to access subtitles:

```python
from bilibili_api import ass
import asyncio

async def get_subtitles():
    # Get subtitle using BV number and CID
    subtitle_data = await ass.get_subtitle(
        bvid="BV1xx411c7mD",
        cid=123456789
    )
    
    # Parse subtitle entries
    for entry in subtitle_data.get('body', []):
        start_time = entry['from']
        end_time = entry['to']
        content = entry['content']
        print(f"[{start_time:.2f} - {end_time:.2f}] {content}")

asyncio.run(get_subtitles())
```

#### ASS Module Parameters

- `bvid` - BV号 (required)
- `cid` - CID number from video info (required)

#### When to Use ASS Module

Use the `ass` module when:
- `video.get_subtitle()` returns empty or incomplete data
- You need more control over subtitle fetching
- Working with specific subtitle formats

### URL Patterns

Bilibili video URLs come in several formats:

- Standard: `https://www.bilibili.com/video/BV1xx411c7mD`
- With page: `https://www.bilibili.com/video/BV1xx411c7mD?p=2`
- Short link: `https://b23.tv/xxxxx`
- Bangumi: `https://www.bilibili.com/bangumi/play/ss12345`

### Extracting BV Number

```python
import re

def extract_bvid(url: str) -> str:
    # Standard URL
    match = re.search(r'[Bb][Vv]([a-zA-Z0-9]+)', url)
    if match:
        return f"BV{match.group(1)}"
    
    # Short URL - need to resolve redirect
    if 'b23.tv' in url:
        import requests
        response = requests.head(url, allow_redirects=True)
        url = response.url
        match = re.search(r'[Bb][Vv]([a-zA-Z0-9]+)', url)
        if match:
            return f"BV{match.group(1)}"
    
    return None
```

### Common Issues

**No subtitles:**
- Not all Bilibili videos have subtitles
- Check if UP主 uploaded subtitles or enabled AI字幕
- Some videos only have comments (弹幕), not subtitles

**Authentication required:**
- Some videos require login to access
- Create a Credential object with SESSDATA

**Rate limiting:**
- Bilibili has API rate limits
- Add delays between requests
- Consider using credential for higher limits

---

## Error Handling Reference

### Network Errors

```python
import requests
from requests.exceptions import RequestException

try:
    response = requests.get(url, timeout=10)
except RequestException as e:
    print(f"Network error: {e}")
```

### JSON Parsing Errors

```python
import json

try:
    data = json.loads(json_string)
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}")
```

### Subtitle Extraction Errors

Always check if subtitles exist before processing:

```python
subtitles = video_data.get('subtitles', {})
if not subtitles:
    print("No subtitles available for this video")
    return
```

---

## Testing Commands

### Test YouTube Extraction

```bash
# Check available subtitles
yt-dlp --list-subs "https://youtube.com/watch?v=VIDEO_ID"

# Extract metadata only
yt-dlp --dump-json --skip-download "https://youtube.com/watch?v=VIDEO_ID"
```

### Test Bilibili Extraction

```python
from bilibili_api import video
import asyncio

async def test():
    v = video.Video(bvid="BV1xx411c7mD")
    info = await v.get_info()
    print(info['title'])
    subs = await v.get_subtitle()
    print(subs)

asyncio.run(test())
```
