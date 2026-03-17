# Prospero Razor GPU — Command Reference

## razorgpu-cli (Custom Analysis Tool)

Source: https://github.com/real-link-tech/razorgpu-cli (private)

Built with .NET 8, references Sony Razor GPU internal DLLs via reflection.

### `dump-bindings` — Full capture analysis

```bash
razorgpu-cli dump-bindings -in <capture.rzrgpu> -out <output.json>
```

Extracts marker tree with timing, per-batch resource bindings, batch descriptions, and global resource inventory.

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `-in <file>` | yes | Input `.rzrgpu` capture file |
| `-out <file>` | yes | Output `.json` file path |

**Output JSON contains:**

| Section | Description |
|---------|-------------|
| `batchCount` | Total number of batches |
| `batches[]` | Per-batch data: description, type, textures, buffers, RTs, depth, IB |
| `resources` | Global resource inventory: textures, buffers, renderTargets, depthTargets, videoOutBuffers |
| `markers[]` | Marker hierarchy with timing (durationUs) |

**Example:**

```bash
razorgpu-cli dump-bindings -in "X:/PS5GPU/capture.rzrgpu" -out "X:/PS5GPU/analysis.json"
```

---

## RazorCmd.exe (Sony Official CLI)

Version: 11.0.1.0

Path: `C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\RazorCmd.exe`

### `--dumpstats` — Export trace statistics

```bash
RazorCmd.exe --dumpstats [-trace=<N>] -in <file> -out <file.json>
```

Requires replay trace data in the `.rzrgpu` file. Outputs per-batch shader timing, wavefronts, VGPR counts.

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `-in <file>` | yes | Input `.rzrgpu` or `.rtt` file |
| `-out <file>` | yes | Output `.json` file |
| `-trace=<N>` | no | Replay trace index (for multi-trace files) |

### `--export` — Export GPU resources

```bash
RazorCmd.exe --export -resource=<Type><Index> -in <file> -out <dir>
```

**Resource types:** `Buffer`, `IndexBuffer`, `Texture`, `RenderTarget`, `DepthRenderTarget`

Use `*` or omit index to export all. Use `0`, `1`, `2`... for specific resources.

**Examples:**

```bash
RazorCmd.exe --export -resource=Texture92 -in capture.rzrgpu -out export/
RazorCmd.exe --export -resource=Buffer94 -in capture.rzrgpu -out export/
RazorCmd.exe --export -resource=RenderTarget* -in capture.rzrgpu -out export/rts/
```

**Output formats:**

| Resource | Format |
|----------|--------|
| Texture | `.gnf` (PS5 native) |
| RenderTarget | `.gnf` |
| Buffer | `.bin` (raw binary) |
| IndexBuffer | `.bin` |

---

## prospero-coredump2razorgpu.exe

Path: `C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\CommandTools\bin\prospero-coredump2razorgpu.exe`

```bash
prospero-coredump2razorgpu.exe [/o <output.rzrgpu>] [/f <count>] [/g] <corefile>
```

| Flag | Description |
|------|-------------|
| `/o <path>` | Output `.rzrgpu` path |
| `/f <count>` | Command buffer count |
| `/g` | GPU exception coredumps only |

---

## image2gnf.exe

Path: `C:\Program Files (x86)\SCE\Prospero SDKs\11.000\host_tools\bin\image2gnf.exe`

```bash
# Inspect GNF header
image2gnf.exe -i texture.gnf

# Convert to viewable format
image2gnf.exe -f Atlas -i texture.gnf -o output.png
```

**Note:** Use ASCII-only output paths. Convert one file at a time to avoid OOM.

---

## File Formats

| Extension | Description |
|-----------|-------------|
| `.rzrgpu` | Razor GPU capture (frame + resources + optional traces) |
| `.rtt` | Thread trace (fine-grained per-shader timing) |
| `.gnf` | PS5 native texture format |
| `.core` | PS5 coredump (convert with prospero-coredump2razorgpu.exe) |

## GPU Counter Groups (Prospero)

Located at: `C:\Program Files (x86)\SCE\Prospero\Tools\Razor GPU\bin\plugins-architectures\`

| Group | Focus |
|-------|-------|
| `group04_Quad_Pixel_and_Texel_counts` | Pixel/texel throughput |
| `group05_Primitive_Culling_detail_reasons` | Geometry culling |
| `group06_HiZHiS_and_PreZ_Depth_Stencil` | Early depth rejection |
| `group08_VS_PS_Bottleneck_Analysis` | VS/PS bottleneck |
| `group10_CS_Bottleneck_Analysis` | Compute bottleneck |
| `group14_Cache_Read` / `group15_Cache_Write` | Cache efficiency |
| `group170_DCC_Compressed_Access` | DCC compression |
| `group1610_RayTracing_Sol_prospero` | Ray tracing |
