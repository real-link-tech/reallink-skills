# pixtool.exe Command Quick Reference

PIX version: `2509.25`  
Path: `%ProgramFiles%\Microsoft PIX\<version>\pixtool.exe`

Commands chain left-to-right on a single invocation. `open-capture` must precede
inspection commands. `launch` must precede `take-capture`.

---

## Global Options

| Option | Description | Default |
|--------|-------------|---------|
| `--help [<cmd>]` | Show help (optionally for a specific command) | — |
| `--output=<level>` | Console verbosity: `quiet`, `trace`, `engine`, `verbose` | `trace` |
| `--log=<level>` | Log file verbosity (adds `off`) | `verbose` |
| `--log-file=<path>` | Log file path | `%TEMP%\pixtool.log` |

---

## Capture Commands

### `launch <exe> [...]`
Launch a Win32 executable for GPU capture.

| Option | Description | Default |
|--------|-------------|---------|
| `--command-line=<cl>` | Arguments passed to the exe | — |
| `--working-directory=<dir>` | Working directory | Directory of exe |
| `--setenv=<NAME=VALUE>` | Set environment variables (repeatable) | — |
| `--remote=<machine>` | Remote capture machine | localhost |
| `--timing` | Launch for Timing Capture instead of GPU | — |
| `--force11on12` | Force D3D11on12 | — |
| `--captureFromStart` | Start capturing before app starts | — |

### `launch-app <package> <application> [...]`
Launch a UWP app. Same options as `launch`.

### `take-capture [--open] [...]`
Take a GPU capture of the currently launched app.

| Option | Description | Default |
|--------|-------------|---------|
| `--open` | Open capture on target after taking | — |
| `--frames=<n>` | Number of frames to capture | 1 |
| `--winml` | Use Windows ML Work as frame delimiter | — |

### `programmatic-capture [--open] [--until-exit]`
Wait for the app to trigger a programmatic capture (via `PIXBeginCapture`).

### `attach <pid>`
Attach to an already-running process by PID.

### `take-new-timing-capture <filename> [--duration=<n>]`
Take a Timing Capture of the current app.

---

## Capture File Commands

### `open-capture <filename> [...]`
Open an existing `.wpix` GPU capture file.

| Option | Description |
|--------|-------------|
| `--remote=<machine>` | Remote analysis machine (default: localhost) |
| `--use-replay-time-executeindirect-buffers` | Use replay-time EI argument buffers |
| `--disable-gpu-plugins` | Do not load GPU vendor plugins |
| `--enable-recreate-at-gpuva` | Recreate heaps at capture-time GPU virtual addresses |
| `--enable-application-specific-driver-state` | Apply app-specific driver workarounds |
| `--force-set-application-specific-driver-state` | Force driver workarounds regardless of device/driver mismatch |

### `save-capture <filename>`
Save the currently open capture to a file.

### `save-all-captures <directory>`
Save all recently taken captures to a directory.

---

## Analysis Commands

### `save-screenshot <filename>`
Save the embedded screenshot (recorded at capture time) as PNG.

### `save-resource <filename> [...]`
Save a render target or depth buffer to an image file.

| Option | Description | Default |
|--------|-------------|---------|
| `--rtv=<index>` | Which RenderTargetView index to save | 0 |
| `--depth` | Save depth buffer (visual representation, PNG only) | — |
| `--global-id=<id>` | Save resource at this Global ID event | last event |
| `--marker=<name>` | Save resource from last child of named PIX marker | — |

### `save-event-list <filename> [...]`
Save the event list as CSV.

| Option | Description |
|--------|-------------|
| `--counters=<pattern>` | Include counters matching pattern (`*` = wildcard). Repeatable. |
| `--counter-groups=<pattern>` | Include all counters in matching groups. Repeatable. |
| `--queue-name=<name>` | Specify which command queue to use |

Always-included columns: Queue ID, Name, Global ID.

**Common counter group patterns:**

| Pattern | Counters |
|---------|----------|
| `D3D:*` | D3D12 built-in counters (duration, draw calls, primitives) |
| `GPU:*` | Hardware counters (occupancy, cache, bandwidth) |
| `*` | All available counters |

### `list-counters`
Print all available GPU counters for the current capture.

### `save-high-frequency-counters <filename> [...]`
Collect per-clock counter data in CSV format.

| Option | Description |
|--------|-------------|
| `--counters=<pattern>` | Counters to collect (repeatable, `*` = all) |
| `--merge` | Merge timestamps to single column, coalesce data |

### `run-debug-layer`
Replay the capture with the D3D12 debug layer enabled. Outputs API errors to the log.

### `collect-occupancy`
Collect GPU shader occupancy data for the capture.

---

## Region / Recapture Commands

### `recapture-region <outputFile> [...]`
Recapture a sub-range of the currently open capture.

| Option | Description |
|--------|-------------|
| `--start=<GlobalID>` | First event to include (inclusive) |
| `--end=<GlobalID>` | Last event to include (inclusive) |

### `recapture-single-playback [...]`
Capture one playback of the currently open file.

### `perform-single-playback [...]`
Perform one playback without capture.

| Option | Description |
|--------|-------------|
| `--do-not-expand-executeindirect` | Keep EI argument buffers unexpanded |
| `--loop` | Loop playback indefinitely |
| `--loop-count=<n>` | Loop N times (requires `--loop`) |
| `--time-cpu` | Measure CPU command list recording time |
| `--measure-cycles` | Report CPU time in cycles (requires `--time-cpu`) |

---

## Export Command

### `export-to-cpp <directory> [--force] [--use-winpixeventruntime] [...]`
Export the captured frame as a standalone D3D12 C++ Visual Studio project.

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing files |
| `--use-winpixeventruntime` | Include WinPixEventRuntime (accept license) |
| `--use-agilitySdk` | Include D3D12 Agility SDK (accept license) |
| `--use-replay-time-executeindirect-buffers` | Use replay-time EI argument buffers |

---

## Recapture Commands

### `begin-recapture` / `end-recapture`
Bracket a recapture of pixtool itself (for debugging pixtool).

---

## Example Chains

```powershell
# Launch, capture, open in GUI, save screenshot
pixtool launch app.exe take-capture --open save-capture frame.wpix

# Open capture, get all D3D counters in CSV
pixtool open-capture frame.wpix save-event-list events.csv --counter-groups="D3D:*"

# Open on remote machine, save all counters
pixtool open-capture --remote=192.168.1.1 frame.wpix save-event-list events.csv --counters="*"

# Save shadow map depth buffer
pixtool open-capture frame.wpix save-resource shadow.png --marker="ShadowPass" --depth

# Recapture frames 100-200, then export to C++
pixtool open-capture frame.wpix ^
  recapture-region slim.wpix --start=100 --end=200 ^
  open-capture slim.wpix ^
  export-to-cpp C:\repro --force --use-winpixeventruntime --use-agilitySdk

# Debug layer validation
pixtool open-capture frame.wpix run-debug-layer
```
