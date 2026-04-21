# Usage Notes

## What the script does

`scripts/analyze_utrace.py` parses Unreal `.utrace` files by:

1. reading the transport header
2. demuxing packets into per-thread binary streams
3. rebuilding runtime event type metadata from the important streams
4. decoding `GpuProfiler.Frame` and `GpuProfiler.Frame2`
5. aggregating inclusive and exclusive time per GPU event name

The output is a summary dictionary with:

- `trace`: capture metadata, decoder path, packet counts, and optional demux directory
- `thread_names`: thread id to name mapping from `$Trace.ThreadInfo`
- `event_types`: reconstructed event type names
- `important_counts`: counts from the important stream
- `event_counts`: parsed non-important event counts
- `gpu`: per-timeline frame stats and hotspot summaries

## Common commands

Print a text summary:

```powershell
python scripts/analyze_utrace.py C:\path\to\capture.utrace
```

If you do not pass `--work-dir`, the script creates a deterministic demux folder under the trace file's directory and removes it after analysis unless `--keep-demux` is set.

Write JSON for later comparison:

```powershell
python scripts/analyze_utrace.py C:\path\to\capture.utrace --json-out C:\path\to\summary.json
```

Use a specific decoder DLL:

```powershell
python scripts/analyze_utrace.py C:\path\to\capture.utrace --decoder-dll C:\UE\Engine\Binaries\Win64\UnrealInsights-TraceLog.dll
```

Keep demux output for debugging:

```powershell
python scripts/analyze_utrace.py C:\path\to\capture.utrace --keep-demux --work-dir C:\temp\trace-debug
```

## How to read the summary

Use `avg_ms` and `median_ms` for the general frame level, `p95_ms` for recurring spikes, and `max_ms` plus `worst_frame` for the single worst case.

Use `top_inclusive` to find expensive branches and `top_exclusive` to find work that is expensive even after subtracting child cost.

If `frame_count` is zero for a timeline, do not infer anything from that timeline.

## Extension guidance

If you need to parse more event families:

1. inspect `event_counts` to confirm the target events actually exist
2. inspect the copied files in `trace-csharp-src/`
3. add explicit parsing logic to `scripts/analyze_utrace.py`
4. rerun against a real trace before trusting the new summary

The copied C# files are reference material only. The reusable execution path for this skill is the Python script.
