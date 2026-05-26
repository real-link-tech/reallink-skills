#!/usr/bin/env python3
"""Convert Unreal texture streaming pool NDJSON samples to a standalone HTML chart."""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any


DEFAULT_FIELDS = "requiredPoolMB,streamingPoolMB"
DEFAULT_MAX_REASONABLE_MB = 1_000_000.0
FIELD_COLORS = {
    "requiredPoolMB": "#2563eb",
    "streamingPoolMB": "#16a34a",
    "usedStreamingPoolMB": "#7c3aed",
    "overBudgetMB": "#dc2626",
    "wantedMipsMB": "#d97706",
    "cachedMipsMB": "#0891b2",
    "nonStreamingMipsMB": "#64748b",
    "pendingRequestsMB": "#f43f5e",
    "renderAssetPoolMB": "#0f766e",
    "virtualTexturePoolMB": "#15803d",
    "requiredVirtualTexturePoolMB": "#1d4ed8",
    "usedVirtualTexturePoolMB": "#6d28d9",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a standalone HTML curve chart from texture streaming pool NDJSON."
    )
    parser.add_argument("input", help="Path to streaming_pool_report_*.ndjson")
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to the input name with .html extension.",
    )
    parser.add_argument("--title", help="Chart title. Defaults to the report file name.")
    parser.add_argument(
        "--fields",
        default=DEFAULT_FIELDS,
        help=f"Comma-separated sample fields to plot. Default: {DEFAULT_FIELDS}",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=3500,
        help="Maximum chart points after downsampling. Default: 3500",
    )
    parser.add_argument(
        "--max-reasonable-mb",
        type=float,
        default=DEFAULT_MAX_REASONABLE_MB,
        help=(
            "Ignore MB values above this threshold as unlimited/sentinel noise. "
            f"Default: {DEFAULT_MAX_REASONABLE_MB:g}"
        ),
    )
    return parser.parse_args()


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_report(path: Path) -> dict[str, Any]:
    start = None
    stop = None
    summary = None
    samples: list[dict[str, Any]] = []
    skipped = 0

    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON at line {line_number}: {exc}") from exc

            if row.get("t") == "s":
                samples.append(row)
            elif row.get("type") == "start":
                start = row
            elif row.get("type") == "stop":
                stop = row
            elif row.get("type") == "summary":
                summary = row
            else:
                skipped += 1

    if not samples:
        raise SystemExit("No sample rows found. Expected rows with {'t':'s', ...}.")

    return {"start": start, "stop": stop, "summary": summary, "samples": samples, "skipped": skipped}


def downsample(rows: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points <= 0 or len(rows) <= max_points:
        return rows
    step = len(rows) / max_points
    result = []
    previous_index = -1
    for i in range(max_points):
        index = min(int(i * step), len(rows) - 1)
        if index != previous_index:
            result.append(rows[index])
            previous_index = index
    if result and result[-1] is not rows[-1]:
        result.append(rows[-1])
    return result


def parse_fields(value: str, sample: dict[str, Any]) -> list[str]:
    fields = [field.strip() for field in value.split(",") if field.strip()]
    return [field for field in fields if is_number(sample.get(field))]


def reasonable_mb(value: Any, max_reasonable_mb: float) -> bool:
    return is_number(value) and abs(float(value)) <= max_reasonable_mb


def max_for(samples: list[dict[str, Any]], field: str, max_reasonable_mb: float) -> dict[str, Any]:
    best_value = float("-inf")
    best_row: dict[str, Any] | None = None
    for row in samples:
        value = row.get(field)
        if reasonable_mb(value, max_reasonable_mb) and float(value) > best_value:
            best_value = float(value)
            best_row = row
    if best_row is None:
        best_value = float("nan")
    return {"field": field, "value": best_value, "row": best_row}


def clean_samples(
    samples: list[dict[str, Any]],
    fields: list[str],
    max_reasonable_mb: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cleaned = []
    filtered_counts = {field: 0 for field in fields}
    last_streaming_pool_mb: float | None = None

    for row in samples:
        point = dict(row)
        streaming_value = row.get("streamingPoolMB")
        if reasonable_mb(streaming_value, max_reasonable_mb):
            last_streaming_pool_mb = float(streaming_value)
            point["streamingPoolMB"] = last_streaming_pool_mb
        elif is_number(streaming_value):
            filtered_counts["streamingPoolMB"] = filtered_counts.get("streamingPoolMB", 0) + 1
            if last_streaming_pool_mb is not None:
                point["streamingPoolMB"] = last_streaming_pool_mb
            else:
                point.pop("streamingPoolMB", None)

        for field in fields:
            if field == "streamingPoolMB":
                continue
            value = point.get(field)
            if is_number(value) and not reasonable_mb(value, max_reasonable_mb):
                filtered_counts[field] = filtered_counts.get(field, 0) + 1
                point.pop(field, None)

        required = point.get("requiredPoolMB")
        effective_streaming = point.get("streamingPoolMB")
        if is_number(required) and is_number(effective_streaming):
            point["overBudgetMB"] = max(0.0, float(required) - float(effective_streaming))

        cleaned.append(point)

    return cleaned, filtered_counts


def build_payload(report: dict[str, Any], fields: list[str], max_points: int, max_reasonable_mb: float) -> dict[str, Any]:
    all_samples = report["samples"]
    cleaned_all_samples, filtered_counts = clean_samples(all_samples, fields, max_reasonable_mb)
    samples = downsample(cleaned_all_samples, max_points)
    first = cleaned_all_samples[0]
    last = cleaned_all_samples[-1]

    points = []
    for row in samples:
        x = row.get("e", row.get("f"))
        if not is_number(x):
            continue
        point = {"x": float(x), "f": row.get("f")}
        for field in fields:
            value = row.get(field)
            if reasonable_mb(value, max_reasonable_mb):
                point[field] = float(value)
        points.append(point)

    peak_fields = list(dict.fromkeys([*fields, "overBudgetMB"]))
    peaks = {field: max_for(cleaned_all_samples, field, max_reasonable_mb) for field in peak_fields}
    summary = report.get("summary") or {}
    filtered_summary = dict(summary)
    for key in list(filtered_summary):
        if key.startswith("max") and key.endswith("MB") and not reasonable_mb(filtered_summary[key], max_reasonable_mb):
            filtered_summary[key] = None
    if "streamingPoolMB" in fields:
        filtered_summary["maxStreamingPoolMB"] = peaks.get("streamingPoolMB", {}).get("value")
    filtered_summary["maxOverBudgetMB"] = peaks.get("overBudgetMB", {}).get("value")
    return {
        "start": report.get("start"),
        "stop": report.get("stop"),
        "summary": summary,
        "filteredSummary": filtered_summary,
        "maxReasonableMB": max_reasonable_mb,
        "filteredCounts": filtered_counts,
        "sampleCount": len(all_samples),
        "shownSampleCount": len(samples),
        "durationSeconds": float(last.get("e", 0)) - float(first.get("e", 0)) if is_number(last.get("e")) and is_number(first.get("e")) else None,
        "frameStart": first.get("f"),
        "frameEnd": last.get("f"),
        "fields": [{"name": field, "color": FIELD_COLORS.get(field, "#111827")} for field in fields],
        "points": points,
        "peaks": peaks,
    }


def render_html(title: str, source: Path, payload: dict[str, Any]) -> str:
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_title = html.escape(title)
    safe_source = html.escape(str(source))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: light; --border:#d7dce5; --text:#1f2937; --muted:#64748b; --panel:#f8fafc; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family:"Segoe UI",Arial,sans-serif; color:var(--text); background:#fff; }}
header {{ padding:18px 24px 12px; border-bottom:1px solid var(--border); background:#fff; }}
h1 {{ margin:0 0 6px; font-size:22px; font-weight:650; letter-spacing:0; }}
.source {{ color:var(--muted); font-size:13px; overflow-wrap:anywhere; }}
main {{ padding:18px 24px 28px; }}
.metrics {{ display:grid; grid-template-columns:repeat(5,minmax(150px,1fr)); gap:10px; margin-bottom:16px; }}
.metric {{ border:1px solid var(--border); border-radius:8px; padding:10px 12px; background:var(--panel); }}
.metric .label {{ color:var(--muted); font-size:12px; }}
.metric .value {{ margin-top:5px; font-size:21px; font-weight:700; }}
.panel {{ border:1px solid var(--border); border-radius:8px; padding:14px; margin-bottom:16px; }}
.panel-title {{ display:flex; justify-content:space-between; gap:12px; margin-bottom:8px; font-weight:650; }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px 14px; color:var(--muted); font-size:12px; }}
.legend span {{ display:inline-flex; align-items:center; gap:5px; }}
.swatch {{ width:18px; height:3px; border-radius:2px; display:inline-block; }}
canvas {{ display:block; width:100%; height:520px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ text-align:right; padding:7px 9px; border-bottom:1px solid var(--border); white-space:nowrap; }}
th:first-child,td:first-child {{ text-align:left; }}
th {{ color:var(--muted); font-weight:650; }}
@media (max-width:900px) {{ main,header {{ padding-left:14px; padding-right:14px; }} .metrics {{ grid-template-columns:repeat(2,minmax(140px,1fr)); }} canvas {{ height:360px; }} }}
</style>
</head>
<body>
<header>
  <h1>{safe_title}</h1>
  <div class="source">{safe_source}</div>
</header>
<main>
  <section class="metrics" id="metrics"></section>
  <section class="panel">
    <div class="panel-title">
      <span>Streaming Pool Curves</span>
      <div class="legend" id="legend"></div>
    </div>
    <canvas id="chart"></canvas>
  </section>
  <section class="panel">
    <div class="panel-title">Peaks</div>
    <table>
      <thead><tr><th>Field</th><th>Max MB</th><th>Time s</th><th>Frame</th></tr></thead>
      <tbody id="peaks"></tbody>
    </table>
  </section>
</main>
<script>
const data = {data_json};
const fmt = value => Number.isFinite(value) ? value.toLocaleString(undefined, {{maximumFractionDigits:3}}) : "-";

function metricCards() {{
  const summary = data.filteredSummary || data.summary || {{}};
  const required = summary.maxRequiredPoolMB ?? data.peaks.requiredPoolMB?.value;
  const streaming = summary.maxStreamingPoolMB ?? data.peaks.streamingPoolMB?.value;
  const over = summary.maxOverBudgetMB ?? data.peaks.overBudgetMB?.value;
  const recommended = summary.recommendedEffectiveStreamingPoolMB_RequiredX1_3 ?? (Number.isFinite(required) ? Math.ceil(required * 1.3) : NaN);
  const occupancy = streaming > 0 && required >= 0 ? required / streaming * 100 : NaN;
  const cards = [
    ["Max Required", `${{fmt(required)}} MB`],
    ["Max Streaming Pool", `${{fmt(streaming)}} MB`],
    ["Required / Pool", `${{fmt(occupancy)}}%`],
    ["Max OverBudget", `${{fmt(over)}} MB`],
    ["Required * 1.3", `${{fmt(recommended)}} MB`],
  ];
  document.getElementById("metrics").innerHTML = cards.map(([label,value]) => `<div class="metric"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`).join("");
}}

function draw() {{
  const canvas = document.getElementById("chart");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const pad = {{l:64,r:18,t:16,b:36}};
  const w = rect.width - pad.l - pad.r;
  const h = rect.height - pad.t - pad.b;
  const points = data.points || [];
  if (points.length < 2) return;
  const minX = points[0].x;
  const maxX = points[points.length - 1].x;
  let maxY = 1;
  for (const field of data.fields) {{
    for (const point of points) {{
      const value = point[field.name];
      if (Number.isFinite(value)) maxY = Math.max(maxY, value);
    }}
  }}
  maxY *= 1.12;
  const x = point => pad.l + (point.x - minX) / Math.max(maxX - minX, .001) * w;
  const y = value => pad.t + h - value / maxY * h;
  ctx.strokeStyle = "#d7dce5";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#64748b";
  ctx.font = "12px Segoe UI, Arial";
  for (let i = 0; i <= 5; i++) {{
    const gy = pad.t + h * i / 5;
    const value = maxY * (1 - i / 5);
    ctx.beginPath();
    ctx.moveTo(pad.l, gy);
    ctx.lineTo(pad.l + w, gy);
    ctx.stroke();
    ctx.fillText(fmt(value), 8, gy + 4);
  }}
  for (let i = 0; i <= 6; i++) {{
    const gx = pad.l + w * i / 6;
    const value = minX + (maxX - minX) * i / 6;
    ctx.fillText(`${{fmt(value)}}s`, gx - 16, pad.t + h + 24);
  }}
  for (const field of data.fields) {{
    ctx.strokeStyle = field.color;
    ctx.lineWidth = field.name === "streamingPoolMB" ? 2.2 : 1.8;
    ctx.beginPath();
    let started = false;
    for (const point of points) {{
      const value = point[field.name];
      if (!Number.isFinite(value)) continue;
      if (!started) {{
        ctx.moveTo(x(point), y(value));
        started = true;
      }} else {{
        ctx.lineTo(x(point), y(value));
      }}
    }}
    ctx.stroke();
  }}
  ctx.strokeStyle = "#1f2937";
  ctx.strokeRect(pad.l, pad.t, w, h);
}}

function legend() {{
  document.getElementById("legend").innerHTML = data.fields.map(field => {{
    const filtered = data.filteredCounts?.[field.name] || 0;
    const suffix = filtered ? ` (${{filtered}} filtered)` : "";
    return `<span><i class="swatch" style="background:${{field.color}}"></i>${{field.name}}${{suffix}}</span>`;
  }}).join("");
}}

function peaks() {{
  document.getElementById("peaks").innerHTML = data.fields.map(field => {{
    const peak = data.peaks[field.name] || {{}};
    const row = peak.row || {{}};
    return `<tr><td>${{field.name}}</td><td>${{fmt(peak.value)}}</td><td>${{fmt(row.e)}}</td><td>${{row.f ?? "-"}}</td></tr>`;
  }}).join("");
}}

metricCards();
legend();
peaks();
draw();
window.addEventListener("resize", draw);
</script>
</body>
</html>
"""


def print_summary(payload: dict[str, Any]) -> None:
    summary = payload.get("filteredSummary") or payload.get("summary") or {}
    peaks = payload.get("peaks") or {}
    required = summary.get("maxRequiredPoolMB")
    if required is None:
        required = peaks.get("requiredPoolMB", {}).get("value")
    streaming = summary.get("maxStreamingPoolMB")
    if streaming is None:
        streaming = peaks.get("streamingPoolMB", {}).get("value")
    over = summary.get("maxOverBudgetMB")
    if over is None:
        over = peaks.get("overBudgetMB", {}).get("value")
    recommended = summary.get("recommendedEffectiveStreamingPoolMB_RequiredX1_3")
    if recommended is None and is_number(required):
        recommended = math.ceil(float(required) * 1.3)
    print(f"samples={payload['sampleCount']} shown={payload['shownSampleCount']}")
    print(f"maxRequiredPoolMB={required}")
    print(f"maxStreamingPoolMB={streaming}")
    print(f"maxOverBudgetMB={over}")
    print(f"recommendedEffectiveStreamingPoolMB_RequiredX1_3={recommended}")
    filtered_counts = payload.get("filteredCounts") or {}
    filtered_total = sum(int(value) for value in filtered_counts.values())
    if filtered_total:
        print(f"filteredOutlierValues={filtered_counts}")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(".html")
    report = load_report(input_path)
    fields = parse_fields(args.fields, report["samples"][0])
    if not fields:
        raise SystemExit("None of the requested fields exist as numeric sample values.")
    payload = build_payload(report, fields, args.max_points, args.max_reasonable_mb)
    title = args.title or input_path.name
    output_path.write_text(render_html(title, input_path, payload), encoding="utf-8")
    print(f"wrote={output_path}")
    print_summary(payload)


if __name__ == "__main__":
    main()
