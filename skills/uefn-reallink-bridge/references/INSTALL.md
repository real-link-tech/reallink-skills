# Reallink UEFN Bridge 安装指南（AI 自动执行）

本文档供 AI 助手读取并自动执行安装。

安装内容：**uefn-reallink-bridge** — 编辑器 HTTP 桥接插件 + Reallink UEFN Editor GUI。

> World Partition 审查功能已合并到本插件的 GUI 中（StreamingLayout / MemoryTest Tab），不再需要单独安装。

---

## 第 0 步：定位路径

本文档位于 `skills/uefn-reallink-bridge/references/INSTALL.md`，据此推算：

- `SKILL_DIR` = 本文件的上一级目录（即 `skills/uefn-reallink-bridge/`）
- `BRIDGE_PYTHON_SRC` = `SKILL_DIR/assets/Python` — 编辑器插件源文件

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
        ├── init_unreal.py            → 符号链接 → <BRIDGE_PYTHON_SRC>/init_unreal.py
        └── UefnReallink/             → Junction  → <BRIDGE_PYTHON_SRC>/UefnReallink/
            ├── __init__.py            # 包入口，注册 HTTP 服务 + 注入工具栏按钮
            ├── server.py              # HTTP 桥接服务
            ├── reallink_uefn_editor.py  # GUI 入口
            ├── core/
            │   ├── bridge.py          # HTTP 通信 + 编辑器命令 + 内存采集
            │   ├── common.py          # 数据结构（Cell, ActorDesc 等）
            │   ├── parser.py          # StreamingGeneration 日志解析
            │   ├── theme.py           # 暗色主题
            │   └── snapshot.py        # 快照导入导出
            ├── tabs/
            │   ├── common_tab.py      # 控制台指令
            │   ├── streaming_layout_tab.py  # World Partition 可视化
            │   └── memory_test_tab.py       # Grid Scan / 内存分析
            └── widgets/
                ├── cell_map_canvas.py       # Cell 地图画布
                └── connection_status.py     # 连接状态栏
```

## 第 3 步：验证编辑器连接

如果 UEFN 编辑器正在运行，执行：

```powershell
curl -s http://127.0.0.1:9877/
```

- **返回 `"status": "ok"`** → 插件已在线，跳到第 4 步
- **连接失败** → 告知用户需要重启 UEFN 编辑器，或在编辑器 Python 输入框中执行以下命令手动启动（将 `<UEFN_PROJECT>` 替换为实际路径，使用正斜杠）：

```python
p=r"<UEFN_PROJECT>/Content/Python";import sys,os;sys.path.insert(0,p) if p not in sys.path else None;exec(open(os.path.join(p,"init_unreal.py"),encoding="utf-8").read(),{"__file__":os.path.join(p,"init_unreal.py")})
```

编辑器 Output Log 应出现：

```
[LOADER] 1 package(s) registered: UefnReallink
[UefnReallink] Ready on http://127.0.0.1:9877
[UefnReallink] Toolbar button 'Reallink' injected
```

## 第 4 步：启动 Reallink UEFN Editor GUI

插件就绪后，有两种方式打开 Reallink 编辑器 GUI：

### 方式 A：工具栏按钮（推荐）

插件加载成功后，UEFN 视口工具栏会自动出现 `Reallink` 按钮，点击即可启动。

### 方式 B：Python 输入框手动启动

在 UEFN 编辑器底部的 Python 输入框中粘贴以下命令并回车：

```python
import sys, os, subprocess; subprocess.Popen([os.path.join(os.path.normpath(os.path.join(os.path.dirname(sys.executable), sys.prefix)), 'python.exe'), '-m', 'UefnReallink.reallink_uefn_editor'], cwd=os.path.dirname(os.path.dirname(__import__('UefnReallink').__file__)), creationflags=0x08000000)
```

编辑器 GUI 会以独立进程启动，不阻塞 UEFN 主线程，也不会弹出控制台窗口。

### GUI 功能

- **Common** — 控制台指令输入，直接在 UEFN 编辑器中执行
- **StreamingLayout** — World Partition Streaming Cell 可视化、搜索、Actor 聚焦、Refresh 触发日志生成
- **MemoryTest** — Grid Scan 全图内存热力图、Capture 当前相机位置内存分析、资源依赖树、Texture Streaming 估算

## 安装完成

向用户确认：

- ✅ 编辑器插件已通过 Junction 链接到 UEFN 项目
- ✅ Reallink UEFN Editor GUI 可通过工具栏按钮或 Python 命令启动
- ✅ World Partition 审查 + 内存分析已集成在 GUI 中
- 💡 skill 仓库文件更新后自动生效，无需重新安装
