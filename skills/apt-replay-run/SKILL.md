---
name: apt-replay-run
description: Run packaged AutomatedPerfTest replay workflows through a Windows .bat setup with editable config. Supports device packaged runs such as PS5 and local PC packaged runs, with configurable replay, build, device, and profiling archive paths.
---

# APT Replay Run

## Pure BAT Workflow

1. Edit `references/apt.config.cmd` (all keys are `set "Key=Value"`).
2. Choose entry command:
   - `run_replay_ps5.bat`: default PS5 entry; runs `run_replay_batch.bat`, one replay per list entry, always strict `-skipdeploy`.
   - `run_replay_pc.bat`: default local Win64 entry; runs `run_replay_batch.bat`, one replay per list entry.
   - `run_replay.bat`: lower-level single replay runner, used by batch mode for each entry.
3. Run `references/run_replay_ps5.bat` or `references/run_replay_pc.bat`.
4. The wrappers auto-load `apt.config.cmd` by default.
5. Optional: pass custom config path as first arg:
   - `run_replay_ps5.bat "F:\path\to\another.config.cmd"`

## One-phrase Run

When user says short commands like `跑APT`:

1. Rewrite `references/apt.config.cmd` with latest values.
2. Execute `references/run_replay_ps5.bat` by default, or `references/run_replay_pc.bat` if PC/Win64 is requested.
3. Treat replay input as a list by default: set `REPLAY_LIST` in `apt.config.cmd`. Do not use `REPLAY_PATH` or numbered replay variables.

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
- Multi replay APT:
  - Trigger phrases: `一次性跑多个replay`, `批量跑replay APT`, `batch replay apt`
  - Command: same as normal mode, usually `references\\run_replay_ps5.bat`
  - No special user phrasing is required; PS5/PC wrappers are batch-first.

This skill already includes ready defaults:
- `references/apt.config.cmd`
- `references/run_replay.bat`
- `references/run_replay_ps5.bat`
- `references/run_replay_pc.bat`
- `references/run_replay_batch.bat`

If these paths and values are correct for your machine, user can directly say `跑APT`.

## Command

```bat
.agents\skills\apt-replay-run\references\run_replay_ps5.bat
```

```bat
.agents\skills\apt-replay-run\references\run_replay_ps5.bat "F:\path\to\custom.config.cmd"
```

```bat
.agents\skills\apt-replay-run\references\run_replay_pc.bat
```

```bat
.agents\skills\apt-replay-run\references\run_replay_batch.bat "F:\path\to\apt.config.cmd" "F:\path\to\replay_list.txt"
```

## Replay List

`run_replay_ps5.bat` and `run_replay_pc.bat` are batch-first. They call `run_replay_batch.bat`.

Configure replay paths in `apt.config.cmd` with semicolon-separated entries:

```bat
set "REPLAY_LIST=\\192.168.0.7\store\APT\ReplayFiles\xigu.replay;\\192.168.0.7\store\APT\ReplayFiles\demo_02.replay;\\192.168.0.7\store\APT\ReplayFiles\demo_03.replay"
```

For readable multiline `.cmd` config, append one replay per line:

```bat
set "REPLAY_LIST="
set "REPLAY_LIST=%REPLAY_LIST%;\\192.168.0.7\store\APT\ReplayFiles\xigu.replay"
set "REPLAY_LIST=%REPLAY_LIST%;\\192.168.0.7\store\APT\ReplayFiles\demo_02.replay"
set "REPLAY_LIST=%REPLAY_LIST%;\\192.168.0.7\store\APT\ReplayFiles\demo_03.replay"
```

Avoid caret continuation inside quoted `set "REPLAY_LIST=..."` blocks; CMD can treat later `.replay` lines as commands.

Optional external file mode: set `REPLAY_LIST` to a `.txt`/`.list` file path or pass arg2. The file is one replay path per line; blank lines and lines beginning with `#` are ignored.

## Notes

- Keep all variable edits in `apt.config.cmd`; avoid editing `run_replay.bat` for daily runs.
- Save `apt.config.cmd` as ANSI/ASCII (or clean UTF-8) to avoid CMD parsing issues from mixed encoding/newlines.
- Use UNC paths as-is for replay/build/report locations.
- `PS5` and `PC` modes are strict by design: no install fallback, no retry without skipdeploy.
- `RunMode` is chosen by the wrapper bat. Do not set it in `apt.config.cmd` for daily runs.
- Profiling archive keys:
  - `PS5SourceProfiling`: PS5 source `profiling` folder to collect from after test run.
  - `PCSourceProfiling`: PC source `profiling` folder to collect from after test run.
  - `ArchiveRoot`: destination root; script creates `ArchiveRoot\\BuildName_yyyyMMdd-HHmm_ReplayName\\profiling`.
- Gauntlet is expected to leave only the current run's profiling files in the source profiling folder; the runner copies that folder into the timestamped archive directory.
- APT capture toggles live in `apt.config.cmd`: `DoInsightsTrace` defaults to `true`; `DoCSVProfiler`, `DoFPSChart`, `DoLLM`, `DoGPUPerf`, `DoGPUReshape`, and `DoVideoCapture` default to `false`.
- Platform and target names are fixed by mode: `PS5` uses `-platform=PS5 -target=ProjectPBZ`, and `PC` uses `-platform=Win64 -target=ProjectPBZ`.
- PS5 device selection uses `PS5Target` to build `-devices=PS5:<ip>`.
- `PS5BuildDir` should point to the PS5 packaged build root.
- `PCBuildDir` should point to the Win64 packaged build root.
- `REPLAY_LIST` is the only replay input for daily runs. It can be a semicolon-separated inline list, appended across multiple `set` lines, or a path to a `.txt`/`.list` file.
- Batch mode creates temp config files under `%TEMP%\\apt_replay_batch_*`; it does not edit `apt.config.cmd`.
