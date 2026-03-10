#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Smart Video Extractor with Auto-Auth
Aut
omatically detects auth requirement and guide
s user through setup
"""

import json

# Try to import youtube-transcript-api for fallback subtitle extraction
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    YOUTUBE_TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_API_AVAILABLE = False

import 
re
import sys
import subprocess
from pathlib 
import Path
from typing import Dict, List, Op
tional, Tuple
from dataclasses import datacla
ss, asdict


@dataclass
class VideoInfo:
    
"""Video information data structure"""
    pl
atform: str
    title: str
    author: str
  
  duration: int
    duration_formatted: str
 
   subtitles: List[Dict]
    segments: List[D
ict]
    error: Optional[str] = None


def ge
t_config_dir() -> Path:
    """Get the config
 directory path, works in any environment"""

    # Try multiple methods to find the correc
t path
    script_dir = Path(__file__).parent
.absolute()
    config_dir = script_dir.paren
t / "config"
    
    # If config directory d
oesn't exist, create it
    if not config_dir
.exists():
        config_dir.mkdir(parents=T
rue, exist_ok=True)
    
    return config_di
r


def check_bilibili_auth() -> bool:
    ""
"Check if Bilibili authentication is configur
ed"""
    try:
        config_dir = get_confi
g_dir()
        config_file = config_dir / "a
uth.json"
        
        if not config_file
.exists():
            # Create empty config 
file
            config = {"sessdata": "", "p
latform": "bilibili"}
            with open(c
onfig_file, 'w', encoding='utf-8') as f:
    
            json.dump(config, f, ensure_ascii
=False, indent=2)
            return False
  
      
        with open(config_file, 'r', en
coding='utf-8') as f:
            config = js
on.load(f)
        return bool(config.get('se
ssdata') and config.get('sessdata').strip())

    except Exception as e:
        print(f"Wa
rning: Error checking auth config: {e}", file
=sys.stderr)
        return False


def save_
bilibili_auth(sessdata: str) -> bool:
    """
Save Bilibili authentication to config file""
"
    try:
        config_dir = get_config_di
r()
        config_file = config_dir / "auth.
json"
        
        config = {
           
 "sessdata": sessdata,
            "platform"
: "bilibili"
        }
        
        with 
open(config_file, 'w', encoding='utf-8') as f
:
            json.dump(config, f, ensure_asc
ii=False, indent=2)
        
        return T
rue
    except Exception as e:
        print(
f"Error saving auth config: {e}", file=sys.st
derr)
        return False


def auto_setup_b
ilibili_auth():
    """Interactive setup for 
Bilibili authentication with detailed instruc
tions"""
    print("\n" + "="*70)
    print("
🔐 需要 Bilibili 认证")
    print("="*7
0)
    print()
    print("此视频需要 Bil
ibili 登录才能获取字幕。")
    print
()
    print("📋 获取 SESSDATA 的详细�
��骤：")
    print()
    print("方法 1 - 
使用文档（推荐）：")
    print("   1
. 访问: https://nemo2011.github.io/bilibili
-api/#/get-credential")
    print("   2. 按�
��页面上的说明操作")
    print("   3.
 复制获取到的 SESSDATA")
    print()
  
  print("方法 2 - 手动获取：")
    pri
nt("   1. 打开 Chrome/Edge 浏览器")
    
print("   2. 访问 https://www.bilibili.com 
并登录你的账号")
    print("   3. 按 
F12 打开开发者工具")
    print("   4. 
点击 'Application' (应用) 标签")
    pr
int("   5. 左侧找到 'Storage' → 'Cookie
s' → 'https://www.bilibili.com'")
    print
("   6. 在右侧列表中找到 'SESSDATA' �
��")
    print("   7. 双击 Value 列的值�
��复制完整内容")
    print()
    print(
"⚠️  安全提示：")
    print("   • 
SESSDATA 是你的登录凭证，请勿分享
给他人")
    print("   • 凭证将保存
在本地 config/auth.json 文件中")
    pr
int("   • 可随时删除该文件清除登
录状态")
    print()
    print("-"*70)
   
 
    try:
        sessdata = input("\n请粘
贴 SESSDATA (或按回车取消): ").strip()

    except EOFError:
        # Non-interacti
ve environment
        print("\n❌ 无法读
取输入，请重试")
        return False

    except KeyboardInterrupt:
        print("
\n\n❌ 用户取消")
        return False
 
   
    if not sessdata:
        print("\n❌
 未输入 SESSDATA，操作取消")
        
return False
    
    # Validate input looks 
like SESSDATA
    if len(sessdata) < 20:
    
    print("\n⚠️  输入的内容看起来
不像是有效的 SESSDATA（太短了）")

        retry = input("是否重新输入? (y
/n): ").strip().lower()
        if retry == '
y':
            return auto_setup_bilibili_au
th()
        return False
    
    # Save to 
config
    if save_bilibili_auth(sessdata):
 
       print(f"\n✅ 认证信息已保存！
")
        print(f"   位置: {get_config_dir
() / 'auth.json'}")
        return True
    e
lse:
        print("\n❌ 保存认证信息�
��败")
        return False


def identify_p
latform(url: str) -> Optional[str]:
    """Id
entify video platform from URL"""
    youtube
_patterns = [
        r'youtube\.com/watch\?v
=',
        r'youtu\.be/',
        r'youtube\
.com/shorts/'
    ]
    bilibili_patterns = [

        r'bilibili\.com/video/[Bb][Vv]',
   
     r'b23\.tv/',
        r'bilibili\.com/ban
gumi/play/'
    ]
    
    url_lower = url.lo
wer()
    
    for pattern in youtube_pattern
s:
        if re.search(pattern, url_lower):

            return 'youtube'
    
    for pat
tern in bilibili_patterns:
        if re.sear
ch(pattern, url_lower):
            return 'b
ilibili'
    
    return None


def format_du
ration(seconds: int) -> str:
    """Format du
ration in seconds to human-readable string"""

    hours = seconds // 3600
    minutes = (s
econds % 3600) // 60
    secs = seconds % 60

    
    if hours > 0:
        return f"{hour
s}:{minutes:02d}:{secs:02d}"
    else:
      
  return f"{minutes}:{secs:02d}"


def calcul
ate_segments(duration: int) -> List[Tuple[int
, int]]:
    """Calculate time segments based
 on video duration"""
    if duration < 600: 
 # < 10 minutes
        return [(0, duration)
]
    elif duration < 1800:  # 10-30 minutes

        segment_duration = duration // 3
    
    return [
            (0, segment_duration
),
            (segment_duration, segment_dur
ation * 2),
            (segment_duration * 2
, duration)
        ]
    else:  # > 30 minut
es
        segment_duration = 600  # 10 minut
es per segment
        segments = []
        
for start in range(0, duration, segment_durat
ion):
            end = min(start + segment_d
uration, duration)
            segments.appen
d((start, end))
            if len(segments) 
>= 10:  # Max 10 segments
                bre
ak
        return segments


def extract_yout
ube_info(url: str) -> VideoInfo:
    """Extra
ct information from YouTube video using yt-dl
p Python API"""
    try:
        try:
       
     import yt_dlp
            import request
s
        except ImportError as e:
          
  return VideoInfo(
                platform=
'youtube',
                title='',
        
        author='',
                duration=0
,
                duration_formatted='',
    
            subtitles=[],
                seg
ments=[],
                error=f"Missing dep
endency: {e}. Run: pip install yt-dlp request
s"
            )
        
        # Configure
 yt-dlp
        ydl_opts = {
            'ski
p_download': True,
            'writesubtitle
s': True,
            'writeautomaticsub': Tr
ue,
            'subtitleslangs': ['zh', 'zh-
CN', 'zh-TW', 'en', 'ja', 'ko'],
            
'quiet': True,
            'no_warnings': Tru
e,
        }
        
        # Extract video
 info
        with yt_dlp.YoutubeDL(ydl_opts)
 as ydl:
            try:
                vid
eo_data = ydl.extract_info(url, download=Fals
e)
            except Exception as e:
       
         return VideoInfo(
                  
  platform='youtube',
                    tit
le='',
                    author='',
       
             duration=0,
                    
duration_formatted='',
                    su
btitles=[],
                    segments=[],

                    error=f"Failed to extract
 video info: {e}"
                )
         
   
            duration = int(video_data.get
('duration', 0))
            title = video_da
ta.get('title', 'Unknown')
            author
 = video_data.get('uploader', 'Unknown')
    
        
            # Extract subtitles by d
ownloading them
            subtitles = []
  
          
            # Try manual subtitles
 first
            subs_data = video_data.get
('subtitles', {})
            automatic_capti
ons = video_data.get('automatic_captions', {}
)
            
            # Find available s
ubtitle
            subtitle_url = None
     
       
            for lang in ['zh', 'zh-CN
', 'zh-TW', 'en', 'ja', 'ko']:
              
  if lang in subs_data and subs_data[lang]:
 
                   for sub in subs_data[lang]
:
                        if sub.get('url'):

                            subtitle_url = su
b['url']
                            break
  
              if subtitle_url:
              
      break
                
                
# Try automatic captions
                if l
ang in automatic_captions and automatic_capti
ons[lang]:
                    for sub in aut
omatic_captions[lang]:
                      
  if sub.get('url'):
                        
    subtitle_url = sub['url']
               
             break
                if subtitl
e_url:
                    break
            

            # Download and parse subtitle
  
          if subtitle_url:
                tr
y:
                    response = requests.ge
t(subtitle_url, timeout=10)
                 
   if response.status_code == 200:
          
              content = response.text
       
                 
                        # T
ry to parse as JSON
                        t
ry:
                            json_data = j
son.loads(content)
                          
  if 'events' in json_data:
                 
               for event in json_data['events
']:
                                    if 's
egs' in event:
                              
          start = event.get('tStartMs', 0) / 
1000.0
                                      
  end = start + (event.get('dDurationMs', 0) 
/ 1000.0)
                                   
     text = ''.join(seg.get('utf8', '') for s
eg in event['segs'])
                        
                if text.strip():
            
                                subtitles.app
end({
                                       
         'start': start,
                    
                            'end': end,
     
                                           't
ext': text.strip()
                          
                  })
                        
    elif 'body' in json_data:
               
                 for entry in json_data['body
']:
                                    subti
tles.append({
                               
         'start': float(entry.get('from', 0))
,
                                        'en
d': float(entry.get('to', 0)),
              
                          'text': entry.get('
content', '').strip()
                       
             })
                        excep
t json.JSONDecodeError:
                     
       pass
                        
        
        except Exception as e:
              
      print(f"Warning: Failed to download sub
title: {e}", file=sys.stderr)
        
      
  
            # Fallback: Try youtube-transcript-api if yt-dlp subtitles are empty
            if not subtitles and YOUTUBE_TRANSCRIPT_API_AVAILABLE:
                try:
                    # Extract video ID from URL
                    video_id = None
                    if 'youtu.be/' in url:
                        video_id = url.split('youtu.be/')[-1].split('?')[0]
                    elif 'v=' in url:
                        video_id = url.split('v=')[-1].split('&')[0]
                    
                    if video_id:
                        api = YouTubeTranscriptApi()
                        transcript = api.fetch(video_id, languages=['en', 'zh', 'zh-CN'])
                        
                        for snippet in transcript:
                            subtitles.append({
                                'start': snippet.start,
                                'duration': snippet.duration,
                                'text': snippet.text
                            })
                except Exception as e:
                    # youtube-transcript-api failed, continue with empty subtitles
                    pass

            # Calculate segments
        segments_data 
= calculate_segments(duration)
        segmen
ts = []
        
        for start, end in se
gments_data:
            segment_subs = [
   
             sub for sub in subtitles
       
         if start <= sub['start'] < end
     
       ]
            
            segment_tex
t = ' '.join([sub['text'] for sub in segment_
subs])
            
            segments.appe
nd({
                'start': start,
        
        'end': end,
                'start_fo
rmatted': format_duration(start),
           
     'end_formatted': format_duration(end),
 
               'text': segment_text,
        
        'subtitles_count': len(segment_subs)

            })
        
        return VideoI
nfo(
            platform='youtube',
        
    title=title,
            author=author,
 
           duration=duration,
            dur
ation_formatted=format_duration(duration),
  
          subtitles=subtitles,
            se
gments=segments
        )
        
    except
 Exception as e:
        import traceback
   
     return VideoInfo(
            platform='
youtube',
            title='',
            a
uthor='',
            duration=0,
           
 duration_formatted='',
            subtitles
=[],
            segments=[],
            err
or=f"Extraction error: {str(e)}\n{traceback.f
ormat_exc()}"
        )


def extract_bilibil
i_info(url: str) -> VideoInfo:
    """Extract
 information from Bilibili video with auto-au
th"""
    # Check if authenticated
    if not
 check_bilibili_auth():
        print("\n⚠�
��  首次使用 Bilibili 功能，需要配�
��认证")
        if not auto_setup_bilibili
_auth():
            return VideoInfo(
      
          platform='bilibili',
              
  title='',
                author='',
      
          duration=0,
                duratio
n_formatted='',
                subtitles=[],

                segments=[],
               
 error="Bilibili 认证配置失败或取消"

            )
        print("\n✅ 认证完
成，继续提取视频...")
    
    # Now 
extract with authentication
    try:
        
from bilibili_api import video, Credential
  
      from bilibili_api.exceptions import Cre
dentialNoSessdataException
        import asy
ncio
        import requests
    except Impor
tError as e:
        return VideoInfo(
      
      platform='bilibili',
            title=
'',
            author='',
            durati
on=0,
            duration_formatted='',
    
        subtitles=[],
            segments=[]
,
            error=f"Missing dependency: {e}
. Run: pip install bilibili-api-python reques
ts"
        )
    
    # Load credential
    
try:
        config_dir = get_config_dir()
  
      config_file = config_dir / "auth.json"

        with open(config_file, 'r', encoding=
'utf-8') as f:
            config = json.load
(f)
        
        sessdata = config.get('s
essdata', '')
        if not sessdata:
      
      return VideoInfo(
                platf
orm='bilibili',
                title='',
   
             author='',
                durat
ion=0,
                duration_formatted='',

                subtitles=[],
              
  segments=[],
                error="认证�
��息为空，请重新配置"
            )

        
        credential = Credential(sess
data=sessdata)
    except Exception as e:
   
     return VideoInfo(
            platform='
bilibili',
            title='',
            
author='',
            duration=0,
          
  duration_formatted='',
            subtitle
s=[],
            segments=[],
            er
ror=f"加载认证信息失败: {e}"
        
)
    
    # Extract BV number
    bv_match =
 re.search(r'[Bb][Vv]([a-zA-Z0-9]+)', url)
  
  if not bv_match:
        return VideoInfo(

            platform='bilibili',
            
title='',
            author='',
            
duration=0,
            duration_formatted=''
,
            subtitles=[],
            segme
nts=[],
            error="Could not extract 
BV number from URL"
        )
    
    bvid =
 f"BV{bv_match.group(1)}"
    
    # Create v
ideo object
    v = video.Video(bvid=bvid, cr
edential=credential)
    
    async def get_v
ideo_data():
        """Get all video data in
cluding info and subtitles"""
        info = 
await v.get_info()
        cid = info.get('ci
d')
        
        subtitles_data = []
    
    
        if cid:
            try:
       
         subtitle_list = await v.get_subtitle
(cid=cid)
                
                if
 subtitle_list and isinstance(subtitle_list, 
dict):
                    if 'subtitles' in 
subtitle_list and subtitle_list['subtitles']:

                        print(f"\n📝 找�
� {len(subtitle_list['subtitles'])} 个字幕
，正在下载...")
                        
for sub_info in subtitle_list['subtitles']:
 
                           subtitle_url = sub
_info.get('subtitle_url', '')
               
             if subtitle_url:
               
                 # Fix relative URL
         
                       if subtitle_url.starts
with('//'):
                                 
   subtitle_url = 'https:' + subtitle_url
   
                             
               
                 try:
                       
             print(f"   下载 {sub_info.get(
'lan_doc', 'unknown')} 字幕...")
          
                          resp = requests.get
(subtitle_url, timeout=10)
                  
                  if resp.status_code == 200:

                                        subt
itle_json = resp.json()
                     
                   body = subtitle_json.get('
body', [])
                                  
      print(f"   ✓ 获取 {len(body)} 条�
�幕")
                                      
  for entry in body:
                        
                    subtitles_data.append({
 
                                             
  'start': float(entry.get('from', 0)),
     
                                           'e
nd': float(entry.get('to', 0)),
             
                                   'text': en
try.get('content', '').strip()
              
                              })
            
                            break  # Use firs
t available subtitle
                        
        except Exception as e:
              
                      print(f"   ✗ 下载�
�败: {e}")
                                 
   continue
                    elif 'body' i
n subtitle_list:
                        for 
entry in subtitle_list['body']:
             
               subtitles_data.append({
      
                          'start': float(entr
y.get('from', 0)),
                          
      'end': float(entry.get('to', 0)),
     
                           'text': entry.get(
'content', '').strip()
                      
      })
            except Exception:
      
          pass
        
        return info, 
subtitles_data
    
    try:
        info, su
btitles = asyncio.run(get_video_data())
    e
xcept Exception as e:
        return VideoInf
o(
            platform='bilibili',
         
   title='',
            author='',
         
   duration=0,
            duration_formatted
='',
            subtitles=[],
            se
gments=[],
            error=f"Failed to fetc
h video data: {e}"
        )
    
    title =
 info.get('title', 'Unknown')
    author = in
fo.get('owner', {}).get('name', 'Unknown')
  
  duration = info.get('duration', 0)
    
   
 
            # Fallback: Try youtube-transcript-api if yt-dlp subtitles are empty
            if not subtitles and YOUTUBE_TRANSCRIPT_API_AVAILABLE:
                try:
                    # Extract video ID from URL
                    video_id = None
                    if 'youtu.be/' in url:
                        video_id = url.split('youtu.be/')[-1].split('?')[0]
                    elif 'v=' in url:
                        video_id = url.split('v=')[-1].split('&')[0]
                    
                    if video_id:
                        api = YouTubeTranscriptApi()
                        transcript = api.fetch(video_id, languages=['en', 'zh', 'zh-CN'])
                        
                        for snippet in transcript:
                            subtitles.append({
                                'start': snippet.start,
                                'duration': snippet.duration,
                                'text': snippet.text
                            })
                except Exception as e:
                    # youtube-transcript-api failed, continue with empty subtitles
                    pass

            # Calculate segments
    segments_data = cal
culate_segments(duration)
    segments = []
 
   
    for start, end in segments_data:
    
    segment_subs = [
            sub for sub 
in subtitles
            if start <= sub['sta
rt'] < end
        ]
        
        segment
_text = ' '.join([sub['text'] for sub in segm
ent_subs])
        
        segments.append({

            'start': start,
            'end
': end,
            'start_formatted': format
_duration(start),
            'end_formatted'
: format_duration(end),
            'text': s
egment_text,
            'subtitles_count': l
en(segment_subs)
        })
    
    return V
ideoInfo(
        platform='bilibili',
      
  title=title,
        author=author,
       
 duration=duration,
        duration_formatte
d=format_duration(duration),
        subtitle
s=subtitles,
        segments=segments
    )



def print_help():
    """Print detailed hel
p message"""
    help_text = """
Video Summar
y Tool - 视频字幕提取工具
===========
==========================

Usage: python ext
ract_video_info.py <video_url>

支持的平�
��:
  • YouTube - 无需认证，自动提�
��字幕
  • Bilibili - 首次使用需要 
SESSDATA 认证

示例:
  python extract_vid
eo_info.py "https://www.youtube.com/watch?v=x
xx"
  python extract_video_info.py "https://w
ww.bilibili.com/video/BVxxx"

Bilibili 认证
说明:
  1. 首次使用 Bilibili 功能时�
��脚本会提示输入 SESSDATA
  2. 获取�
��法：
     • 访问: https://nemo2011.gi
thub.io/bilibili-api/#/get-credential
     �
� 或手动: F12 → Application → Cookies 
→ bilibili.com → 复制 SESSDATA
  3. 粘
贴 SESSDATA 后，认证信息会保存在 c
onfig/auth.json
  4. 后续使用无需再次
输入

配置文件位置:
  config/auth.jso
n (已添加到 .gitignore，不会被提交)

"""
    print(help_text)


def main():
    "
""Main entry point"""
    if len(sys.argv) < 
2 or sys.argv[1] in ['-h', '--help']:
       
 print_help()
        sys.exit(0)
    
    ur
l = sys.argv[1]
    
    url = sys.argv[1]
  
  
    # Identify platform
    platform = ide
ntify_platform(url)
    
    if not platform:

        result = VideoInfo(
            plat
form='unknown',
            title='',
       
     author='',
            duration=0,
     
       duration_formatted='',
            sub
titles=[],
            segments=[],
         
   error="Unsupported platform. Supported: Yo
uTube, Bilibili"
        )
    elif platform 
== 'youtube':
        result = extract_youtub
e_info(url)
    elif platform == 'bilibili':

        result = extract_bilibili_info(url)
 
   else:
        result = VideoInfo(
        
    platform='unknown',
            title='',

            author='',
            duration=
0,
            duration_formatted='',
       
     subtitles=[],
            segments=[],
 
           error="Unknown platform"
        )

    
    # Output as JSON
    print(json.dum
ps(asdict(result), ensure_ascii=False, indent
=2))


if __name__ == '__main__':
    main()


