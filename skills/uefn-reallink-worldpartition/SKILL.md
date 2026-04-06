---
name: uefn-reallink-worldpartition
description: >-
  审查 UEFN 项目的 World Partition Streaming Layout 和内存分析。自动触发日志生成、解析、弹出可视化 UI。
  当用户要求查看世界分区、审查 streaming cell、检查 actor 分布、分析内存占用时使用。
metadata:
  version: "1.0.0"
  layer: domain
  tags: "worldpartition streaming cell uefn audit layout memory"
  updated: "2026-04-06"
  depends: "uefn-reallink-bridge"
---

# UefnReallink World Partition

审查 UEFN 项目的 World Partition Streaming Layout + 内存分析。一条命令自动完成：触发日志生成 → 解析 → 弹出 tkinter 审查窗口。

## 前置条件

- UEFN 编辑器必须正在运行
- `uefn-reallink-bridge` 编辑器插件已安装且 HTTP 服务器已启动（端口 9877）

如果编辑器插件未安装，请先使用 `uefn-reallink-bridge` Skill 完成安装。

## 触发条件

当用户说以下任意表述时使用此 Skill：
- "查看世界分区"
- "审查 streaming layout"
- "检查 cell 分布"
- "World Partition 布局审查"
- "分析内存占用"
- "streaming cell 有多少 actor"

## 使用方式

读取本 SKILL.md 时你已知其绝对路径，将文件名替换为 `scripts/wp_streaming_viewer.py` 即为脚本路径。

直接执行，无需任何参数：

```powershell
python "<path-to-wp_streaming_viewer.py>"
```

脚本会自动：
1. 通过 UefnReallink 触发 `wp.Editor.DumpStreamingGenerationLog`
2. 等待日志生成完成
3. 定位并解析最新的 StreamingGeneration 日志
4. 弹出 tkinter 审查窗口

## UI 功能

### Layout 标签页
- Streaming Cell 列表（按 Actor 数量降序），显示 Cell 名称、Actor 数、是否空间加载
- 选中 Cell 的 Actor 列表，显示类名、HLOD 标记、Instance GUID
- 双击 Actor 在 UEFN 编辑器中自动选中并聚焦视口
- 搜索框按 Cell 名称或 Actor 名称筛选

### Memory 标签页
- **Grid Scan** — 全图网格内存热力图，每个格子计算该位置加载的所有资产去重后总内存
- **Capture** — 抓取当前摄像机位置的加载状态
- **Texture Streaming 估算** — 勾选 "Tex Streaming" 后，根据采样点到 Actor Bounds 的距离估算纹理实际加载的 Mip Level，修正内存统计
- **资源明细** — 按类型分类的柱状图 + 资源列表，支持排序、右键跳转到编辑器
- **依赖缓存** — 首次扫描较慢（需查询所有资产），之后缓存到本地 JSON 秒级完成

## 技术参考

关于 ctypes 调用 C++ 函数获取内存大小的完整技术文档，见 [references/ctypes-call-cpp-in-uefn.md](references/ctypes-call-cpp-in-uefn.md)。

## 注意事项

- 日志文件通常在 `%LOCALAPPDATA%\UnrealEditorFortnite\Saved\Logs\WorldPartition\` 目录下
- 大型地图的日志可能有数 MB，解析需要几秒
- 双击聚焦功能依赖 UefnReallink 连接，确保编辑器在线
- 首次 Scan All 需要查询约 25000 个资产（约 3 分钟），之后使用缓存
