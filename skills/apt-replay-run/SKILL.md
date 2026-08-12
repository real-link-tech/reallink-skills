---
name: apt-replay-run
description: Run packaged AutomatedPerfTest replay workflows through a small Windows .bat setup with separate PS5, local PC, and remote PC configs.
---

# APT Replay Run

## Files

Configs:

- `references/apt.ps5.config.cmd`
- `references/apt.pc.config.cmd`
- `references/apt.remote-pc.config.cmd`

Entry scripts:

- `references/run_replay_ps5.bat`
- `references/run_replay_pc.bat`
- `references/run_replay_pc_direct.bat`
- `references/run_replay_pc_gauntlet.bat`
- `references/run_replay_remote.bat`
- `references/run_replay_batch.bat`

`run_replay_pc.bat` is the normal local PC entry. It launches the packaged exe directly through `run_replay_pc_direct.bat`, matching the remote target-mode flow and avoiding RunUAT/Gauntlet's temporary device wrapper.

`run_replay_pc_gauntlet.bat` is the preserved old local PC RunUAT/Gauntlet entry. Do not use it for normal local PC runs unless explicitly comparing against the old behavior.

`run_replay_batch.bat` is the shared PS5/legacy local PC batch helper. It reads `REPLAY_LIST`, runs each replay once, and performs the PS5 or legacy local-PC RunUAT work itself.

`run_replay_remote.bat` has two modes in one file:

- Controller mode: run from this machine, copy itself plus `apt.remote-pc.config.cmd` to `RemotePC`, then trigger a scheduled task.
- Target mode: `run_replay_remote.bat --target <config>`, used on the remote PC by the scheduled task to launch the packaged exe.

## One-Phrase Run

- `跑APT`: run PS5 APT by default.
- `跑PS5 APT`: run `references/run_replay_ps5.bat`.
- `跑PC APT` or `跑本地PC APT`: run `references/run_replay_pc.bat`, which uses direct packaged-exe local PC mode.
- `跑本地PC Gauntlet APT` or `跑旧本地PC APT`: run `references/run_replay_pc_gauntlet.bat`.
- `跑远程PC APT` or `跑远程PC`: run `references/run_replay_remote.bat`.

## Config Rules

Do not mix the three configs:

- PS5 edits go in `apt.ps5.config.cmd`.
- Local PC edits go in `apt.pc.config.cmd`.
- Remote PC edits go in `apt.remote-pc.config.cmd`.

Remote PC does not read `apt.pc.config.cmd`. Duplicate needed PC package fields in `apt.remote-pc.config.cmd`. In remote config, `PCBuildDir` and `PCExe` are paths on the remote target PC, not paths on the controller machine.

### Insights Trace Policy

- Keep `DoInsightsTrace=false` in every base config and runner fallback.
- Treat ordinary requests such as `run APT`, `run PC APT`, or `run replay` as Trace disabled.
- Enable Trace only when the current user request explicitly names Trace, Insights Trace, or `.utrace`, for example `run APT with Trace`.
- Do not infer Trace from a generic request to collect performance data or enable other capture options.
- For an explicit Trace run, copy the matching base config to a temporary CRLF `.cmd`, set `DoInsightsTrace=true` in that temporary config, pass it as the entry script's first argument, and remove it after the run. Do not leave a base config with Trace enabled.

### CSV Profiler Policy

- Keep `DoCSVProfiler=false` in every base config and runner fallback. Ordinary APT runs do not collect CSV data.
- Enable CSVProfiler only when the current user request explicitly names CSVProfiler or asks for CSV capture, for example `跑APT，开CSVProfiler`.
- Do not infer CSVProfiler from a generic request to run APT, collect performance data, or enable GPUPerf.
- For an explicit CSVProfiler run, copy the matching base config to a temporary CRLF `.cmd`, set `DoCSVProfiler=true` in that temporary config, pass it as the entry script's first argument, and remove it after the run. Do not leave a base config with CSVProfiler enabled.
- When CSVProfiler is enabled, pass both `-AutomatedPerfTest.DoCSVProfiler` and `-csvGpuStats`. The latter enables GPU stat columns in the CSV output.
- When `DoCSVProfiler=false`, omit both arguments. `DoGPUPerf` is independent and must not add `-csvGpuStats` back.

### GPU Perf Policy

- Keep `DoGPUPerf=false` in every base config and runner fallback. Ordinary APT runs should preserve normal dynamic-resolution and async-compute behavior.
- Enable GPUPerf only when the current user request explicitly names GPUPerf or asks for GPU pass breakdown under GPUPerf conditions, for example `跑APT，开GPUPerf`.
- Do not infer GPUPerf from a generic request to collect GPU data. CSVProfiler with `-csvGpuStats` already collects GPU CSV stats independently.
- For an explicit GPUPerf run, copy the matching base config to a temporary CRLF `.cmd`, set `DoGPUPerf=true` in that temporary config, pass it as the entry script's first argument, and remove it after the run. Do not leave a base config with GPUPerf enabled.
- GPUPerf changes the measurement conditions by locking dynamic resolution and reducing async GPU work. Treat it as a diagnostic pass-timing mode rather than the default gameplay-performance mode.

### Video Capture Policy

- Keep `DoVideoCapture=false` in every base config and runner fallback.
- Treat ordinary APT runs as video capture disabled.
- Enable video capture only when the current user request explicitly asks for recording or video capture.

### One-Run Extra Args

- Treat phrases such as `运行后缀`, `启动后缀`, or `额外启动参数` as extra command-line arguments for the game process, not as an archive-name suffix.
- For local PC and PS5, pass explicitly requested one-run arguments through `--extra-args "<args>"` on the public entry script. Examples: `run_replay_pc.bat --extra-args "-VTPoolReport"` and `run_replay_ps5.bat --extra-args "-test1 -test2"`.
- Append one-run arguments to the configured `ExtraArgs`; do not replace the configured value and do not write the one-run value back to a base config.
- Pass multiple switches as one quoted, space-separated string. Preserve the user's spelling and values instead of creating dedicated config fields for arbitrary switches.
- For remote PC, copy `apt.remote-pc.config.cmd` to a temporary CRLF `.cmd`, append the requested arguments to `ExtraArgs` in that temporary config, pass it as the controller entry's config argument, and remove it after the run.

### Replay Readiness Policy

- Local PC runs enable `WaitForReplayReady` in `apt.pc.config.cmd`.
- This requires a package built with the matching `AutomatedReplayPerfTest` ready-wait controller support. Older packages ignore the added command-line arguments and retain the old profiling start behavior.
- The controller primes the configured number of replay frames, pauses only replay playback, and keeps the world ticking while map and World Partition streaming finish.
- `ReplayReadyCVar` is the project-specific final gate. For ProjectPBZ use `gq.Ind.Loading` with `ReplayReadyValue=0`.
- Start profiling only after all ready conditions remain satisfied for `ReplayReadySettleSeconds`. Treat `ReplayReadyTimeoutSeconds` expiry as a failed run rather than collecting invalid loading data.
- Keep `ReplayReadyForceExitOnTimeout=true` for unattended local PC runs. The controller then force-exits with code `1` as soon as the ready wait times out, so a blocked graceful shutdown cannot leave the package running indefinitely. Set it to `false` only when an engineer explicitly prefers the original graceful-exit path so profiling tools can attempt normal finalization.
- Keep the independent `ReplayReadyWatchdog=true` for both the PSO warmup and measured local PC passes. It arms from the `Replay ready task installed.` log marker, disarms only after `Replay is ready. Profiling started`, and does not depend on the game thread continuing to tick.
- The watchdog deadline is `ReplayReadyTimeoutSeconds + ReplayReadyWatchdogGraceSeconds`. If the launcher process is still running at that point, kill its Windows process tree and report exit code `124`. Preserve the watchdog `.log` and `.status` files with the normal APT logs.
- Set `ReplayReadyWatchdog=false` only for an explicitly interactive debugging run. This disables the external fallback but does not disable the controller's own ready timeout.
- Keep project-specific CVar names in the Skill config; do not hard-code them into the engine controller.

### Local PC PSO Policy

- Keep `PSOWarmupMode=Auto` in `apt.pc.config.cmd`. One user invocation may run an unmeasured warmup replay followed by the measured replay.
- `Auto` warms once for each package/replay/map/GPU-driver/quality-override identity, `Always` warms every time, and `Never` skips warmup while retaining the capture-time PSO controls.
- The warmup pass does not override runtime `r.PSOPrecaching`, runs bundled ShaderPipelineCache work in Fast mode, and disables APT performance collectors.
- Create the warmup stamp only after the game exits successfully and the log confirms that the bundled PSO queue completed. A failed or incomplete warmup must stop the measured pass.
- The measured pass reuses the same `userdir`, pins runtime PSO precaching off, and calls `r.ShaderPipelineCache.SetBatchMode Pause` before profiling. Do not use `r.ShaderPipelineCache.Enabled=0`.
- Validate the measured log and fail the run if bundled PSO precompile resumes or advances during the profiling window.
- This is a two-process Skill-level approximation. It warms driver/user caches and prevents background bundled compilation during measurement, but it cannot eliminate a genuinely missing first-draw PSO. Exact same-process queue gating requires controller support.
- The measured pass requires a packaged build containing `Reallink.ProfileMatrix.AddCustomizedCVar`. Do not silently fall back to a one-shot `r.PSOPrecaching 0`, because later profile refreshes can restore it.

## Replay List

Use `REPLAY_LIST` for daily runs. It accepts:

```bat
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles\xuzhang.replay"
```

Multiple replay files can be separated by semicolons:

```bat
set "REPLAY_LIST=\\server\a.replay;\\server\b.replay"
```

Or set `REPLAY_LIST` to a `.txt` or `.list` file with one replay path per line.

## Launch Args

`ExecCmds` and `ExtraArgs` are different:

```bat
set "ExecCmds=r.DynamicRes.OperationMode 0,stat fps"
set "ExtraArgs=-ResX=1920 -ResY=1080 -ForceRes -NoVSync"
```

- `ExecCmds`: UE console commands executed after game startup.
- `ExtraArgs`: extra command-line args passed to the game.

For PS5/local PC, `ExtraArgs` is passed through RunUAT's `-Args="..."`. For remote PC, it is appended directly to the packaged exe command line.

### Local PC Quality Overrides

Leave `QualityCVars` empty and run `run_replay_pc.bat` without arguments to use the current default quality. For a one-run override:

```bat
run_replay_pc.bat --quality "r.GraphicsQuality=3;gq.Ind.ResolutionQualityLevel=4"
```

- Accept integer `gq.*`, `gq.Ind.*`, and `r.GraphicsQuality` values separated by semicolons.
- Convert each value to a max-priority `Reallink.ProfileMatrix.AddCustomizedCVar` command, and apply the same values to warmup and measured passes.
- Include normalized quality overrides in the PSO warmup key and write the requested values to `quality_cvars.txt` in the report directory.
- Treat `gq.Ind.UpscaleMode` as a ProfileMatrix dimension only; it is not a complete replacement for the project's upscaler settings flow.

## Remote PC Notes

Remote PC uses `run_replay_remote.bat` only. There is no separate `remote.bat`.

Remote PC required game/package fields live in `apt.remote-pc.config.cmd`; missing package or launch fields should fail fast. Remote trigger fields such as `RemoteDeployDir`, `RemoteTaskName`, and credential cache paths may use launcher defaults.

`apt.remote-pc.config.cmd` should be a full template, not a minimal snippet. Keep it aligned with `apt.pc.config.cmd` where the concepts overlap:

- `PCBuildDir`, `REPLAY_LIST`, `ExecCmds`, `ExtraArgs`
- `DoInsightsTrace`, `DoCSVProfiler`, `DoFPSChart`, `DoLLM`, `DoGPUPerf`, `DoGPUReshape`, `DoVideoCapture`
- `ArchiveRoot`

Remote-only fields include `RemotePC`, `RemoteUser`, `RemoteDeployDir`, `RemoteTaskName`, `PCExe`, `PCBuildName`, `WorkRoot`, `MapPath`, and `WindowMode`.

Remote PC launches the packaged exe directly, so it does not use local-PC RunUAT fields such as `Configuration`, `MaxDuration`, or `Iterations`.

The remote game is started through an interactive scheduled task so D3D/DXGI can create a real window in the logged-on desktop session. Do not launch the packaged game directly inside `Invoke-Command`; that can fail with `DXGI_ERROR_NOT_CURRENTLY_AVAILABLE`.

## Local PC Direct Notes

Local PC direct mode uses `run_replay_pc_direct.bat` via `run_replay_pc.bat`. It launches `PCExe` directly and archives `%WorkRoot%\UserDir\Saved\Profiling` plus logs, similar to remote target mode.

Local PC direct config fields in `apt.pc.config.cmd` include `PCExe`, `PCBuildName`, `WorkRoot`, `MapPath`, `WindowMode`, `PCSourceProfiling`, `QualityCVars`, and the `PSOWarmup*`/`PSOCaptureExecCmds` settings. `Configuration`, `MaxDuration`, and `Iterations` are legacy RunUAT/Gauntlet fields and are not used by direct mode.

Local PC direct mode starts from `/Game/Maps/B02/PBZ_Xigu_WP` by default. Keep this value in `MapPath` so another startup map can be selected through config without editing the runner.

Keep `run_replay_pc_gauntlet.bat` only as a fallback for reproducing old RunUAT/Gauntlet behavior.

## Docs

Short user-facing guides live under `docs/`:

- `docs/ps5.md`
- `docs/local-pc.md`
- `docs/remote-pc.md`

## Notes

- Keep `.cmd` files in CRLF line endings. LF-only config files can be parsed incorrectly by `cmd.exe call`.
- Use UNC paths as-is for replay/build/report locations.
- `RunMode` is explicit in `apt.ps5.config.cmd` and `apt.pc.config.cmd`, so direct `run_replay_batch.bat <config>` calls behave correctly too.
- Avoid editing runner `.bat` files for daily runs; edit the matching config instead.
