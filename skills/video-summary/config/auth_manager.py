#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Bilibili Authentication Manager
Simple credential management for bilibili-api
Stores SESSDATA in plaintext config/auth.json
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict


class BilibiliAuthManager:
    """Manages Bilibili SESSDATA authentication"""
    
    def __init__(self):
        # Config file path
        config_dir = Path(__file__).parent
        self.config_file = config_dir / "auth.json"
        
    def has_config(self) -> bool:
        """Check if auth config exists"""
        return self.config_file.exists()
    
    def load_config(self) -> Optional[Dict]:
        """Load auth config from file"""
        if not self.has_config():
            return None
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    
    def save_config(self, sessdata: str) -> bool:
        """Save auth config to file"""
        config = {
            "sessdata": sessdata,
            "platform": "bilibili"
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}", file=sys.stderr)
            return False
    
    def get_credential(self):
        """Get bilibili_api Credential object"""
        from bilibili_api import Credential
        
        config = self.load_config()
        if not config:
            return None
        
        sessdata = config.get("sessdata", "")
        if not sessdata:
            return None
        
        return Credential(sessdata=sessdata)
    
    def interactive_setup(self) -> bool:
        """Interactive setup for Bilibili authentication"""
        print("\n" + "="*60)
        print("🔐 Bilibili 认证配置")
        print("="*60)
        print()
        print("此视频需要 Bilibili 登录才能获取字幕。")
        print()
        print("📋 获取 SESSDATA：")
        print()
        print("方法1: 访问 https://nemo2011.github.io/bilibili-api/#/get-credential")
        print("       按照文档说明获取 SESSDATA")
        print()
        print("方法2: 1. 打开浏览器，访问 bilibili.com 并登录账号")
        print("       2. 按 F12 打开开发者工具")
        print("       3. 切换到 Application → Cookies → bilibili.com")
        print("       4. 找到 SESSDATA 字段，复制其值")
        print()
        print("⚠️  注意：SESSDATA 是登录凭证，请勿分享给他人")
        print()
        print("-"*60)
        
        while True:
            sessdata = input("\n请输入 SESSDATA (直接回车取消): ").strip()
            
            if not sessdata:
                print("\n❌ 已取消配置")
                return False
            
            # 验证凭证
            print("\n🔄 正在验证凭证...")
            if self._validate(sessdata):
                if self.save_config(sessdata):
                    print("\n✅ 认证配置成功！")
                    return True
                else:
                    print("\n❌ 保存配置失败")
                    return False
            else:
                print("\n❌ 凭证无效")
                retry = input("是否重新输入? (y/n): ").strip().lower()
                if retry != 'y':
                    print("\n❌ 已取消配置")
                    return False
    
    def _validate(self, sessdata: str) -> bool:
        """Validate credential by testing with API"""
        try:
            from bilibili_api import Credential, video
            import asyncio
            
            credential = Credential(sessdata=sessdata)
            v = video.Video(bvid="BV1GJ411x7h7", credential=credential)
            
            async def test():
                try:
                    info = await v.get_info()
                    return True
                except Exception:
                    return False
            
            return asyncio.run(test())
        except Exception:
            return False
    
    def ensure_authenticated(self):
        """
        Ensure authentication is configured.
        Returns Credential object or None if cancelled.
        """
        credential = self.get_credential()
        
        if credential is None:
            # No config, interactive setup
            if self.interactive_setup():
                return self.get_credential()
            else:
                return None
        
        return credential
    
    def handle_auth_error(self) -> bool:
        """Handle authentication error (e.g., expired credential)"""
        print("\n⚠️  凭证已过期或无效，需要重新配置")
        return self.interactive_setup()


if __name__ == "__main__":
    # Test
    manager = BilibiliAuthManager()
    cred = manager.ensure_authenticated()
    if cred:
        print(f"\n认证成功！SESSDATA: {cred.sessdata[:20]}...")
    else:
        print("\n认证失败或未配置")
