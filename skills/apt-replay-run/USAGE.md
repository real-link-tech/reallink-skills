# APT Replay Run 简洁使用说明

## 1. 基本用法

### 录制 Replay

在 PC 或 PS5 包体控制台输入：

```text
Demorec 文件名
```

结束录制：

```text
Demostop
```

Replay 一般生成在包体的 `Saved\Demos` 下，也可以使用共享目录中已有的 `.replay` 文件。

### 选择运行平台

| 需求 | 配置文件 | 对 Codex 的说法 |
| --- | --- | --- |
| 本地 PC | `references\apt.pc.config.cmd` | `跑PC APT` |
| PS5 | `references\apt.ps5.config.cmd` | `跑APT` 或 `跑PS5 APT` |
| 远程 PC | `references\apt.remote-pc.config.cmd` | `跑远程PC APT` |

只说“跑APT”时默认运行 PS5。

运行前至少确认：

- `REPLAY_LIST`：一个 Replay、分号分隔的多个 Replay，或 `.txt/.list` 清单。
- PC：`PCBuildDir`、`PCExe`、`PCBuildName`。
- PS5：`PS5Target`、`PS5BuildDir`、`PS5SourceProfiling`。
- 远程 PC：远端机器上的 `PCBuildDir`、`PCExe`、`WorkRoot`。
- `ArchiveRoot`：报告归档目录。

### 手动运行

在 Skill 根目录执行：

```powershell
& .\references\run_replay_pc.bat
& .\references\run_replay_ps5.bat
& .\references\run_replay_remote.bat
```

### 临时追加启动参数

本地 PC 和 PS5 支持只对本次运行追加 `ExtraArgs`：

```powershell
cmd.exe /d /c '.\references\run_replay_pc.bat --extra-args "-test1 -Foo=1"'
cmd.exe /d /c '.\references\run_replay_ps5.bat --extra-args "-test1 -Foo=1"'
```

参数会追加到配置里的 `ExtraArgs`，不会覆盖或写回基础配置。本地 PC 会把它同时传给 warmup 和正式采集。

远程 PC 没有 `--extra-args` 入口。临时参数应写入一份临时远程配置，运行后删除临时文件。

### Replay 就绪与资源加载等待

本地 PC 直启流程默认开启 Replay 就绪等待：

```bat
set "WaitForReplayReady=true"
set "ReplayReadyCVar=gq.Ind.Loading"
set "ReplayReadyValue=0"
set "ReplayReadySettleSeconds=1.0"
set "ReplayReadyTimeoutSeconds=60.0"
set "ReplayReadyForceExitOnTimeout=true"
set "ReplayReadyWatchdog=true"
set "ReplayReadyWatchdogGraceSeconds=10.0"
set "ReplayReadyPrimeFrames=1"
```

它不是在 Replay 启动前等待全部资源，而是按以下顺序执行：

1. 启动 Replay 并推进配置数量的帧，使 Replay 世界和目标地图建立。
2. 只暂停 Replay 播放，保持世界 Tick，让地图、World Partition 和资源流送继续完成。
3. 等待项目加载条件 `gq.Ind.Loading=0` 持续满足 `1` 秒。
4. 条件稳定后恢复 Replay，并开始本次 profiling。

等待超时采用双层保护：包体内部超过 `60` 秒会按失败退出；独立 watchdog 不依赖游戏线程，在额外等待 `10` 秒后如果仍未看到 profiling 开始且进程没有退出，就强制结束启动进程及其子进程，并让本次 APT 返回错误码 `124`。这样即使游戏线程卡住、内部退出没有执行完成，运行脚本也不会一直等待。

`ReplayReadyWatchdog=false` 只关闭外部 watchdog，不会关闭包体内部的 Replay 就绪超时。PSO warmup 和正式采集进程都会使用同一套 Replay 就绪参数与 watchdog，相关的 `.log`、`.status` 文件会随报告一起保留。

该功能只接入本地 PC 直启流程，并要求包体包含匹配版本的 `AutomatedReplayPerfTest` 就绪等待控制逻辑。旧包体可能忽略这些参数并沿用旧的采集起点。

Replay 就绪等待与 PSO warmup 解决的问题不同：前者等待地图和资源加载稳定，后者处理 PSO 编译对性能数据的干扰。

## 2. 采集开关怎么选

配置位置：

```bat
set "DoInsightsTrace=false"
set "DoCSVProfiler=false"
set "DoFPSChart=true"
set "DoLLM=true"
set "DoGPUPerf=false"
set "DoGPUReshape=false"
set "DoVideoCapture=false"
```

| 开关 | 什么时候开启 | 注意事项 |
| --- | --- | --- |
| `DoInsightsTrace` | 分析卡顿、线程等待、任务调度、CPU/GPU 时间线时 | 生成 `.utrace`，数据量和采集开销较大；普通跑分关闭 |
| `DoCSVProfiler` | 需要逐帧 CSV、批量对比、趋势分析或 GPU stat 列时 | 会同时追加 `-csvGpuStats`；普通跑分按需开启 |
| `DoFPSChart` | 只需要平均 FPS、帧率区间、Hitch 和 HTML 汇总时 | 最适合快速看整体流畅度；当前本地 PC 默认开启 |
| `DoLLM` | 分析内存分类、峰值和随时间变化时 | 生成 LLM CSV；当前本地 PC 默认开启 |
| `DoGPUPerf` | 需要诊断 GPU pass 成本时 | 本地 PC 会锁动态分辨率并减少异步 GPU 工作，测试条件已改变，不能当普通游戏基准 |
| `DoGPUReshape` | 需要 GPU 指令、Ray Tracing 或深度 GPU 调试时 | 插桩会明显影响 GPU 时间；只用于诊断，不用于性能成绩 |
| `DoVideoCapture` | 需要把画面现象与性能时间点对应，或留存复现视频时 | 有额外录制开销；普通跑分关闭 |

推荐组合：

| 需求 | 建议开启 |
| --- | --- |
| 日常流畅度检查 | `DoFPSChart` |
| 内存专项 | `DoLLM`，需要逐帧趋势时再加 `DoCSVProfiler` |
| CPU/线程卡顿 | `DoInsightsTrace` |
| CSV 批量对比 | `DoCSVProfiler` |
| GPU pass 诊断 | `DoGPUPerf` |
| 深度 GPU 调试 | `DoGPUReshape`，不要用其结果作为基准成绩 |
| 画面复现 | `DoVideoCapture`，按需搭配其他采集 |

不要默认全部开启。采集器越多，数据量和运行干扰越大。Trace、CSV、GPUPerf、GPUReshape 和视频建议使用临时配置开启，基础配置保持关闭。

### StatsFile

当前 Skill 没有 `DoStatsFile` 开关，也不会自动校验 `.uestats`。

需要给 Unreal Profiler 记录 StatsFile 时，在 `ExecCmds` 中加入：

```bat
set "ExecCmds=stat startfile"
```

已有命令时用英文逗号追加：

```bat
set "ExecCmds=stat fps,stat startfile"
```

文件通常生成在：

```text
Saved\Profiling\UnrealStats\*.uestats
```

注意：

- `stat startfile` 是控制台命令，不能写成 `--extra-args`。
- 当前 runner 不检查 `.uestats` 是否生成，APT 可能成功但没有 StatsFile。
- 本地 PC 的 `ExecCmds` 会同时用于 warmup 和正式采集，所以 `stat startfile` 也会在 warmup 进程执行。
- StatsFile 更适合旧式 Unreal Profiler/stat 分析；需要跨线程时间线时优先使用 Insights Trace。

### 其他报告启动参数

```text
-VTPoolReport          需要虚拟纹理池报告时开启
-StreamingPoolReport   需要纹理流送池报告时开启
```

当前本地 PC 基础 `ExtraArgs` 已包含这两个参数，无需重复追加。

## 3. 画质设置

画质覆盖只接入本地 PC 直启流程。

### 使用当前默认画质

```bat
set "QualityCVars="
```

此时 Skill 不注入画质 CVar。实际画质仍由包体默认值、DeviceProfile、项目设置和 `%WorkRoot%\UserDir` 中保存的用户设置共同决定，因此不一定等于全新安装的首次启动画质。

### 单次设置总画质档位

PowerShell 中使用 `cmd.exe`，避免 `.bat` 丢失 `=值`：

```powershell
cmd.exe /d /c '.\references\run_replay_pc.bat --quality "r.GraphicsQuality=0"'
```

### 单次设置多个画质项

```powershell
cmd.exe /d /c '.\references\run_replay_pc.bat --quality "r.GraphicsQuality=3;gq.Ind.ResolutionQualityLevel=4"'
```

### 长期写入配置

```bat
set "QualityCVars=r.GraphicsQuality=0"
```

规则：

- 支持整数类型的 `r.GraphicsQuality`、`gq.*` 和 `gq.Ind.*`。
- 多个项目用英文分号分隔。
- CVar 会通过 `Reallink.ProfileMatrix.AddCustomizedCVar` 以最高优先级应用。
- warmup 与正式采集使用同一组画质。
- 日志未确认最高优先级赋值时，运行失败。
- 画质内容写入报告的 `quality_cvars.txt`。
- 画质不同会生成不同的 PSO warmup key。

`gq.Ind.UpscaleMode` 只是 ProfileMatrix 维度，不能替代项目完整的 TSR、DLSS 等切换流程。`r.ScreenPercentage` 不属于 `--quality` 支持范围。

当前 `run_replay_pc.bat` 不能在一次命令中同时解析 `--quality` 和 `--extra-args`。两者都需要时，创建包含最终 `QualityCVars` 和 `ExtraArgs` 的临时 PC 配置，然后把临时配置路径作为入口的第一个参数。

## 4. PSO Warmup

PSO warmup 只接入本地 PC 直启流程，默认配置：

```bat
set "PSOWarmupMode=Auto"
```

| 模式 | 适用场景 |
| --- | --- |
| `Auto` | 日常测试推荐。相同条件只 warmup 一次，后续直接正式采集 |
| `Always` | 修改了影响渲染的 `ExecCmds`、`ExtraArgs`，或希望明确重新预热时 |
| `Never` | 只做快速功能验证，或明确接受首次 PSO 卡顿风险时；不建议用于正式基准 |

### `Auto` 如何判断是否需要 warmup

warmup key 包含：

- 包体 exe 的路径、大小和修改时间
- Replay 的路径、大小和修改时间
- 启动地图
- GPU 与驱动信息
- `QualityCVars`

key 不包含 `ExecCmds` 和 `ExtraArgs`。如果它们会改变画质、材质、渲染路径或 PSO 集合，应使用一次 `Always`，否则 `Auto` 可能错误复用旧 warmup。

### 实际运行流程

第一次运行或 key 变化时，一次命令会自动跑两遍 Replay：

1. warmup：关闭 APT 正式采集器，关闭运行时 PSO Precache，让 bundled ShaderPipelineCache 以 Fast 模式完成已有任务。
2. 正式采集：继续关闭运行时 PSO Precache，并把 ShaderPipelineCache 批处理切换到 `Pause`，避免后台编译干扰数据。

只有 warmup 进程成功退出、日志确认 PSO 队列完成且相关 CVar 生效，才会开始正式采集。失败时不会生成 warmup 完成标记，也不会继续正式跑分。

warmup 缓存位置：

```text
%PSOWarmupCacheRoot%
```

PS5 和远程 PC 当前不使用这套两阶段 PSO warmup。

## 5. 输出位置

当前本地 PC 报告根目录由 `ArchiveRoot` 配置决定：

```text
%ArchiveRoot%
```

每个 Replay 的归档大致为：

```text
<PCBuildName>_yyyyMMdd-HHmmss_<ReplayName>
|-- profiling
|-- logs
|-- warmup_logs
`-- quality_cvars.txt
```

本地 PC 批量结果：

```text
%WorkRoot%\pc_direct_summary.txt
```

详细的平台配置说明：

- [本地 PC](docs/local-pc.md)
- [PS5](docs/ps5.md)
- [远程 PC](docs/remote-pc.md)
- [原始 APT 使用手册](APT%20使用手册.pdf)
