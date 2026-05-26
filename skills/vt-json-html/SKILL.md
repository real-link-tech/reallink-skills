---
name: vt-json-html
description: Read Unreal Engine virtual texture NDJSON reports with pool_meta and per-frame sample rows, then generate standalone HTML per-pool curve charts where green shows pool size and yellow shows visible usage matching the in-game VisiblePool HUD.
---

# VT JSON HTML

Use this skill when the user asks to read VT/virtual texture JSON or NDJSON reports like `vt_report_*.ndjson` and turn them into HTML curve charts.

The default output is one chart per pool:

- Green line: pool size in MB, from `pool_meta.capacityMB`.
- Yellow line: visible usage in MB, default metric `vp * pool_meta.tileSizeBytes / 1024 / 1024`, matching the in-game `VisiblePool` HUD.

## Workflow

1. Locate the input report. Prefer a user-provided path; otherwise search for `vt_report_*.ndjson`.
2. Generate the chart with the bundled script:

```powershell
python .\scripts\vt_json_to_html.py "path\to\vt_report.ndjson"
```

3. If the script is run from outside the skill folder, use the absolute script path:

```powershell
python "D:\UnrealEngine\.codex\skills\vt-json-html\scripts\vt_json_to_html.py" "path\to\vt_report.ndjson"
```

4. Give the user the generated `.html` path. The HTML is self-contained and can be opened directly in a browser.

## Useful Options

```powershell
python .\scripts\vt_json_to_html.py "report.ndjson" --output "report.html"
python .\scripts\vt_json_to_html.py "report.ndjson" --needed-metric vp
python .\scripts\vt_json_to_html.py "report.ndjson" --needed-metric apr
python .\scripts\vt_json_to_html.py "report.ndjson" --title "B02 VT Pool Usage"
```

## Data Notes

- Input is newline-delimited JSON, one object per line.
- `{"type":"pool_meta", ...}` rows describe pools.
- `{"t":"s", ...}` rows are samples. `id` maps to `pool_meta.poolId`.
- The x-axis uses elapsed seconds `e` when available, falling back to frame `f`.
- Default chart lines are `pool_meta.capacityMB` for pool size and `vp` converted to MB for visible usage.
- Use `--needed-metric apr` when you intentionally want allocated pages instead of the in-game visible residency number.

Read `references/schema.md` only when field meaning or parsing details are needed.
