"""
init_unreal.py — Python 包自动加载器 (MemoryTest 项目)
======================================================
Unreal Engine 在编辑器启动时自动执行 Content/Python/init_unreal.py。

注意：在 UEFN 中 unreal.Paths.project_content_dir() 指向 Fortnite 引擎
的 Content 目录而非 Island 项目目录，因此使用 __file__ 推断实际路径。

流程：
  1. 将 Content/Python/ 加入 sys.path
  2. 扫描所有含 __init__.py 的子目录（Python 包）
  3. 对暴露了 register() 函数的包逐个调用
"""

import sys
import os
import importlib
import unreal

_PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))

if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

_loaded: list = []
_failed: list = []

try:
    _entries = os.listdir(_PYTHON_DIR)
except OSError:
    _entries = []

for _name in sorted(_entries):
    _pkg_path = os.path.join(_PYTHON_DIR, _name)
    if not os.path.isdir(_pkg_path):
        continue
    if not os.path.exists(os.path.join(_pkg_path, "__init__.py")):
        continue
    try:
        _mod = importlib.import_module(_name)
        if callable(getattr(_mod, "register", None)):
            _mod.register()
            _loaded.append(_name)
    except Exception as _e:
        _failed.append(_name)
        unreal.log_error(f"[LOADER] Failed to load '{_name}': {_e}")

if _loaded:
    unreal.log(f"[LOADER] {len(_loaded)} package(s) registered: {', '.join(_loaded)}")
if _failed:
    unreal.log_warning(f"[LOADER] {len(_failed)} package(s) failed: {', '.join(_failed)}")
if not _loaded and not _failed:
    unreal.log("[LOADER] No packages with register() found in Content/Python/.")
