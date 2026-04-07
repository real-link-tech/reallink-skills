# RealLink Skills 安装指南（AI 自动执行）

本文档供 AI 助手读取并自动执行安装。安装内容包括：

1. **uefn-reallink-bridge** — 编辑器 HTTP 桥接插件（复制到 UEFN 项目的 `Content/Python/`）
2. **uefn-reallink-worldpartition** — World Partition 审查工具（无需复制，原地运行）

---

## 第 0 步：定位路径

本文档的绝对路径已知，据此推算：

- `INSTALL_DIR` = 本文件所在目录（即 `assets/`）
- `BRIDGE_PYTHON_SRC` = `INSTALL_DIR/Python` — 编辑器插件源文件
- `SKILL_ROOT` = `INSTALL_DIR` 的上两级（即 `skills/` 目录）
- `WP_SCRIPTS` = `SKILL_ROOT/uefn-reallink-worldpartition/scripts` — WP 审查脚本

## 第 1 步：询问用户 UEFN 项目路径

向用户询问 UEFN 项目的根目录路径。通常形如：

```
C:\Users\<用户名>\Documents\Fortnite Projects\<项目名>
```

将其记为 `UEFN_PROJECT`。目标目录为 `UEFN_PROJECT\Content\Python`。

如果用户已在对话中提供过项目路径，直接使用，无需重复询问。

## 第 2 步：安装编辑器插件（Junction 方式）

使用 Junction / SymbolicLink 将源文件链接到 UEFN 项目，这样 skill 仓库更新后无需重新安装。

执行以下 PowerShell 命令（替换变量为实际路径）：

```powershell
$src = "<BRIDGE_PYTHON_SRC>"
$dst = "<UEFN_PROJECT>\Content\Python"

# 确保目标目录存在
if (!(Test-Path $dst)) { New-Item -ItemType Directory -Path $dst -Force | Out-Null }

# init_unreal.py — 文件符号链接
New-Item -ItemType SymbolicLink -Path "$dst\init_unreal.py" -Target "$src\init_unreal.py" -Force

# UefnReallink 包 — 目录 Junction（无需管理员权限）
$pkg = "$dst\UefnReallink"
if (Test-Path $pkg) {
    # 如果已存在（可能是旧的复制），先删除
    cmd /c rmdir "$pkg" 2>$null   # Junction 用 rmdir 移除
    if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
}
New-Item -ItemType Junction -Path $pkg -Target "$src\UefnReallink"
```

安装后的目录结构：

```
<UEFN_PROJECT>/
└── Content/
    └── Python/
        ├── init_unreal.py        → 符号链接 → <BRIDGE_PYTHON_SRC>/init_unreal.py
        └── UefnReallink/         → Junction  → <BRIDGE_PYTHON_SRC>/UefnReallink/
            ├── __init__.py
            └── server.py
```

## 第 3 步：验证编辑器连接

如果 UEFN 编辑器正在运行，执行：

```powershell
curl -s http://127.0.0.1:9877/
```

- **返回 `"status": "ok"`** → 插件已在线，跳到第 4 步
- **连接失败** → 告知用户需要重启 UEFN 编辑器，或在编辑器 Python REPL 中执行以下命令手动启动（将 `<UEFN_PROJECT>` 替换为实际路径，使用正斜杠）：

```python
p=r"<UEFN_PROJECT>/Content/Python";import sys,os;sys.path.insert(0,p) if p not in sys.path else None;exec(open(os.path.join(p,"init_unreal.py"),encoding="utf-8").read(),{"__file__":os.path.join(p,"init_unreal.py")})
```

编辑器 Output Log 应出现：

```
[LOADER] 1 package(s) registered: UefnReallink
[UefnReallink] Ready on http://127.0.0.1:9877
```

## 第 4 步：World Partition 审查工具

`uefn-reallink-worldpartition` 无需安装到 UEFN 项目，脚本从 skill 仓库原地运行。

告知用户：当需要审查 World Partition 时，执行：

```powershell
python "<WP_SCRIPTS>\wp_streaming_viewer.py"
```

脚本会自动通过 bridge 触发日志生成、解析并弹出审查窗口。

## 安装完成

向用户确认：

- ✅ 编辑器插件已通过 Junction 链接到 UEFN 项目
- ✅ World Partition 审查工具就绪（原地运行，无需安装）
- 💡 skill 仓库文件更新后自动生效，无需重新安装
