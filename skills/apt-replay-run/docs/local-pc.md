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
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles"

set "Configuration=Test"
set "MaxDuration=1800"
set "PCBuildDir=D:\PBZ_PC\Win64_189198-9493\189198-9493"
set "ExecCmds="
set "QualityCVars="
set "ExtraArgs="
set "PSOWarmupMode=Auto"

set "ArchiveRoot=\\192.168.0.7\store\APT\Report"
set "PCSourceProfiling=%ProjectPath%\Saved\Profiling"
```

## 字段是什么意思

- `EnginePath`: 本机 UnrealEngine 路径。
- `ProjectPath`: 本机 ProjectPBZ 工程路径。
- `REPLAY_LIST`: replay 输入。默认共享目录会递归查找所有子目录中的 `.replay` 并按完整路径排序；也可以指定一个 `.replay`、分号分隔的多个文件或 `.txt/.list` 清单。
- `PCBuildDir`: 本地 Win64 包体目录。
- `ExecCmds`: 游戏启动后执行的 UE 控制台命令。
- `QualityCVars`: 可选的整数画质覆盖，留空时使用当前默认画质。
- `ExtraArgs`: 额外传给游戏 exe 的命令行参数。
- `PSOWarmupMode`: PSO 预热策略。`Auto` 只在包体、Replay、地图或显卡驱动变化后预热一次；`Always` 每次预热；`Never` 跳过预热。
- `ArchiveRoot`: 跑完后报告、trace 归档到哪里。
- `PCSourceProfiling`: 本地 PC profiling 源目录，通常默认 `%ProjectPath%\Saved\Profiling`。

## 启动参数怎么加

控制台命令写 `ExecCmds`：

```bat
set "ExecCmds=r.DynamicRes.OperationMode 0,stat fps"
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

只给本次运行追加游戏命令行参数：

```bat
references\run_replay_pc.bat --extra-args "-VTPoolReport"
references\run_replay_pc.bat --extra-args "-test1 -test2"
```

`--extra-args` 会追加到配置里的 `ExtraArgs`，不会覆盖或写回配置。

临时指定一次画质参数：

```bat
references\run_replay_pc.bat --quality "r.GraphicsQuality=3;gq.Ind.ResolutionQualityLevel=4"
```

多个画质项使用英文分号分隔。脚本会将其固定为 ProfileMatrix 最高优先级，同时应用到 PSO 预热和正式采集；不传 `--quality` 时不注入任何画质覆盖。

## PSO 预热与正式采集

默认 `PSOWarmupMode=Auto`。第一次运行时，脚本会自动完整播放一次 Replay 做 PSO 预热，不开启 FPSChart、CSV、LLM 等采集；确认 PSO 队列完成后，再自动播放第二次并正式采集。后续相同包体、Replay、地图和显卡驱动会直接进入正式采集。

正式采集期间会关闭运行时 PSO Precache，并暂停 bundled ShaderPipelineCache 的后台预编译。整个流程仍然只需要执行一次 `run_replay_pc.bat`。

## Replay 资源等待与 Watchdog

本地 PC 默认使用以下超时保护：

```bat
set "WaitForReplayReady=true"
set "ReplayReadyTimeoutSeconds=60.0"
set "ReplayReadyForceExitOnTimeout=true"
set "ReplayReadyWatchdog=true"
set "ReplayReadyWatchdogGraceSeconds=10.0"
set "ReplayProgressWatchdog=true"
set "ReplayProgressTimeoutSeconds=120.0"
set "ReplayExitWatchdog=true"
set "ReplayExitTimeoutSeconds=90.0"
set "ReplayWatchdogCpuSampleSeconds=3.0"
```

Replay 建立目标世界后会暂停回放，保持世界 Tick，等地图、World Partition、资源流送以及 `gq.Ind.Loading=0` 稳定后才开始采集。

包体内部等待超过 `60` 秒会先按失败退出。独立生命周期 watchdog 会读取运行日志并分阶段计时：

- Replay 就绪超时再宽限 `10` 秒，仍未开始 profiling 时结束进程树，返回 `124`。
- profiling 开始后，只有新的 Replay Chunk 或 Teardown 才算有效进展；连续 `120` 秒无进展时采样 CPU/响应状态、归档诊断并结束进程树，返回 `127`。
- Teardown 或请求退出后切换到退出阶段，给 PSO 保存、上传和正常退出 `90` 秒；只有退出阶段超时才返回 `128`。

warmup 和正式采集都会启用该保护。报告会保留 `ReplayWatchdog.log`、`.status`、`.json` 和 `.tail.log`。Replay 阶段被 watchdog 终止时不会继续执行 PSO 校验，也不会创建 warmup stamp。

`ReplayReadyWatchdog`、`ReplayProgressWatchdog` 和 `ReplayExitWatchdog` 可以分别关闭。`ReplayReadyWatchdog=false` 只关闭外部就绪保护，不会关闭包体内部的 Replay 就绪超时。仅在需要交互调试时临时关闭。

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
