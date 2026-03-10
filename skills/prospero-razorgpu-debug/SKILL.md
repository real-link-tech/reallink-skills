---
name: prospero-razorgpu-debug
description: >
  PS5 (Prospero) GPU frame debugging and analysis with Razor GPU command-line tools.
  Use this skill when the user mentions: PS5 GPU, Razor GPU, .rzrgpu files, .rtt files,
  Prospero GPU capture, PSSL shaders, GNM/GNMX, AGC command buffers, PS5 rendering,
  PS5 GPU counters, PS5 performance, PS5 frame capture, PS5 render target, PS5 texture export,
  PS5 crash/coredump GPU analysis, prospero-razorgpu-cmd, RazorGPU, PS5 GPU profiling,
  PS5 bottleneck analysis, PS5 draw calls, PS5 GPU debugging, PS5 thread trace,
  "PS5 frame analysis", "inspect PS5 render target", "PS5 GPU stats", "PS5 GPU exception",
  "export PS5 texture", "PS5 coredump GPU".
  DO NOT use for: PC D3D12 debugging (use PIX), Vulkan debugging (use RenderDoc),
  Xbox GPU debugging, web rendering, CSS, non-PlayStation platforms.
---

# PS5 (Prospero) Razor GPU Debugging Skill

## Overview

Razor GPU is Sony's GPU frame debugger and profiler for PS5 (Prospero). The CLI exposes
two core operations on `.rzrgpu` / `.rtt` capture files:

| Tool | Purpose |
|------|---------|
| `prospero-razorgpu-cmd.exe` | Stats dump + resource export |
| `prospero-coredump2razorgpu.exe` | Convert PS5 crash coredump → `.rzrgpu` |
| `image2gnf.exe` | Inspect `.gnf` headers and convert `.gnf` → PNG/BMP/DDS atlas |
| `PS5RazorGPU.exe` | Main GUI (not CLI-scriptable) |

**Binary path:**
```
C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\CommandTools\bin\prospero-razorgpu-cmd.exe
```

**Set an alias for convenience in PowerShell:**
```powershell
$rzr = "C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\CommandTools\bin\prospero-razorgpu-cmd.exe"
$rzr2rdc = "C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\CommandTools\bin\prospero-coredump2razorgpu.exe"
$img2gnf = "C:\Program Files (x86)\SCE\Prospero SDKs\11.000\host_tools\bin\image2gnf.exe"
```

## 1. Command Reference

### `--dumpstats` — Export trace statistics to JSON

```powershell
& $rzr --dumpstats -in capture.rzrgpu -out stats.json

# With multiple replay traces: specify trace index
& $rzr --dumpstats -trace=0 -in capture.rzrgpu -out stats_trace0.json
& $rzr --dumpstats -trace=1 -in capture.rzrgpu -out stats_trace1.json

# Also works with .rtt (thread-trace) files
& $rzr --dumpstats -in capture.rtt -out stats.json
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `-in <file>` | yes | Input `.rzrgpu` or `.rtt` file |
| `-out <file>` | yes | Output `.json` file path |
| `-trace=<N>` | no | Index of replay trace (for multi-trace `.rzrgpu`) |

### `--export` — Export GPU resources to files

```powershell
# Export all render targets
& $rzr --export -resource=RenderTarget* -in capture.rzrgpu -out output\rendertargets\

# Export a specific render target by index
& $rzr --export -resource=RenderTarget0 -in capture.rzrgpu -out output\rt0\
& $rzr --export -resource=RenderTarget3 -in capture.rzrgpu -out output\rt3\

# Export all textures
& $rzr --export -resource=Texture* -in capture.rzrgpu -out output\textures\

# Export a specific texture
& $rzr --export -resource=Texture7 -in capture.rzrgpu -out output\tex7\

# Export all depth render targets
& $rzr --export -resource=DepthRenderTarget* -in capture.rzrgpu -out output\depth\

# Export all index buffers
& $rzr --export -resource=IndexBuffer* -in capture.rzrgpu -out output\indices\

# Export all buffers
& $rzr --export -resource=Buffer* -in capture.rzrgpu -out output\buffers\
```

**Resource types:**

| Type | Description |
|------|-------------|
| `RenderTarget` | Color render targets (exported as PNG/DDS) |
| `DepthRenderTarget` | Depth/stencil buffers |
| `Texture` | Shader-readable textures |
| `Buffer` | Generic GPU buffers (exported as binary) |
| `IndexBuffer` | Index buffers (exported as binary) |

Use `*` or omit the index to export all resources of a type. Use `0`, `1`, `2`… to export a specific one.

**Output directory is created automatically if it does not exist.**

## 2. Coredump Conversion

Convert a PS5 GPU crash coredump to an inspectable `.rzrgpu` file:

```powershell
# Basic conversion
& $rzr2rdc /o output.rzrgpu corefile.core

# Capture N command buffers
& $rzr2rdc /o output.rzrgpu /f 3 corefile.core

# GPU exception only (skip non-GPU coredumps)
& $rzr2rdc /o output.rzrgpu /g corefile.core
```

**Arguments:**

| Flag | Description |
|------|-------------|
| `/o <path>` | Output `.rzrgpu` file path |
| `/f <count>` | Frame/command-buffer count to capture |
| `/g` | Only convert coredumps caused by GPU exception |
| `/h` | Show help |

After conversion, inspect with `--dumpstats` and `--export` as normal.

## 3. Stats JSON Structure

`--dumpstats` produces a JSON file. Open it and parse as follows:

```powershell
$stats = Get-Content stats.json | ConvertFrom-Json
```

**Top-level shape (typical):**
```json
{
  "TraceInfo": {
    "FrameCount": 1,
    "GpuDurationMs": 12.34,
    "CaptureTimeStamp": "...",
    "Architecture": "Prospero"
  },
  "DrawCallStats": [
    {
      "Index": 0,
      "Name": "DrawIndexed",
      "GpuDurationUs": 450.2,
      "VertexCount": 36000,
      "InstanceCount": 1
    }
  ],
  "Counters": {
    "Sum_CB_DRAWN_PIXEL": 2073600,
    "Ratio_SQTT_INSTS_WAVE32_VALU": 0.72,
    "Sum_GL2C_EA_RDREQ_DRAM_32B__Byte": 134217728
  },
  "ReplayTraces": [...]
}
```

### Useful counter patterns

| Counter identifier | What it means |
|---|---|
| `Sum_CB_DRAWN_PIXEL` | Pixels written to color buffer (overdraw indicator) |
| `Ratio_SQTT_INSTS_WAVE32_VALU` | % of shader time in VALU (higher = shader-bound) |
| `Ratio_SQTT_VMEM_BUS_STALL_TA_ADDR_FIFO_FULL` | % time stalled on texture/memory fetches |
| `Sum_SQTT_WAIT_CNT_VMVS` | Shader wait counts for VMEM load/store |
| `Sum_GL2C_EA_RDREQ_DRAM_32B__Byte` | Main memory reads via GL2$ (bytes) |
| `Sum_GL2C_EA_WRREQ_DRAM_32B__Byte` | Main memory writes via GL2$ (bytes) |
| `Sum_PA_PA_INPUT_PRIM` | Primitives input to PA (geometry throughput) |
| `Sum_PA_SU_OUTPUT_PRIM` | Primitives output after setup/culling |

## 4. Visual Inspection Pattern

After exporting resources, **use the Read tool** to view PNG images (the agent is multimodal):

```powershell
# 1. Export render targets
& $rzr --export -resource=RenderTarget* -in capture.rzrgpu -out C:\analysis\rts\

# 2. List exported files
Get-ChildItem C:\analysis\rts\

# 3. If Razor exported .gnf files, inspect one header first
& $img2gnf -i C:\analysis\rts\render_target_5.gnf

# 4. Convert ONE .gnf to a standard image in an ASCII-only output path
#    Use a small/single file first to avoid OOM on large HDR/multi-surface RTs.
& $img2gnf -f Atlas -i C:\analysis\rts\render_target_5.gnf -o C:\analysis_ascii\rt5.png

# 5. View with Read tool (renders images visually)
# Read tool: C:\analysis_ascii\rt5.png
```

Do NOT use `cat` to view images. The Read tool renders them visually.

### `.gnf` conversion notes

- PS5 Razor exports render targets and depth targets as `.gnf` in many captures, even when the resource is logically a color/depth surface.
- `image2gnf.exe -i <file.gnf>` is the fastest safe way to inspect dimensions, mip count, and format before trying to convert or open the file.
- Prefer converting **one file at a time** with `-f Atlas` when validating the workflow. Large captures can contain dozens of RTs and converting them all at once can OOM.
- Use an **ASCII-only output path** for converted images. Writing `.png` to paths with non-ASCII characters can fail with WIC error `0x80070003`.
- For large RTs, avoid opening the whole export directory in GUI viewers first. Probe one candidate `.gnf`, confirm conversion works, then continue selectively.

## 5. Analysis Workflows

### Workflow: Analyze frame performance

```powershell
$rzr = "C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\CommandTools\bin\prospero-razorgpu-cmd.exe"

# Step 1: Extract stats
& $rzr --dumpstats -in frame.rzrgpu -out analysis\stats.json

# Step 2: Parse key metrics
$stats = Get-Content analysis\stats.json | ConvertFrom-Json

# GPU frame time
$stats.TraceInfo.GpuDurationMs

# Total draw calls
$stats.DrawCallStats.Count

# Top 5 most expensive draw calls
$stats.DrawCallStats | Sort-Object GpuDurationUs -Descending | Select-Object -First 5

# Memory bandwidth
$stats.Counters.'Sum_GL2C_EA_RDREQ_DRAM_32B__Byte'
$stats.Counters.'Sum_GL2C_EA_WRREQ_DRAM_32B__Byte'
```

### Workflow: Inspect render targets

```powershell
# Export all render targets
& $rzr --export -resource=RenderTarget* -in frame.rzrgpu -out analysis\rts\

# Export depth buffer
& $rzr --export -resource=DepthRenderTarget* -in frame.rzrgpu -out analysis\depth\

# List what was exported
Get-ChildItem analysis\rts\ | Select-Object Name, Length

# If exports are .gnf, inspect one candidate first
& $img2gnf -i analysis\rts\render_target_5.gnf

# Convert a single candidate to PNG using an ASCII-only output path
& $img2gnf -f Atlas -i analysis\rts\render_target_5.gnf -o C:\analysis_ascii\rt5.png

# View with Read tool to diagnose visual issues
```

### Workflow: Diagnose visual artifact

```powershell
# 1. Dump stats to understand the frame
& $rzr --dumpstats -in frame.rzrgpu -out analysis\stats.json

# 2. Export all render targets to find which pass has the artifact
& $rzr --export -resource=RenderTarget* -in frame.rzrgpu -out analysis\rts\
& $rzr --export -resource=DepthRenderTarget* -in frame.rzrgpu -out analysis\depth\
& $rzr --export -resource=Texture* -in frame.rzrgpu -out analysis\textures\

# 3. If Razor emitted .gnf files, inspect and convert likely candidates one-by-one
& $img2gnf -i analysis\rts\render_target_5.gnf
& $img2gnf -f Atlas -i analysis\rts\render_target_5.gnf -o C:\analysis_ascii\rt5.png

# 4. View each exported PNG with Read tool, looking for:
#    - Unexpected black/missing regions
#    - Incorrect colors or missing objects
#    - Depth buffer oddities (z-fighting, incorrect depth range)
#    - Shadow map issues

# 5. Cross-reference index from the exported filename with DrawCallStats
#    in the JSON to find the corresponding draw call
```

### Workflow: Multi-trace comparison

```powershell
# For .rzrgpu files with multiple replay traces (before/after a change)
& $rzr --dumpstats -trace=0 -in capture.rzrgpu -out analysis\stats_trace0.json
& $rzr --dumpstats -trace=1 -in capture.rzrgpu -out analysis\stats_trace1.json

# Compare GPU time
$t0 = (Get-Content analysis\stats_trace0.json | ConvertFrom-Json).TraceInfo.GpuDurationMs
$t1 = (Get-Content analysis\stats_trace1.json | ConvertFrom-Json).TraceInfo.GpuDurationMs
Write-Host "Trace 0: ${t0}ms  Trace 1: ${t1}ms  Delta: $([math]::Round($t1-$t0,3))ms"
```

### Workflow: GPU crash coredump analysis

```powershell
$rzr2rdc = "C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\CommandTools\bin\prospero-coredump2razorgpu.exe"

# 1. Convert the coredump (GPU exception only)
& $rzr2rdc /o analysis\crash.rzrgpu /g crash.core

# 2. Dump stats from the converted capture
& $rzr --dumpstats -in analysis\crash.rzrgpu -out analysis\crash_stats.json

# 3. Export render targets to see what was being rendered when the crash occurred
& $rzr --export -resource=RenderTarget* -in analysis\crash.rzrgpu -out analysis\crash_rts\
& $rzr --export -resource=DepthRenderTarget* -in analysis\crash.rzrgpu -out analysis\crash_depth\

# 4. View exported images with Read tool
# 5. Parse crash stats JSON for context (draw count, last draw name, counters)
```

## 6. Performance Interpretation Guide

### GPU time red flags

| Symptom | Likely bottleneck | Counter to check |
|---------|------------------|-----------------|
| High shader time | VALU/compute bound | `Ratio_SQTT_INSTS_WAVE32_VALU` |
| Stalls on memory | Texture/buffer bandwidth | `Ratio_SQTT_VMEM_BUS_STALL_TA_ADDR_FIFO_FULL` |
| High DRAM read bandwidth | Texture cache misses or large textures | `Sum_GL2C_EA_RDREQ_DRAM_32B__Byte` |
| Low primitive output vs input | Heavy culling (OK) or geometry issue | `Sum_PA_SU_OUTPUT_PRIM` vs `Sum_PA_PA_INPUT_PRIM` |
| High pixel count | Overdraw or expensive fill | `Sum_CB_DRAWN_PIXEL` |

### PS5-specific notes

- **AGC** (AMD GPU Custom): PS5 uses a low-level AGC API over GNMX. Draw calls appear as AGC command buffer submissions.
- **PSSL shaders**: PlayStation Shading Language (HLSL-like). Compiled to native GCN/RDNA ISA.
- **Wave32 vs Wave64**: PS5 GPU executes shaders in waves of 32 or 64 threads. `WAVE32` counters are the primary ones.
- **DCC** (Delta Color Compression): PS5 uses DCC for render target compression. High DCC miss rate increases bandwidth.
- **Thread traces (`.rtt`)**: Fine-grained per-shader timing data. Use with `--dumpstats` on `.rtt` files.

## 7. Output File Formats

| Resource type | Export format | Notes |
|---|---|---|
| RenderTarget | Often `.gnf` from Razor; convert to PNG/BMP/DDS with `image2gnf.exe` | Prefer single-file conversion first |
| DepthRenderTarget | Often `.gnf` from Razor; convert with `image2gnf.exe` | Depth views may appear as grayscale or encoded masks |
| Texture | `.gnf`, PNG, or DDS depending on capture/tool path | Format depends on texture format |
| Buffer | Binary `.bin` | Raw GPU buffer data |
| IndexBuffer | Binary `.bin` | Raw index data |

**For `.gnf` files**: Use `image2gnf.exe -i file.gnf` to inspect the header, then `image2gnf.exe -f Atlas -i file.gnf -o C:\ascii_path\file.png` to create a viewable image.

**For DDS files**: Convert to PNG for visual inspection using `magick convert input.dds output.png` (requires ImageMagick) before using the Read tool.

## 8. Error Handling

### "File not found" on `-in`
Verify the `.rzrgpu` path. Use tab-complete or `Get-ChildItem` to confirm.

### Export produces no files
The capture may not contain resources of that type. Try `RenderTarget*` or `Texture*` with wildcard first before specifying an index.

### Exported RTs are `.gnf`, not `.png`
This is normal on PS5 captures. Use `image2gnf.exe -i file.gnf` to inspect the resource, then convert a single candidate with `-f Atlas` to a PNG/BMP/DDS output.

### `image2gnf.exe` fails with WIC error `0x80070003`
The output path likely contains non-ASCII characters. Retry with an ASCII-only output path such as `C:\analysis_ascii\rt5.png`.

### Converting `.gnf` files OOMs
- Do not convert the whole export directory at once
- Start with one small `.gnf` file to validate the workflow
- Avoid opening all RTs in GUI viewers first
- Convert only likely candidates for the target pass

### Coredump conversion fails
- Ensure the core file is a valid PS5 coredump
- Use `/g` flag if it's a GPU exception core specifically
- Verify the coredump is not truncated or corrupted

### Stats JSON is empty or minimal
The capture may be a thread-trace-only `.rtt` file without draw stats. Check `TraceInfo` first; if `DrawCallStats` is absent, only counter data is available.

## Command Quick Reference

For complete details, see [references/commands-reference.md](references/commands-reference.md).
