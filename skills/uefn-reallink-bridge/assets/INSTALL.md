# 编辑器插件安装指南

## 安装步骤

将本 Skill 目录下 `assets/Python/` 中的所有内容复制到 UEFN 项目的 `Content/Python/` 目录：

```powershell
$src = "<本文件所在目录>\Python"
$dst = "<UEFN项目路径>\Content\Python"

Copy-Item "$src\init_unreal.py" "$dst\init_unreal.py" -Force

$pkg = "$dst\UefnReallink"
if (!(Test-Path $pkg)) { New-Item -ItemType Directory -Path $pkg -Force | Out-Null }
Copy-Item "$src\UefnReallink\__init__.py" "$pkg\__init__.py" -Force
Copy-Item "$src\UefnReallink\server.py" "$pkg\server.py" -Force
```

安装完成后的目录结构：

```
你的UEFN项目/
└── Content/
    └── Python/
        ├── init_unreal.py
        └── UefnReallink/
            ├── __init__.py
            └── server.py
```

## 启动

### 方式 A：重启编辑器

关闭并重新打开 UEFN 编辑器，`init_unreal.py` 会在启动时自动执行。

### 方式 B：免重启（编辑器已在运行）

如果不想重启编辑器，在 UEFN 编辑器底部的 **Python (REPL)** 输入框中粘贴并执行以下命令：

```python
import sys,os;p=next((d for d in sys.path if "Content\\Python" in d or "Content/Python" in d),None);exec(open(os.path.join(p,"init_unreal.py"),encoding="utf-8").read(),{"__file__":os.path.join(p,"init_unreal.py")}) if p else print("not found")
```

## 验证

无论哪种方式，Output Log 中应出现：

```
[LOADER] 1 package(s) registered: UefnReallink
[UefnReallink] Ready on http://127.0.0.1:9877
```

终端验证：

```powershell
curl http://127.0.0.1:9877/
```

应返回包含 `"status": "ok"` 的 JSON。
