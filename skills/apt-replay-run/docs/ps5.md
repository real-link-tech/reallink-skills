# PS5 APT 怎么配和怎么跑

## 改哪个配置

改这个文件：

```bat
references\apt.ps5.config.cmd
```

## 最少要确认这些

```bat
set "EnginePath=D:\UnrealEngine"
set "ProjectPath=E:\PBZ\ProjectPBZ"
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles\xuzhang.replay"

set "PS5Target=192.168.103.108"
set "Configuration=Test"
set "MaxDuration=1800"
set "PS5BuildDir=\\192.168.103.61\builds_ps\PS5\Test\xxx"
set "ExecCmds="
set "ExtraArgs="

set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "PS5SourceProfiling=P:\%PS5Target%\devlog\app\projectpbz\projectpbz\saved\profiling"
```

## 字段是什么意思

- `EnginePath`: 本机 UnrealEngine 路径。
- `ProjectPath`: 本机 ProjectPBZ 工程路径。
- `REPLAY_LIST`: replay 路径。可以是一个 `.replay`，也可以用分号写多个。
- `PS5Target`: PS5 devkit IP。
- `PS5BuildDir`: PS5 包体目录。
- `ExecCmds`: 游戏启动后执行的 UE 控制台命令。
- `ExtraArgs`: 额外传给游戏 exe 的命令行参数。
- `ArchiveRoot`: 跑完后报告、trace 归档到哪里。
- `PS5SourceProfiling`: PS5 profiling 源目录，一般跟 `PS5Target` 走默认写法就行。

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
跑PS5 APT
```

或者：

```text
跑APT
```

默认没特别说明 PC 的时候，skill 会按 PS5 跑。

## 手动命令

```bat
references\run_replay_ps5.bat
```

## 常见问题

### 找不到 Engine 或 Project

检查：

```bat
set "EnginePath=..."
set "ProjectPath=..."
```

这两个路径必须是本机真实存在的路径。

### 找不到 PS5 包

检查：

```bat
set "PS5BuildDir=..."
```

这个目录要能从本机访问。

### replay 没跑起来

检查：

```bat
set "REPLAY_LIST=..."
```

路径要能访问，文件名不要写错。多个 replay 用英文分号 `;` 分开。

### 没有归档结果

检查：

```bat
set "ArchiveRoot=..."
set "PS5SourceProfiling=..."
```

`ArchiveRoot` 要能写入，`PS5SourceProfiling` 要能读到 PS5 产出的 profiling。
