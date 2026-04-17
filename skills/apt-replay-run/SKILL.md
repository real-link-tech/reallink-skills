---
name: apt-replay-run
description: Run AutomatedPerfTest replay workflows through a pure Windows .bat setup with editable config file and no PowerShell dependency. Use when users ask to run UE RunUAT replay perf tests, inject paths/device/map/replay/build settings, parameterize repeated APT jobs, automate "write config then call bat" flows, or give short commands like "跑APT", "开跑APT", "run apt".
---

# APT Replay Run

## Pure BAT Workflow

1. Edit `references/apt.config.cmd` (all keys are `set "Key=Value"`).
2. Choose mode with `RunMode`:
   - `Packaged`: RunUAT replay test, always `-skipdeploy`, failure exits immediately (no retry/install fallback).
   - `Editor`: run replay APT in editor via `UnrealEditor-Cmd.exe`.
3. Run `references/run_replay.bat`.
4. `run_replay.bat` auto-loads `apt.config.cmd` by default.
5. Optional: pass custom config path as first arg:
   - `run_replay.bat "F:\path\to\another.config.cmd"`

## One-phrase Run

When user says short commands like `跑APT`:

1. Rewrite `references/apt.config.cmd` with latest values.
2. Execute `references/run_replay.bat`.

## Intent Routing

Use these phrase-to-mode rules so the agent can pick the correct run type:

- Packaged APT (`RunMode=Packaged`):
  - Trigger phrases: `跑包APT`, `包APT`, `跑PS5 APT`, `run packaged apt`
  - Command: `references\\run_replay_packaged.bat`
- Editor APT (`RunMode=Editor`):
  - Trigger phrases: `跑编辑器APT`, `编辑器APT`, `跑Editor APT`, `run editor apt`
  - Command: `references\\run_replay_editor.bat`
- Generic `跑APT` / `run apt`:
  - Default to `Packaged` unless user explicitly asks for editor.

This skill already includes ready defaults:
- `references/apt.config.cmd`
- `references/run_replay.bat`
- `references/run_replay_packaged.bat`
- `references/run_replay_editor.bat`

If these paths and values are correct for your machine, user can directly say `跑APT`.

## Command

```bat
.agents\skills\apt-replay-run\references\run_replay.bat
```

```bat
.agents\skills\apt-replay-run\references\run_replay.bat "F:\path\to\custom.config.cmd"
```

```bat
.agents\skills\apt-replay-run\references\run_replay_packaged.bat
```

```bat
.agents\skills\apt-replay-run\references\run_replay_editor.bat
```

## Notes

- Keep all variable edits in `apt.config.cmd`; avoid editing `run_replay.bat` for daily runs.
- Save `apt.config.cmd` as ANSI/ASCII (or clean UTF-8) to avoid CMD parsing issues from mixed encoding/newlines.
- Use UNC paths as-is for replay/build/report locations.
- `Packaged` mode is strict by design: no install fallback, no retry without skipdeploy.
- Profiling archive keys:
  - `SourceProfiling`: source `profiling` folder to collect from after test run.
  - `ArchiveRoot`: destination root; script creates `ArchiveRoot\\yyyy-M-d-HHmm\\profiling`.
- APT capture toggles live in `apt.config.cmd`: `DoInsightsTrace` defaults to `true`; `DoCSVProfiler`, `DoFPSChart`, `DoLLM`, `DoGPUPerf`, `DoGPUReshape`, and `DoVideoCapture` default to `false`.
- Packaged platform keys live in `apt.config.cmd`: `Platform` defaults to `PS5`, `TargetName` defaults to `ProjectPBZ`, and `DeviceId` defaults to the PS5 device id. For Win64 packaged runs, update these together with `BuildDir` as needed.
