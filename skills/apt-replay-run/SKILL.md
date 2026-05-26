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
set "ExecCmds=r.DynamicRes.OperationMode 0;stat fps;"
set "ExtraArgs=-ResX=1920 -ResY=1080 -ForceRes -NoVSync"
```

- `ExecCmds`: UE console commands executed after game startup.
- `ExtraArgs`: extra command-line args passed to the game.

For PS5/local PC, `ExtraArgs` is passed through RunUAT's `-Args="..."`. For remote PC, it is appended directly to the packaged exe command line.

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

Local PC direct config fields in `apt.pc.config.cmd` include `PCExe`, `PCBuildName`, `WorkRoot`, `MapPath`, `WindowMode`, and `PCSourceProfiling`. `Configuration`, `MaxDuration`, and `Iterations` are legacy RunUAT/Gauntlet fields and are not used by direct mode.

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
