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
  "export PS5 texture", "PS5 coredump GPU", razorgpu-cli, "PS5 per-batch bindings",
  "PS5 marker tree", "PS5 pass timing", "PS5 resource bindings".
  DO NOT use for: PC D3D12 debugging (use PIX), Vulkan debugging (use RenderDoc),
  Xbox GPU debugging, web rendering, CSS, non-PlayStation platforms.
---

# PS5 (Prospero) Razor GPU Debugging Skill

## Overview

This skill enables PS5 GPU frame capture analysis, per-batch resource inspection, pass timing, and resource export using two CLI tools and the official Sony export tool.

| Tool | Purpose |
|------|---------|
| `razorgpu-cli` | **Primary analysis tool** — marker tree with timing, per-batch resource bindings, batch descriptions, global resource inventory |
| `RazorCmd.exe` | Sony official CLI — resource export (textures/buffers/RTs as files), trace stats dump |
| `prospero-coredump2razorgpu.exe` | Convert PS5 crash coredump → `.rzrgpu` |
| `image2gnf.exe` | Inspect/convert PS5 `.gnf` texture files |

### Tool Paths

```bash
# razorgpu-cli (custom analysis tool)
# Source: https://github.com/real-link-tech/razorgpu-cli (private)
# Build: cd X:/PS5GPU/razorgpu-cli && dotnet build -c Release
# Run via: dotnet run -c Release --project X:/PS5GPU/razorgpu-cli -- <args>
# Or directly: X:/PS5GPU/razorgpu-cli/bin/Release/net8.0-windows/razorgpu-cli.exe <args>

# Sony official tools
RAZORCMD="C:/Program Files (x86)/SCE/Prospero/Tools/Razor GPU/bin/RazorCmd.exe"
COREDUMP2RZR="C:/Program Files (x86)/SCE/Prospero/Tools/Razor GPU/bin/CommandTools/bin/prospero-coredump2razorgpu.exe"
IMG2GNF="C:/Program Files (x86)/SCE/Prospero SDKs/11.000/host_tools/bin/image2gnf.exe"
```

## 1. Frame Exploration

Start with a high-level overview of the capture:

```bash
# Full analysis — marker tree, per-batch bindings, resource inventory, timing
razorgpu-cli dump-bindings -in capture.rzrgpu -out analysis.json
```

This single command extracts everything. Parse the JSON to explore:

```python
import json
with open('analysis.json') as f:
    d = json.load(f)

# Frame overview
print(f"Total batches: {d['batchCount']}")
print(f"Marker trees: {len(d.get('markers', []))}")
print(f"Resources: {list(d['resources'].keys())}")
```

### Navigate by marker (pass hierarchy)

The marker tree matches the Workload Navigator in Razor GPU GUI:

```python
# Print marker tree with timing
def print_markers(m, depth=0):
    name = m.get('name') or '(root)'
    dur = m.get('durationUs', 0)
    bs, be = m.get('batchStart', 0), m.get('batchEnd', 0)
    dur_str = f" {dur/1000:.2f}ms" if dur >= 1000 else f" {dur:.0f}us" if dur > 0 else ""
    print(f"{'  '*depth}{name} (B{bs}-{be}){dur_str}")
    for c in m.get('children', []):
        print_markers(c, depth+1)

for m in d['markers']:
    print_markers(m)
```

### Navigate by batch

```python
# Find specific batch types
draws = [b for b in d['batches'] if b.get('type') == 'DrawIndexed']
dispatches = [b for b in d['batches'] if b.get('type') == 'Dispatch']

# Find batches in a specific pass (by index range from markers)
basepass = [b for b in d['batches'] if 858 <= b['index'] <= 1102]

# Find batches with most textures
by_tex = sorted(d['batches'], key=lambda b: b.get('textureCount', 0), reverse=True)
```

## 2. Per-Batch Resource Bindings

Each batch in the JSON contains its resource bindings:

```json
{
  "globalIndex": 899,
  "index": 899,
  "pipeline": "Graphics",
  "queue": "Normal",
  "description": "drawIndexOffset [1536 indices, 0 instances]",
  "type": "DrawIndexed",
  "textureCount": 4,
  "renderTargets": [
    {"type": "RenderTarget", "name": "Render Target 0", "format": "k16_16_16_16", "width": 2720, "height": 1532}
  ],
  "depthTarget": {"type": "DepthRenderTarget"},
  "textures": [
    {"type": "k2d", "name": "Texture 154", "format": "k16UInt", "width": 340, "height": 192, "descriptorIndex": 154}
  ],
  "buffers": [
    {"type": "VSharp", "name": "GPUScene.InstanceSceneData", "descriptorIndex": 94},
    {"type": "VSharp", "name": "FPositionVertexBuffer", "descriptorIndex": 412}
  ],
  "indexBuffer": {"type": "IndexBuffer"}
}
```

### Query bindings for a specific batch

```python
batch = d['batches'][899]
print(f"Batch {batch['index']}: {batch['description']}")
print(f"  Type: {batch['type']}")
print(f"  Textures: {batch.get('textureCount', 0)}")
print(f"  RTs: {len(batch.get('renderTargets', []))}")
print(f"  Buffers: {len(batch.get('buffers', []))}")

# Show all render targets with details
for rt in batch.get('renderTargets', []):
    print(f"  RT: {rt['name']} {rt.get('format')} {rt.get('width')}x{rt.get('height')}")

# Show all textures with details
for tex in batch.get('textures', []):
    print(f"  Tex: {tex['name']} {tex.get('format')} {tex.get('width')}x{tex.get('height')}")

# Show all buffers with names
for buf in batch.get('buffers', []):
    print(f"  Buf: V#{buf['descriptorIndex']} {buf.get('name', '(unnamed)')}")
```

## 3. Resource Inventory

Global resource summary across the entire capture:

```python
res = d['resources']
print(f"Textures: {len(res.get('textures', []))}")
print(f"Buffers (VSharp): {len(res.get('buffers', []))}")
print(f"RenderTargets: {len(res.get('renderTargets', []))}")
print(f"DepthTargets: {len(res.get('depthTargets', []))}")
print(f"VideoOutBuffers: {len(res.get('videoOutBuffers', []))}")
```

### Find specific resources

```python
# Find largest textures
large_tex = sorted(res['textures'], key=lambda t: t.get('size', 0), reverse=True)[:10]

# Find buffers by name
scene_bufs = [b for b in res['buffers'] if 'GPUScene' in b.get('name', '')]

# Find render targets by format
hdr_rts = [r for r in res['renderTargets'] if '16_16_16_16' in r.get('format', '')]
```

## 4. Resource Export

Use Sony's `RazorCmd.exe` to export actual resource data:

```bash
# Export specific texture (by descriptor index)
RazorCmd.exe --export -resource=Texture92 -in capture.rzrgpu -out export/

# Export specific buffer
RazorCmd.exe --export -resource=Buffer94 -in capture.rzrgpu -out export/

# Export all render targets
RazorCmd.exe --export -resource=RenderTarget* -in capture.rzrgpu -out export/rts/

# Export all depth targets
RazorCmd.exe --export -resource=DepthRenderTarget* -in capture.rzrgpu -out export/depth/

# Export all textures
RazorCmd.exe --export -resource=Texture* -in capture.rzrgpu -out export/textures/
```

### View exported resources

After exporting, **use the Read tool** to view PNG/GNF images (the agent is multimodal).

For `.gnf` files (PS5 native texture format):
```bash
# Inspect GNF header
image2gnf.exe -i export/texture_92.gnf

# Convert to viewable format
image2gnf.exe -f Atlas -i export/texture_92.gnf -o C:/analysis/tex92.png
```

Then use the Read tool on the PNG to view it visually.

## 5. Trace Statistics (Replay Trace Data)

Replay traces are separate `.rzrgpu` files (e.g. `GPU_Trace_*.rzrgpu`) created by running a replay on a connected PS5. They contain per-batch shader timing, wavefronts, and VGPR counts. The capture file (`GPU_Capture_*.rzrgpu`) does NOT contain this data.

```bash
# Dump trace stats — use the TRACE file, not the capture file
RazorCmd.exe --dumpstats -in GPU_Trace_xxx.rzrgpu -out trace_stats.json
```

```python
stats = json.load(open('trace_stats.json'))
freq = stats['Configuration']['ClockFrequency']

for pipe in stats['Pipelines']:
    for queue in pipe['Queues']:
        for marker in queue.get('Markers', []):
            for batch in marker.get('Batches', []):
                dur_us = batch['ShaderDuration'] / (freq / 1e6)
                print(f"Batch {batch['Index']}: {dur_us:.1f}us {batch['Description']}")
                for stage in batch.get('Stages', []):
                    print(f"  {stage['Stage']}: {stage['Wavefronts']} waves, VGPR={stage['VgprCount']}")
```

## 6. Debugging Recipes

### Recipe: Which pass is slowest?

```bash
razorgpu-cli dump-bindings -in capture.rzrgpu -out analysis.json
```

```python
# Find top-level passes sorted by duration
def get_passes(markers, depth=1):
    results = []
    for m in markers:
        if m.get('durationUs', 0) > 0:
            results.append((m['name'], m['durationUs'], m.get('batchStart'), m.get('batchEnd')))
        if depth > 0:
            for c in m.get('children', []):
                results.extend(get_passes([c], depth-1))
    return results

passes = get_passes(d['markers'], depth=2)
for name, dur, bs, be in sorted(passes, key=lambda x: x[1], reverse=True)[:10]:
    print(f"{dur/1000:.2f}ms  {name} (B{bs}-{be})")
```

### Recipe: What resources does a specific draw use?

```python
# Find a basepass draw
batch = d['batches'][899]
print(json.dumps(batch, indent=2))

# Then export the actual texture/buffer data for inspection
# RazorCmd.exe --export -resource=Texture154 -in capture.rzrgpu -out export/
```

### Recipe: Find overdraw hotspots

```python
# Find batches with the most render target bindings (potential overdraw)
multi_rt = [b for b in d['batches'] if len(b.get('renderTargets', [])) > 3]
print(f"Batches with 4+ RTs: {len(multi_rt)}")

# Find batches drawing to the same RT multiple times
from collections import Counter
rt_usage = Counter()
for b in d['batches']:
    for rt in b.get('renderTargets', []):
        rt_usage[rt.get('name', 'unknown')] += 1

for name, count in rt_usage.most_common(10):
    print(f"  {name}: used by {count} batches")
```

### Recipe: Analyze a specific UE5 pass

```python
# Find Nanite VisBuffer pass from marker tree
def find_marker(markers, name_contains):
    for m in markers:
        if name_contains.lower() in (m.get('name') or '').lower():
            return m
        result = find_marker(m.get('children', []), name_contains)
        if result:
            return result
    return None

nanite = find_marker(d['markers'], 'Nanite::VisBuffer')
if nanite:
    print(f"Nanite VisBuffer: {nanite['durationUs']/1000:.2f}ms (B{nanite['batchStart']}-{nanite['batchEnd']})")

    # Get all batches in this pass
    nanite_batches = [b for b in d['batches']
                      if nanite['batchStart'] <= b['index'] <= nanite['batchEnd']]
    print(f"  {len(nanite_batches)} batches")
    print(f"  Types: {Counter(b.get('type') for b in nanite_batches)}")
```

### Recipe: GPU crash coredump analysis

```bash
# 1. Convert coredump
prospero-coredump2razorgpu.exe /o crash.rzrgpu /g crash.core

# 2. Analyze with razorgpu-cli
razorgpu-cli dump-bindings -in crash.rzrgpu -out crash_analysis.json

# 3. Export render targets to see last rendered state
RazorCmd.exe --export -resource=RenderTarget* -in crash.rzrgpu -out crash_export/
```

### Recipe: Compare two captures

```python
# Load both
with open('before.json') as f: before = json.load(f)
with open('after.json') as f: after = json.load(f)

# Compare pass timings
def get_timing_map(data):
    result = {}
    def walk(markers):
        for m in markers:
            if m.get('name') and m.get('durationUs'):
                result[m['name']] = m['durationUs']
            walk(m.get('children', []))
    walk(data.get('markers', []))
    return result

before_t = get_timing_map(before)
after_t = get_timing_map(after)

for name in sorted(set(before_t) & set(after_t), key=lambda n: abs(after_t[n] - before_t[n]), reverse=True)[:10]:
    delta = after_t[name] - before_t[name]
    print(f"{delta/1000:+.2f}ms  {name} ({before_t[name]/1000:.2f} -> {after_t[name]/1000:.2f}ms)")
```

## 7. Performance Interpretation

### PS5 GPU time budgets

| Target FPS | Frame budget | Typical breakdown |
|-----------|-------------|-------------------|
| 30 fps | 33.3 ms | Most PS5 titles |
| 60 fps | 16.7 ms | Performance mode |
| 120 fps | 8.3 ms | High-refresh mode |

### Common UE5 PS5 passes and typical costs

| Pass | What it does | Typical cost |
|------|-------------|-------------|
| Nanite::VisBuffer | Nanite mesh rasterization | 3-8ms |
| ShadowDepths (VSM) | Virtual shadow maps | 3-8ms |
| BasePass | Material evaluation (GBuffer fill) | 1-3ms |
| LumenSceneLighting | Lumen GI lighting | 3-7ms |
| TSR | Temporal Super Resolution | 5-15ms |
| PostProcessing | Bloom, tonemapping, etc. | 1-3ms |
| Hair | Hair rendering (Groom) | 1-3ms |

### PS5-specific notes

- **AGC** (AMD GPU Custom): PS5 uses low-level AGC API over GNMX
- **PSSL shaders**: PlayStation Shading Language (HLSL-like), compiled to RDNA2 ISA
- **Wave32**: PS5 GPU executes shaders in 32-thread waves
- **DCC** (Delta Color Compression): Automatic render target compression
- **Async Compute**: Graphics and Compute queues run in parallel
- **Nanite**: UE5's virtual geometry system, heavy on compute + rasterization

## 8. Output JSON Schema

### Top-level

```json
{
  "capture": "filename.rzrgpu",
  "batchCount": 2999,
  "batches": [...],
  "resources": {...},
  "markers": [...]
}
```

### Batch fields

| Field | Type | Description |
|-------|------|-------------|
| `globalIndex` | int | Sequential index across all queues |
| `index` | int | Index within its queue |
| `pipeline` | string | "Graphics" or "Compute0" etc. |
| `queue` | string | "Normal" or "Queue1" etc. |
| `description` | string | Command string (e.g. "drawIndexOffset [1536 indices]") |
| `type` | string | "Draw", "DrawIndexed", "Dispatch", "Other" |
| `textureCount` | int? | Number of textures bound |
| `renderTargets` | ResourceInfo[]? | Bound render targets with format/dimensions |
| `depthTarget` | ResourceInfo? | Bound depth target |
| `indexBuffer` | ResourceInfo? | Bound index buffer |
| `textures` | ResourceInfo[]? | Bound textures with format/dimensions |
| `buffers` | ResourceInfo[]? | Bound buffers with names |

### Marker fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Marker name (pass name) |
| `pipeline` | string? | Pipeline name (only on root) |
| `batchStart` | uint | First batch index |
| `batchEnd` | uint | Last batch index |
| `batchCount` | uint | Number of batches |
| `durationUs` | double | Duration in microseconds |
| `children` | MarkerData[]? | Child markers |

### ResourceInfo fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Resource type |
| `name` | string? | Resource name |
| `format` | string? | Pixel/data format |
| `width` | int? | Width in pixels |
| `height` | int? | Height in pixels |
| `depth` | int? | Depth (for 3D textures) |
| `mips` | int? | Mip level count |
| `size` | long? | Size in bytes |
| `descriptorIndex` | uint? | Descriptor table index |
| `address` | string? | GPU virtual address (hex) |

## 9. Error Handling

### razorgpu-cli crashes with AccessViolationException
Some VSharp (buffer) descriptors crash when accessed in offline mode. The tool handles this gracefully — buffer names come from resource registrations instead.

### "Source file contains no traces"
The `.rzrgpu` file is a capture-only file without replay trace data. Use `razorgpu-cli dump-bindings` for marker tree and resource bindings (works without traces). For shader timing/wavefronts, you need a separate trace `.rzrgpu` file.

### Exported RTs are `.gnf`, not `.png`
Normal for PS5. Use `image2gnf.exe -i file.gnf` to inspect, then `-f Atlas` to convert. Use ASCII-only output paths to avoid WIC errors.

### GNF conversion OOMs
Convert one file at a time, not whole directories.

## Command Quick Reference

For `razorgpu-cli` command details, see [references/commands-reference.md](references/commands-reference.md).
