# PIX Debugging Recipes

Each recipe assumes `$pix` is set to the full path of `pixtool.exe`.

---

## Recipe 1: Find the Slowest Draw Calls

**Goal**: Rank all draw calls by GPU duration to find the frame's bottleneck.

```powershell
# Step 1: Export event list with timing counters
& $pix open-capture frame.wpix save-event-list events.csv --counter-groups="D3D:*"
```

```python
# Step 2: Parse and rank (run in Python)
import csv

rows = list(csv.DictReader(open("events.csv")))

# Inspect available columns
print(list(rows[0].keys())[:10])

# Find GPU duration column (name varies by GPU vendor)
gpu_col = next(
    (k for k in rows[0] if "GPU" in k and "Duration" in k),
    next((k for k in rows[0] if "Duration" in k), None)
)
if not gpu_col:
    print("No duration column found. Run list-counters to see what's available.")
else:
    top = sorted(rows, key=lambda r: float(r.get(gpu_col) or 0), reverse=True)[:20]
    print(f"\nTop 20 by {gpu_col}:")
    for r in top:
        gid = r.get("Global ID", "")
        name = r.get("Name", "")
        t = float(r.get(gpu_col) or 0)
        print(f"  [{gid:>8}] {t:8.3f}ms  {name}")
```

**Follow-up**: Use the Global ID from the top result with `save-resource --global-id=<id>` to inspect what was being rendered.

---

## Recipe 2: Inspect a Render Target or Depth Buffer

**Goal**: See what a render target looks like at a specific pass.

```powershell
# By PIX marker name (most readable)
& $pix open-capture frame.wpix save-resource "C:\out\gbuffer_albedo.png" --marker="GBuffer"
& $pix open-capture frame.wpix save-resource "C:\out\gbuffer_depth.png"  --marker="GBuffer" --depth

# By Global ID (from event CSV)
& $pix open-capture frame.wpix save-resource "C:\out\rt_at_5000.png" --global-id=5000

# Second render target in an MRT setup
& $pix open-capture frame.wpix save-resource "C:\out\gbuffer_normal.png" --marker="GBuffer" --rtv=1

# End of frame (default - no marker/global-id)
& $pix open-capture frame.wpix save-resource "C:\out\final.png"
```

After exporting, use the **Read tool** to view the PNG and describe what you see.

---

## Recipe 3: GPU Counter Deep-Dive

**Goal**: Find GPU bottleneck — bandwidth, occupancy, cache misses.

```powershell
# Step 1: See what's available for this GPU
& $pix open-capture frame.wpix list-counters > available_counters.txt
```

Then read `available_counters.txt` to identify relevant counter names/groups.

```powershell
# Step 2: Collect targeted counters
& $pix open-capture frame.wpix save-event-list perf.csv `
    --counter-groups="D3D:*" `
    --counter-groups="GPU:*"

# For high-frequency (per-clock) data
& $pix open-capture frame.wpix save-high-frequency-counters hf.csv --counters="*" --merge
```

```python
# Step 3: Find occupancy and bandwidth issues
import csv

rows = list(csv.DictReader(open("perf.csv")))
keys = list(rows[0].keys())

# Find occupancy columns
occ_cols = [k for k in keys if "Occupancy" in k or "occupancy" in k]
# Find bandwidth columns
bw_cols  = [k for k in keys if "Bandwidth" in k or "bandwidth" in k]

print("Occupancy columns:", occ_cols)
print("Bandwidth columns:", bw_cols)

# Report events where occupancy < 50%
for col in occ_cols:
    low = [r for r in rows if float(r.get(col) or 100) < 50]
    print(f"\n{col}: {len(low)} events below 50% occupancy")
    for r in low[:10]:
        print(f"  [{r['Global ID']:>8}] {r['Name']}")
```

---

## Recipe 4: D3D12 API Validation

**Goal**: Find API misuse, missing barriers, or state bugs.

```powershell
# Replay with debug layer — check log for errors
& $pix open-capture frame.wpix run-debug-layer
```

Errors appear in `%TEMP%\pixtool.log`. Read it after the command:

```powershell
# Read the log
Get-Content "$env:TEMP\pixtool.log" | Select-String "ERROR|CORRUPTION|WARNING" | Select-Object -First 50
```

**Common debug layer errors and what they mean:**

| Error pattern | Likely cause |
|--------------|--------------|
| `Resource barrier` | Missing or wrong `ResourceBarrier` transition |
| `Root signature` | Descriptor table out of range |
| `Aliasing` | Heap aliasing violation |
| `GPU-based validation` | Out-of-bounds buffer access |

---

## Recipe 5: Isolate and Recapture a Region

**Goal**: Create a minimal capture containing only the problematic region, for sharing or detailed analysis.

```powershell
# Step 1: Get event list to find Global ID range of the problem area
& $pix open-capture frame.wpix save-event-list events.csv

# Step 2: Look for the marker region in events.csv
# In Python, find start/end Global IDs of "ShadowPass":
```

```python
import csv
rows = list(csv.DictReader(open("events.csv")))
shadow = [r for r in rows if "Shadow" in r.get("Name","")]
if shadow:
    print("Shadow events:", shadow[0]["Global ID"], "to", shadow[-1]["Global ID"])
```

```powershell
# Step 3: Recapture just that region
& $pix open-capture frame.wpix recapture-region shadow_only.wpix --start=1200 --end=1800

# Step 4: Analyze the isolated capture
& $pix open-capture shadow_only.wpix save-event-list shadow_events.csv --counters="*"
& $pix open-capture shadow_only.wpix save-resource shadow_rt.png
```

---

## Recipe 6: Generate a C++ Repro

**Goal**: Create a self-contained D3D12 project that reproduces the captured frame.

```powershell
# Export full capture to C++ project
& $pix open-capture frame.wpix `
    export-to-cpp "C:\repro\MyFrame" `
    --force `
    --use-winpixeventruntime `
    --use-agilitySdk
```

The output is a Visual Studio solution at `C:\repro\MyFrame`. Open in VS, build, and run.
Use this for:
- Driver bug repros (send to GPU vendor)
- CI screenshot regression tests
- Offline shader modification

---

## Recipe 7: Capture a Specific Frame from a Running App

**Goal**: Trigger a GPU capture of exactly the frame showing the artifact.

**Option A — Programmatic (requires app code)**:

Add to your application (D3D12):
```cpp
#include "pix3.h"
// In your render loop:
if (shouldCapture) {
    PIXBeginCapture(PIX_CAPTURE_GPU, nullptr);
    // ... render the problematic frame ...
    PIXEndCapture(false);
}
```

Then capture with pixtool:
```powershell
& $pix launch "MyApp.exe" programmatic-capture save-capture artifact_frame.wpix
```

**Option B — CLI trigger**:
```powershell
# Launch app, wait for steady state, then capture
& $pix launch "MyApp.exe" --captureFromStart take-capture --frames=1 save-capture frame.wpix
```

**Option C — Attach to running process**:
```powershell
# Find the PID first
$pid = (Get-Process MyApp).Id
& $pix attach $pid take-capture save-capture frame.wpix
```

---

## Recipe 8: Compare Two Unreal Engine Captures

**Goal**: Find rendering differences between two `.wpix` captures of the same UE5 scene.

> ⚠️ **Run all pixtool commands serially — one at a time.** Each command loads a
> multi-GB capture and replays every event. Parallel execution will freeze the machine.

### Step 1 — Export event lists (serially)

```powershell
# Wait for the first to finish before running the second
& $pix open-capture captureA.wpix save-event-list A_events.csv
& $pix open-capture captureB.wpix save-event-list B_events.csv
```

### Step 2 — Identify the scene render frame in each capture

```powershell
$q = "C:\Users\L\.cursor\skills\pix-gpu-debug\scripts\ue_capture_query.py"
python $q A_events.csv frames
python $q B_events.csv frames
# Look for the frame marked [3D SceneRender ← use this for pass analysis]
```

### Step 3 — Find the PostProcessing → Tonemapper subpass

```powershell
# List all named passes and their last Draw GID in one shot
python $q A_events.csv passes
python $q B_events.csv passes

# Drill into PostProcessing children to find the tonemapper subpass
# (use the PostProcessing QID printed by 'passes')
python $q A_events.csv children <A_PostProcessing_QID>
python $q B_events.csv children <B_PostProcessing_QID>

# Once you identify the tonemapper subpass QID, get its last draw GID
python $q A_events.csv last-draw <A_Tonemapper_QID>
python $q B_events.csv last-draw <B_Tonemapper_QID>
```

### Step 4 — Extract the correct render target (serially)

Once you have the last draw GID inside the Tonemapper subpass for both captures:

```powershell
# A first — wait for it to finish
& $pix open-capture captureA.wpix save-resource A_scene_final.png --global-id=<A_tonemap_gid>

# Then B
& $pix open-capture captureB.wpix save-resource B_scene_final.png --global-id=<B_tonemap_gid>
```

> **GID cost**: Each `save-resource --global-id=N` replays every event from 0 to N.
> For large captures (50,000+ events) with a high GID, this can take 5–10 minutes.
> If the target GID is near the end of the capture, use `recapture-region` first:
>
> ```powershell
> & $pix open-capture captureA.wpix recapture-region A_slim.wpix --start=<tonemap_gid - 500> --end=<tonemap_gid + 10>
> & $pix open-capture A_slim.wpix save-resource A_scene_final.png
> ```

### Step 5 — Generate heatmap diff

```powershell
powershell -ExecutionPolicy Bypass -File ".cursor\skills\png-diff-heatmap\scripts\run_png_diff_heatmap.ps1" `
  -ImageA "A_scene_final.png" `
  -ImageB "B_scene_final.png" `
  -OutputDir "compare_out" `
  -Prefix "scene" `
  -Threshold 0.02 -Gamma 0.5
```

Read the generated `scene_diff_overlay.png` and `scene_diff_stats.json` to identify
hotspot regions and changed pixel ratios.

### Step 6 — Repeat for intermediate passes (optional, serially)

| Pass | Typical last draw GID range | Notes |
|------|----------------------------|-------|
| BasePass | Early-mid (GBuffer albedo/normal/roughness) | MRT: use `--rtv=0/1/2` |
| DiffuseIndirectAndAO | Mid (Lumen GI) | Dim image, shows GI only |
| ShadowDepths | Mid-late | Use `--depth` |
| LightShafts (Bloom) | Late | Shows bloom contribution |

Always extract A's pass → generate heatmap → then move to the next pass.
Never extract multiple passes in parallel.
