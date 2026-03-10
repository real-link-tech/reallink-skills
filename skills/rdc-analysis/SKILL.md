---
name: rdc-analysis
description: "Analyze RenderDoc .rdc capture files to diagnose rendering issues and perform rendering analysis. Self-contained with bundled Python 3.6 + renderdoc runtime (~36 MB). Use when: (1) User provides a .rdc frame capture file for analysis, (2) Diagnosing rendering problems (black screen, texture errors, depth issues, shader bugs), (3) Analyzing draw call or dispatch pipeline state, (4) Comparing before/after resource states (RT, textures, buffers), (5) Investigating GPU performance bottlenecks, (6) Understanding the rendering pipeline of a captured frame, or (7) Comparing exported render target images with DISCARD-aware pixel difference and brightness analysis."
---

# RDC Analysis

Self-contained skill for analyzing RenderDoc `.rdc` frame captures. Bundles Python 3.6 runtime + renderdoc module + `rdc_export.py` export tool.

## Runtime Requirements

- All scripts **only support Python 3.6** via the bundled interpreter. Do NOT use system Python to run `rdc_export.py` — ABI incompatibility with `renderdoc.pyd`.
- All renderdoc dependencies **must use bundled versions** from `assets/runtime/`. Do NOT substitute with system RenderDoc.
- Always use `run_export.py` as entry point — it auto-deploys the correct runtime.

## Environment Setup

First-time setup is automatic. Run the export runner and it deploys the bundled runtime:

```bash
python "<skill-path>/scripts/run_export.py" --eid -1 <capture.rdc>
```

Runtime deploys to `<workspace>/.rdc-analysis-runtime/` (~36 MB). Subsequent runs skip deployment if unchanged.

## Export Workflow

### Event list only (fastest)

```bash
python "<skill-path>/scripts/run_export.py" --eid -1 <capture.rdc>
```

Produces only `event_list.md` — use to identify target EIDs before full export.

### Single event

```bash
python "<skill-path>/scripts/run_export.py" --eid <EID> <capture.rdc>
```

### Event range

```bash
python "<skill-path>/scripts/run_export.py" --eid <start>-<end> <capture.rdc>
```

### Full export (all events)

```bash
python "<skill-path>/scripts/run_export.py" <capture.rdc>
```

Warning: full export can take minutes and produce gigabytes. Prefer `--eid` filtering.

## Command-Line Arguments

```text
python run_export.py [OPTIONS] <capture.rdc>
```

| Argument | Description |
|----------|-------------|
| `<capture.rdc>` | Path to the .rdc capture file (required) |
| `--eid <spec>` | EID filter: `-1` (event list only), `1234` (single), `1000-2000` (range) |
| `--no-skip-slateui-title` | Include UE SlateUI Title events (skipped by default) |
| `--renderdoc-path <dir>` | Override renderdoc module search path |

### Key Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `RDC_EXPORT_EID` | Same as `--eid` (CLI overrides) | — |
| `RDC_EXPORT_SKIP_SLATEUI_TITLE` | `0`/`false` to include SlateUI | `true` |
| `RDC_EXPORT_ALL_PSOS` | `1` to export ALL PSOs | `false` |
| `RDC_REPLAY_FORCE_SOFTWARE` | `1` to force WARP | `false` |
| `RDC_WORKER_TIMEOUT_SEC` | Worker timeout (seconds) | `6000` |
| `RDC_WORKER_MAX_WS_GB` | Worker max working set (GB) | `128` |

When `--eid` is active, replay stability flags (`RDC_SETFRAME_FULL_REPLAY`, `RDC_SKIP_QUEUE_SWITCH_IDLE`, `RDC_CMDLIST_RESET_NULL_PSO`, `RDC_SKIP_QUERY_REPLAY`) are auto-set to `1`. Override by setting them explicitly.

## Output Structure

Export produces `<capture_name>/` next to the .rdc file. For detailed format specs, see [references/output-format.md](references/output-format.md).

| Path | Content |
|------|---------|
| `event_list.md` | Frame event hierarchy (start here) |
| `events/EID_*.md` | Per-draw/dispatch: pipeline, shaders, bindings, RT before/after, textures, buffers |
| `pso/*.md` | Pipeline State Object configs |
| `shaders/*.md` | Shader disassembly + resource bindings |
| `buffers/*.md` | CB structured values, VB/IB data, hex dumps |
| `textures/`, `render_targets/` | PNG snapshots (before/after) |

## Diagnosis

For rendering issue diagnosis patterns (black screen, wrong colors, geometry issues, depth/Z-fighting, transparency, compute, performance), see [references/diagnosis-patterns.md](references/diagnosis-patterns.md).

## DISCARD Overlay Handling

**CRITICAL**: RenderDoc fills discarded resource regions with visible 64×8 pixel text overlays during replay. These are NOT actual render content. Before any pixel-level analysis on exported images, detect and exclude DISCARD pixels — otherwise statistics and diffs will be incorrect.

Use the bundled `scripts/image_diff.py` tool (requires system Python 3.6+ and Pillow):

```bash
# Compare two images (DISCARD-aware brightness diff)
python "<skill-path>/scripts/image_diff.py" <a.png> <b.png>

# Single image stats
python "<skill-path>/scripts/image_diff.py" --stats <image.png>

# Save diff heatmap / mask visualization
python "<skill-path>/scripts/image_diff.py" <a.png> <b.png> --save-diff diff.png --save-mask mask.png

# JSON output
python "<skill-path>/scripts/image_diff.py" <a.png> <b.png> --json
```

For DISCARD pattern specifications, detection algorithm, and custom masking code, see [references/discard-patterns.md](references/discard-patterns.md).
