---
name: pix-gpu-debug
description: >
  GPU frame debugging and performance analysis with Microsoft PIX via pixtool.exe CLI.
  Use this skill when the user mentions: PIX, .wpix files, GPU capture, D3D12 debugging,
  DirectX performance, GPU counters, draw call timing, GPU occupancy, PIX marker regions,
  render target inspection, depth buffer, GPU performance profiling, frame analysis,
  CPU/GPU timing, ExecuteIndirect, shader debugging, GPU memory, DirectX 12 validation,
  "slow draw call", "GPU bottleneck", "why is this slow", "what's in this render target",
  "capture a frame with PIX", "analyze GPU performance", "D3D12 profiling", "PIX capture",
  UWP capture, programmatic capture, WinPixEventRuntime, high frequency counters.
  DO NOT use for: Vulkan debugging (use RenderDoc), OpenGL, CSS rendering, web performance.
---

# PIX GPU Debugging Skill

## Overview

This skill uses `pixtool.exe`, the Microsoft PIX command-line interface for D3D12 GPU
frame capture and analysis. PIX captures `.wpix` files and supports GPU counters,
resource inspection, event lists, and C++ export.

---

## ⚠️ CRITICAL: Always Run pixtool Serially

**Never launch multiple pixtool instances in parallel.**

Each `pixtool open-capture` invocation:
1. Loads the entire `.wpix` file into memory (captures are commonly 1–6 GB)
2. Replays **every GPU event from GID 0 up to the target GID** to reconstruct state

Running 2–4 instances simultaneously will exhaust RAM and CPU, causing the machine
to appear completely frozen for many minutes. The agent itself will also time out
waiting for background tasks.

**Rules to follow strictly:**
- Always wait for the previous pixtool command to finish before starting the next
- Check `exit_code` in the terminal file before proceeding
- Never use `block_until_ms: 0` (background) for pixtool unless you are deliberately
  monitoring it and will not launch another instance until it completes
- Prefer **low GIDs** (early in the capture) when possible — replay time scales
  linearly with GID. A GID near the end of a 50,000-event capture can take 5–10 minutes.

**Fastest GID strategy:**
```
Low GID  → fast (seconds)     e.g. BasePass ~40000 out of 53000 total
High GID → slow (5-10 min)    e.g. PostProcessing last draw ~53000 out of 53000 total
```

If you need a resource near the end of the capture, consider using
`recapture-region` first to create a trimmed capture, then extract from that.

---

## ⚠️ CRITICAL: Unreal Engine Render Pipeline — Finding the Final Scene Image

In Unreal Engine, **the last DrawCall is NOT the final output image**. Understanding
the UE pipeline is essential to target the correct render target.

### UE5 Frame Structure in PIX

A typical UE5 frame captured in PIX contains two D3D12 frames (Frame N and Frame N+1):

```
Frame N  (QID ~235, low queue IDs)
  └─ RenderGraphExecute - Slate
       └─ SlateUI "Title = ..."
            └─ DrawIndexedInstanced   ← composites Scene RT → backbuffer
  └─ Present  ← presents Frame N-1's already-rendered scene
               (the scene rendered in Frame N's SceneRender won't show until Frame N+1's Present)

Frame N+1  (QID ~75000+, high queue IDs)
  └─ SceneRender - ViewFamilies
       └─ RenderGraphExecute - /ViewFamilies
            └─ Scene
                 ├─ BasePass          ← GBuffer (albedo, normal, roughness, etc.)
                 ├─ ShadowDepths      ← virtual shadow maps
                 ├─ LumenSceneUpdate  ← Lumen GI card captures
                 ├─ DiffuseIndirectAndAO  ← Lumen final gather
                 ├─ RenderDeferredLighting
                 ├─ PostProcessing    ← Bloom, TAA, Tonemapper, FXAA
                 │    └─ [Tonemapper subpass]  ← writes SceneColorLDR (FINAL SCENE IMAGE)
                 └─ [Slate reads SceneColorLDR as texture → composites to backbuffer in Frame N+1]
```

### Which render target is the "final scene image"?

| What you want | Where to look | Notes |
|---|---|---|
| **Final scene (tonemapped, SDR)** | Last draw **inside `PostProcessing`** (Frame N+1) | This is SceneColorLDR — the image users see |
| GBuffer albedo | Last draw inside `BasePass` (Frame N+1) | RTV 0 = albedo |
| GBuffer normal | Last draw inside `BasePass` (Frame N+1) | RTV 1 = normal |
| Shadow atlas | Last draw inside `ShadowDepths` (Frame N+1) | Use `--depth` flag |
| Lumen GI | Last draw inside `DiffuseIndirectAndAO` (Frame N+1) | |
| Backbuffer at Present | Last Draw before `Present` in Frame N | This shows Frame N-1's scene (one frame old) |

### Querying event CSVs — use the bundled script, not ad-hoc Python files

**Never create one-off `.py` files to parse event CSVs.** Use the bundled tool instead:

```powershell
# All-in-one query script — handles every common question about a capture
$q = "C:\Users\L\.cursor\skills\pix-gpu-debug\scripts\ue_capture_query.py"

# Which frame has the 3D SceneRender vs which has Slate+Present?
python $q events.csv frames

# List all named render passes with their last Draw GID
python $q events.csv passes

# Find last Draw GID for every pass in the SceneRender frame at once
python $q events.csv last-draw-all

# Find last Draw GID for a specific pass by its Queue ID
python $q events.csv last-draw 146938

# List named children of any Queue ID
python $q events.csv children 75786

# Trace parent chain of any Global ID (understand what pass a draw belongs to)
python $q events.csv trace 27792

# Find all Present events
python $q events.csv present

# Show events with GIDs surrounding a target GID
python $q events.csv gids-around 27792 20
```

---

### Prerequisites

```powershell
# Locate pixtool - it lives in a versioned subdirectory
$pix = (Get-ChildItem "$env:ProgramFiles\Microsoft PIX" | Sort-Object Name -Desc | Select-Object -First 1).FullName + "\pixtool.exe"
& $pix --help   # verify it runs
```

Set `$pix` once at the start of every session and reuse it throughout. The default
install path is `%ProgramFiles%\Microsoft PIX\<version>\pixtool.exe`.

## 1. Command Chaining

pixtool chains all commands on one line — open, operate, and close happen in sequence:

```powershell
& $pix open-capture capture.wpix save-event-list events.csv
& $pix open-capture capture.wpix save-resource rt0.png
& $pix launch app.exe take-capture --open save-capture output.wpix
```

There is no persistent session. Each invocation starts fresh.

## 2. Capture Workflow

### Launch and capture

```powershell
# Launch app and immediately take 1-frame GPU capture
& $pix launch "C:\MyApp\app.exe" take-capture save-capture "C:\out\frame.wpix"

# Capture N frames
& $pix launch "C:\MyApp\app.exe" take-capture --frames=3 save-capture "C:\out\frame.wpix"

# With command-line args and working directory
& $pix launch "C:\MyApp\app.exe" --command-line="--level forest" --working-directory="C:\MyApp" take-capture save-capture "C:\out\frame.wpix"

# Wait for programmatic capture (app calls PIXBeginCapture/PIXEndCapture)
& $pix launch "C:\MyApp\app.exe" programmatic-capture --open save-capture "C:\out\frame.wpix"

# UWP app
& $pix launch-app "com.example.myapp_xyz" "App" take-capture save-capture "C:\out\frame.wpix"
```

### Open and save existing capture

```powershell
& $pix open-capture "C:\captures\frame.wpix" save-screenshot "C:\out\thumb.png"
```

## 3. Frame Exploration

```powershell
# Save full event list to CSV (no counters)
& $pix open-capture frame.wpix save-event-list events.csv

# Save event list with ALL counters
& $pix open-capture frame.wpix save-event-list events.csv --counters="*"

# Save event list with D3D counters only
& $pix open-capture frame.wpix save-event-list events.csv --counter-groups="D3D:*"

# List all available GPU counters
& $pix open-capture frame.wpix list-counters

# Save screenshot embedded in capture
& $pix open-capture frame.wpix save-screenshot thumb.png
```

After saving the event CSV, read it with the Read tool or parse it with Python
to find expensive draw calls, sorted by GPU time.

Column names depend on hardware; common: `"GPU Duration (ms)"`, `"D3D: GPU Duration"`.

```python
import csv, sys

rows = list(csv.DictReader(open("events.csv")))
print(rows[0].keys())   # inspect available columns first
gpu_col = next((k for k in rows[0] if "GPU" in k and "Duration" in k), None)
if gpu_col:
    top = sorted(rows, key=lambda r: float(r.get(gpu_col) or 0), reverse=True)[:20]
    for r in top:
        print(f"{float(r[gpu_col]):8.3f}ms  {r.get('Name','')}")

## 4. Resource Inspection

Always export to PNG, then use the **Read tool** to view the image.

```powershell
# Save RTV 0 at end of capture
& $pix open-capture frame.wpix save-resource rt0.png

# Save RTV 1 (second render target)
& $pix open-capture frame.wpix save-resource rt1.png --rtv=1

# Save depth buffer (visual representation)
& $pix open-capture frame.wpix save-resource depth.png --depth

# Save resource at a specific PIX marker region (last child of that region)
& $pix open-capture frame.wpix save-resource shadow.png --marker="ShadowPass"
& $pix open-capture frame.wpix save-resource shadow_depth.png --marker="ShadowPass" --depth

# Save resource at a specific Global ID (event number from the event list CSV)
& $pix open-capture frame.wpix save-resource gbuffer.png --global-id=4567

# Save RTV 2 at a specific event
& $pix open-capture frame.wpix save-resource gbuffer_n.png --global-id=4567 --rtv=2
```

**Workflow**: Export → Read tool (view image) → correlate with event CSV.

## 5. GPU Performance Counters

```powershell
# List all counters for this GPU
& $pix open-capture frame.wpix list-counters

# Common counter group patterns:
#   D3D:*          D3D12 built-in counters
#   GPU:*          Hardware counters (vendor-specific)
#   *Occupancy*    Shader occupancy
#   *Duration*     Timing counters
#   *Cache*        Cache hit rates

# Save event list with specific counter groups
& $pix open-capture frame.wpix save-event-list perf.csv --counter-groups="D3D:*" --counter-groups="GPU:*"

# High-frequency counters (per-clock sampling)
& $pix open-capture frame.wpix save-high-frequency-counters hf_counters.csv --counters="*"
& $pix open-capture frame.wpix save-high-frequency-counters hf_merged.csv --counters="*" --merge
```

### Performance profiling workflow (CPU-side bottleneck analysis)

> Only needed when the goal is **"which pass is slow / why is this frame heavy"**.
> Skip this section for render target inspection, API validation, or resource debugging.

```powershell
# Export the 4 timing columns (~20 s).  Do NOT use --counters="*" — it replays
# all hardware counters (2000+ cols) and can take 10+ minutes.
& $pix open-capture frame.wpix save-event-list events_timing.csv `
      "--counters=TOP*" "--counters=EOP*" "--counters=Execution*"

# Then run the bundled analyzer:
python "C:\Users\L\.cursor\skills\pix-gpu-debug\scripts\analyze_frame.py" events_timing.csv
# --top 60   --min-ms 0.1   (optional)
```

The script outputs: frame time, pass breakdown, top-N events, GPU Wait stalls,
Lumen / Bloom detail, EnqueueCopy costs, DrawIndexedInstanced summary.

**CSV parsing gotcha** — pixtool adds a space before quoted names: `, "Name (PS, Static)"`.
Always open with `csv.DictReader(f, skipinitialspace=True)` or columns mis-align.

## 6. GPU Validation / Debug Layer

```powershell
# Force replay with D3D12 debug layer — check for API errors
& $pix open-capture frame.wpix run-debug-layer
```

Check `pixtool.log` (in `%TEMP%`) for debug layer output after running this.

## 7. Recapture Region

```powershell
# Recapture just events 100–200 (use Global IDs from the event CSV)
& $pix open-capture frame.wpix recapture-region slim.wpix --start=100 --end=200
```

Useful for isolating expensive regions before opening in the PIX GUI for shader debugging.

## 8. Export to C++ Project

```powershell
# Export capture as a standalone D3D12 C++ repro
& $pix open-capture frame.wpix export-to-cpp "C:\out\repro" --use-winpixeventruntime --use-agilitySdk --force
```

Generates a Visual Studio project that replays the captured frame. Useful for:
- Submitting repros to GPU driver teams
- Offline shader inspection
- CI/CD regression testing

## 9. Debugging Recipes

See [references/debugging-recipes.md](references/debugging-recipes.md) for workflows:
1. Find the slowest draw call
2. Inspect a render target / depth buffer
3. Validate D3D12 API usage
4. Isolate a problematic region
5. Compare two captures

## 10. Output Management

- **Pipe output to file**: `& $pix ... 2>&1 | Tee-Object -FilePath pixtool.log`
- **Check `%TEMP%\pixtool.log`** for verbose engine output after each run
- **Event CSV can be large** — open in Python/pandas rather than Excel for large captures
- **Use `--marker=`** to scope resource saves instead of using `--global-id=` for readability
- **Run pixtool serially** — wait for `exit_code` in the terminal file before starting the next command

## 11. Error Handling

- **`pixtool` not found**: `Get-ChildItem "$env:ProgramFiles\Microsoft PIX" -Recurse -Filter pixtool.exe`
- **`open-capture` fails**: Ensure the `.wpix` file was captured with this PIX version or later
- **`save-resource` returns nothing**: The resource may not be bound at that event — try `--marker=` instead
- **`run-debug-layer` hangs**: GPU timeout/TDR — recapture with fewer frames
- **No counters in CSV**: Run `list-counters` first; GPU plugin may not be loaded (avoid `--disable-gpu-plugins`)
- **Machine freezes / agent times out**: Almost always caused by running multiple pixtool instances
  simultaneously on large captures. Kill all pixtool processes (`Stop-Process -Name pixtool -Force`),
  then re-run **one at a time**.
- **`save-resource` takes 5–10 minutes**: The target GID is near the end of a large capture.
  Use `recapture-region` to create a trimmed capture first, then extract from the trimmed file.
- **`--marker` fails with 0x80070057**: The marker spans multiple D3D12 command lists (common in UE5
  RDG). Fall back to `--global-id=<N>` using a GID found inside that pass from the event CSV.
- **Last draw before Present is black / wrong image**: In UE5 two-frame captures, the last draw
  before Present belongs to Frame N (Slate UI compositing Frame N-1's scene). The actual scene
  rendered in this capture is in Frame N+1's SceneRender. See the UE pipeline section above.

## Command Reference

For all commands with full options, see [references/commands-quick-ref.md](references/commands-quick-ref.md).
