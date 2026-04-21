---
name: ue-trace-analysis
description: Analyze Unreal Engine `.utrace` files and turn them into actionable hotspot summaries. Use when Codex needs to inspect Unreal trace captures, summarize GPU frame cost, identify worst frames, compare trace files, or explain what a `.utrace` capture is showing. Trigger on requests about `.utrace`, Unreal Insights trace analysis, GPU frame spikes, hotspot breakdowns, or extending the bundled parser for deeper event inspection.
---

# UE Trace Analysis

Use the bundled script for the first pass. It gives a deterministic summary of GPU timelines and keeps the reasoning grounded in parsed trace data instead of guesses.

## Quick Start

1. Confirm the user provided a `.utrace` file path.
2. Run `scripts/analyze_utrace.py <trace_path>`.
3. If the user wants structured output, add `--json-out <path>`.
4. Summarize `avg_ms`, `p95_ms`, `max_ms`, `worst_frame`, `top_inclusive`, and `top_exclusive`.

Example:

```powershell
python scripts/analyze_utrace.py C:\path\to\capture.utrace --json-out C:\path\to\summary.json
```

## Workflow

### 1. Resolve the decoder DLL

The parser needs `UnrealInsights-TraceLog.dll`.

Use one of these paths:

- Pass `--decoder-dll <path>`
- Set `UE_TRACE_LOG_DLL`
- Rely on common UE install paths already checked by the script

If the DLL cannot be found, stop and report that clearly instead of inventing a trace summary.

### 2. Run the parser first

Prefer the script in `scripts/analyze_utrace.py` over ad hoc parsing. It already handles:

- transport packet demux
- trace event type registration
- important stream parsing
- `GpuProfiler.Frame` and `GpuProfiler.Frame2`
- inclusive and exclusive hotspot aggregation

By default the script creates a deterministic demux folder next to the trace file so it also works in workspace-restricted sandboxes. If you need to keep intermediate thread bins for debugging, add `--keep-demux`. If you want them under a known folder, also add `--work-dir <dir>`.

### 3. Interpret the results

Use this reading order:

1. `trace.packet_count`, `decoded_size_bytes`, and `thread_count` for capture scale
2. `gpu.*.avg_ms`, `median_ms`, `p95_ms`, and `max_ms` for distribution
3. `gpu.*.worst_frame` for the concrete spike
4. `top_inclusive` and `top_exclusive` for hotspot attribution

When comparing multiple traces, run the script once per file and compare the same timeline fields across outputs instead of mixing values from different timeline names.

### 4. Stay within the tool's current scope

The bundled parser currently gives the strongest coverage for GPU-frame summaries. Do not claim CPU, networking, object replication, or gameplay conclusions unless you extended the parser and verified them from parsed events.

If the user asks for deeper inspection, extend the parser in `scripts/` and consult the copied C# reference implementation under `references/trace-csharp-src/`.

## References

- Read [usage-notes.md](./references/usage-notes.md) for CLI patterns, output semantics, and extension guidance.
- Read files under `references/trace-csharp-src/` only when you need low-level format details or want to add new event parsing behavior.

## Output Expectations

A good answer should usually include:

- which trace file was analyzed
- which GPU timeline had data
- average, p95, and worst-frame cost
- the top few inclusive hotspots
- the top few exclusive hotspots
- any limitation that affects confidence

Keep the answer grounded in the parsed fields. If the script fails, explain the failure and the next concrete unblock step.
