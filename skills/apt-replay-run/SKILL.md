---
name: apt-replay-run
description: Run packaged AutomatedPerfTest replay workflows through a Windows .bat setup with editable config. Supports device packaged runs such as PS5 and local PC packaged runs, with configurable replay, build, device, and profiling archive paths.
---

# APT Replay Run

## Pure BAT Workflow

1. Edit `references/apt.config.cmd` (all keys are `set "Key=Value"`).
2. Choose entry command:
   - `run_replay_ps5.bat`: packaged replay APT for PS5, always `-skipdeploy`, failure exits immediately (no retry/install fallback).
   - `run_replay_pc.bat`: packaged replay APT for local Win64 runs.
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

- PS5 APT:
  - Trigger phrases: `跑PS5 APT`, `PS5 APT`, `run ps5 apt`
  - Command: `references\\run_replay_ps5.bat`
- PC APT:
  - Trigger phrases: `跑PC APT`, `PC APT`, `跑Win64 APT`, `run pc apt`
  - Command: `references\\run_replay_pc.bat`
- Generic `跑APT` / `run apt`:
  - Default to `PS5` unless user explicitly asks for PC.

This skill already includes ready defaults:
- `references/apt.config.cmd`
- `references/run_replay.bat`
- `references/run_replay_ps5.bat`
- `references/run_replay_pc.bat`

If these paths and values are correct for your machine, user can directly say `跑APT`.

## Command

```bat
.agents\skills\apt-replay-run\references\run_replay.bat
```

```bat
.agents\skills\apt-replay-run\references\run_replay.bat "F:\path\to\custom.config.cmd"
```

.agents\skills\apt-replay-run\references\run_replay_ps5.bat
```

```bat
.agents\skills\apt-replay-run\references\run_replay_pc.bat
```

## Notes

- Keep all variable edits in `apt.config.cmd`; avoid editing `run_replay.bat` for daily runs.
- Save `apt.config.cmd` as ANSI/ASCII (or clean UTF-8) to avoid CMD parsing issues from mixed encoding/newlines.
- Use UNC paths as-is for replay/build/report locations.
- `PS5` and `PC` modes are strict by design: no install fallback, no retry without skipdeploy.
- `RunMode` is chosen by the wrapper bat. Do not set it in `apt.config.cmd` for daily runs.
- Profiling archive keys:
  - `PS5SourceProfiling`: PS5 source `profiling` folder to collect from after test run.
  - `PCSourceProfiling`: PC source `profiling` folder to collect from after test run.
  - `ArchiveRoot`: destination root; script creates `ArchiveRoot\\BuildName_yyyyMMdd_ReplayName\\profiling`.
- APT capture toggles live in `apt.config.cmd`: `DoInsightsTrace` defaults to `true`; `DoCSVProfiler`, `DoFPSChart`, `DoLLM`, `DoGPUPerf`, `DoGPUReshape`, and `DoVideoCapture` default to `false`.
- Platform and target names are fixed by mode: `PS5` uses `-platform=PS5 -target=ProjectPBZ`, and `PC` uses `-platform=Win64 -target=ProjectPBZ`.
- PS5 device selection uses `PS5Target` to build `-devices=PS5:<ip>`.
- `PS5BuildDir` should point to the PS5 packaged build root.
- `PCBuildDir` should point to the Win64 packaged build root.
