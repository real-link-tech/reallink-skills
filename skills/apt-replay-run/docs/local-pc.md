# 本地 PC APT 怎么配和怎么跑

## 改哪个配置

改这个文件：

```bat
references\apt.pc.config.cmd
```

这个配置只给本地 PC 跑法用。远程 PC 跑法不会读取它，远程 PC 请改：

```bat
references\apt.remote-pc.config.cmd
```

## 最少要确认这些

```bat
set "EnginePath=D:\UnrealEngine"
set "ProjectPath=E:\PBZ\ProjectPBZ"
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles\zxrzhulin.replay"

set "Configuration=Test"
set "MaxDuration=1800"
set "PCBuildDir=D:\PBZ_PC\Win64_189198-9493\189198-9493"
set "ExecCmds="
set "ExtraArgs="

set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "PCSourceProfiling=%ProjectPath%\Saved\Profiling"
```

## 字段是什么意思

- `EnginePath`: 本机 UnrealEngine 路径。
- `ProjectPath`: 本机 ProjectPBZ 工程路径。
- `REPLAY_LIST`: replay 路径。可以是一个 `.replay`，也可以用分号写多个。
- `PCBuildDir`: 本地 Win64 包体目录。
- `ExecCmds`: 游戏启动后执行的 UE 控制台命令。
- `ExtraArgs`: 额外传给游戏 exe 的命令行参数。
- `ArchiveRoot`: 跑完后报告、trace 归档到哪里。
- `PCSourceProfiling`: 本地 PC profiling 源目录，通常默认 `%ProjectPath%\Saved\Profiling`。

## 启动参数怎么加

控制台命令写 `ExecCmds`：

```bat
set "ExecCmds=r.DynamicRes.OperationMode 0;stat fps;"
```

命令行参数写 `ExtraArgs`：

```bat
set "ExtraArgs=-ResX=1920 -ResY=1080 -ForceRes -NoVSync"
```

## 怎么让 Codex 跑

直接说：

```text
跑PC APT
```

或者：

```text
跑本地PC APT
```

## 手动命令

```bat
references\run_replay_pc.bat
```

## 常见问题

### 跑成了 PS5

说清楚 PC：

```text
跑PC APT
```

不要只说 `跑APT`，因为默认会按 PS5。

### 找不到 PC 包

检查：

```bat
set "PCBuildDir=..."
```

这个目录要指向 Win64 packaged build 的根目录。

### 找不到 replay

检查：

```bat
set "REPLAY_LIST=..."
```

如果有多个 replay，用英文分号 `;` 分开。

### 没有 profiling 或报告

检查：

```bat
set "PCSourceProfiling=%ProjectPath%\Saved\Profiling"
set "ArchiveRoot=..."
```

确认游戏实际有产出 profiling，并且 `ArchiveRoot` 可以写入。
