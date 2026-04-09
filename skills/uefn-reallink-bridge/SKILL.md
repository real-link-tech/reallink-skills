---
name: uefn-reallink-bridge
description: >-
  通过 HTTP 桥接在运行中的 UEFN 编辑器主线程执行任意 Python 代码。当用户要求操作 UEFN 编辑器中的 Actor、资产、关卡或任何编辑器功能时使用。
metadata:
  version: "1.0.0"
  layer: transport
  tags: "http python uefn fortnite editor bridge"
  updated: "2026-04-06"
---

# UefnReallink Bridge

通过 HTTP 桥接与运行中的 UEFN 编辑器通信。编辑器启动时自动在 `127.0.0.1:19877` 监听。你发送 Python 代码，编辑器在主线程执行并返回结果。

## 前置条件检查

每次会话首次使用时，先检测编辑器插件是否可用：

```powershell
curl -s http://127.0.0.1:19877/ 2>$null
```

- **连接成功** → 直接使用
- **连接失败** → 读取 [assets/INSTALL.md](assets/INSTALL.md) 引导用户安装编辑器插件

## 调用方式

读取本 SKILL.md 时你已知其绝对路径，将文件名替换为 `scripts/reallink_bridge.py` 即为客户端脚本路径。**不要搜索或 glob 查找。**

使用 PowerShell **here-string**（`@'...'@`）将 Python 代码管道传入：

```powershell
@'
import unreal
actors = unreal.EditorLevelLibrary.get_all_level_actors()
result = [a.get_name() for a in actors]
'@ | python "<path-to-reallink_bridge.py>"
```

**重要**：`@'` 必须独占一行，`'@` 也必须在行首。**绝对不要**用 `echo '...'` 或 `echo "..."` 传递代码。

## 协议

```
POST http://127.0.0.1:19877/execute
Content-Type: text/plain

<Python 代码>
```

赋值给 `result` 的值作为返回值。

### 响应

```json
{"success": true, "result": <序列化后的 result>, "stdout": "", "stderr": ""}
```

### 健康检查

```
GET http://127.0.0.1:19877/
```

## 核心规则

1. **所有逻辑用 Python 代码表达。** 不存在预定义命令。
2. **赋值给 `result` 返回值。** exec 环境中预定义了 `result = None`。
3. **预注入全局变量：** `unreal`、`actor_sub`（EditorActorSubsystem）、`asset_sub`（EditorAssetSubsystem）、`level_sub`（LevelEditorSubsystem）。
4. **批量操作一次发送。** 写成完整 Python 脚本一次提交，不要拆成多次调用。
5. **仔细阅读错误响应。** `stderr` 中包含完整 traceback。
6. **返回值自动序列化。** `unreal.Vector` → `{"x","y","z"}`，`UObject` → `path_name` 字符串。

## UEFN Python API 速查

### Actor 操作

```python
actors = unreal.EditorLevelLibrary.get_all_level_actors()
selected = unreal.EditorLevelLibrary.get_selected_level_actors()
actor = actor_sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
actor_sub.destroy_actor(actor)
loc = actor.get_actor_location()
actor.set_actor_location(unreal.Vector(100, 200, 0), False, False)
actor.set_actor_rotation(unreal.Rotator(0, 90, 0), False)
actor.get_name()
actor.get_actor_label()
actor.get_class().get_name()
value = actor.get_editor_property("property_name")
actor.set_editor_property("property_name", value)
```

### 资产操作

```python
assets = unreal.EditorAssetLibrary.list_assets("/Game/", recursive=True)
asset = unreal.EditorAssetLibrary.load_asset("/Game/Path/To/Asset")
unreal.EditorAssetLibrary.save_asset("/Game/Path/To/Asset")
reg = unreal.AssetRegistryHelpers.get_asset_registry()
```

### 视口操作

```python
loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
unreal.EditorLevelLibrary.set_level_viewport_camera_info(
    unreal.Vector(0, 0, 1000), unreal.Rotator(-90, 0, 0))
```

## Reallink UEFN Editor（独立 GUI 工具）

`assets/Python/UefnReallink/` 下包含一个独立的 Tkinter GUI 工具，提供三个 Tab：

- **Common** — 控制台指令输入 + 历史记录
- **StreamingLayout** — World Partition Streaming Cell 可视化 + 搜索
- **MemoryTest** — 内存分析：Grid Scan / Capture / 资源依赖树

### 启动方式

```powershell
# 在线模式（自动连接编辑器）
python -m UefnReallink.reallink_uefn_editor

# 离线模式（从快照加载）
python -m UefnReallink.reallink_uefn_editor --load snapshot.json

# 保存快照
python -m UefnReallink.reallink_uefn_editor --save snapshot.json
```

工作目录需为 `assets/Python/` 或将其加入 `PYTHONPATH`。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `UEFN_HOST` | `127.0.0.1` | 编辑器 HTTP 地址 |
| `UEFN_PORT` | `9877` | 编辑器 HTTP 端口 |
| `UEFN_TIMEOUT` | `30` | 超时秒数 |
