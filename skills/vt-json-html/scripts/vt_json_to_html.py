#!/usr/bin/env python3
"""Convert Unreal virtual texture NDJSON samples to standalone per-pool HTML charts."""

from __future__ import annotations

import argparse
import html
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


CAPACITY_COLOR = "#16a34a"
NEEDED_COLOR = "#eab308"
BYTES_PER_MIB = 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate standalone HTML per-pool curves from VT NDJSON."
    )
    parser.add_argument("input", help="Path to vt_report_*.ndjson")
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to the input name with .html extension.",
    )
    parser.add_argument("--title", help="Chart title. Defaults to the report file name.")
    parser.add_argument(
        "--needed-metric",
        default="vp",
        help="Tile-count metric for the yellow line. It is converted to MB. Default: vp, matching the in-game VisiblePool HUD.",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=2500,
        help="Maximum points per pool line after downsampling. Default: 2500",
    )
    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    pools: dict[int, dict[str, Any]] = {}
    samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    run: dict[str, Any] = {}
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

            row_type = row.get("type")
            if row_type == "pool_meta":
                pool_id = row.get("poolId")
                if isinstance(pool_id, int):
                    pools[pool_id] = row
                continue

            if row_type in {"start", "stop"}:
                run[row_type] = row
                continue

            if row.get("t") == "s" and isinstance(row.get("id"), int):
                samples[row["id"]].append(row)
                continue

            skipped += 1

    return {"pools": pools, "samples": samples, "run": run, "skipped": skipped}


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def downsample(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points <= 0 or len(points) <= max_points:
        return points
    step = len(points) / max_points
    result = []
    previous_index = -1
    for i in range(max_points):
        index = min(int(i * step), len(points) - 1)
        if index != previous_index:
            result.append(points[index])
            previous_index = index
    if result and result[-1] is not points[-1]:
        result.append(points[-1])
    return result


def pool_label(pool_id: int, meta: dict[str, Any] | None) -> str:
    if not meta:
        return f"Pool {pool_id}"
    fmt = meta.get("format") or "Unknown"
    tile = meta.get("tileSize")
    layers = meta.get("numLayers")
    capacity = meta.get("capacityMB")
    suffix = []
    if tile is not None:
        suffix.append(f"Tile={tile}")
    if layers is not None:
        suffix.append(f"Layers={layers}")
    if is_number(capacity):
        suffix.append(f"{capacity:.1f} MB")
    detail = ", ".join(suffix)
    return f"Pool {pool_id} - {fmt}" + (f" ({detail})" if detail else "")


def collect_points(rows: list[dict[str, Any]], metric: str, scale: float = 1.0) -> list[dict[str, float]]:
    points = []
    for row in rows:
        x = row.get("e", row.get("f"))
        y = row.get(metric)
        if is_number(x) and is_number(y):
            points.append({"x": float(x), "y": float(y) * scale})
    return points


def capacity_points(rows: list[dict[str, Any]], capacity_mb: Any) -> list[dict[str, float]]:
    if not is_number(capacity_mb):
        return []
    points = []
    for row in rows:
        x = row.get("e", row.get("f"))
        if is_number(x):
            points.append({"x": float(x), "y": float(capacity_mb)})
    return points


def build_chart_data(report: dict[str, Any], needed_metric: str, max_points: int) -> dict[str, Any]:
    pools = report["pools"]
    charts = []
    archived_pools = []

    for pool_id in sorted(report["samples"]):
        all_rows = report["samples"][pool_id]
        rows = downsample(all_rows, max_points)
        meta = pools.get(pool_id)
        capacity = meta.get("capacityMB") if meta else None
        tile_size_bytes = meta.get("tileSizeBytes") if meta else None
        needed_scale = float(tile_size_bytes) / BYTES_PER_MIB if is_number(tile_size_bytes) else 1.0
        capacity_line = capacity_points(rows, capacity)
        needed = collect_points(rows, needed_metric, needed_scale)
        if not capacity_line and not needed:
            continue
        if len(all_rows) < 2:
            first = all_rows[0] if all_rows else {}
            visible_value = first.get(needed_metric)
            visible_mb = (
                float(visible_value) * needed_scale
                if is_number(visible_value)
                else None
            )
            archived_pools.append(
                {
                    "poolId": pool_id,
                    "label": pool_label(pool_id, meta),
                    "poolKey": meta.get("poolKey") if meta else "",
                    "capacityMB": meta.get("capacityMB") if meta else None,
                    "sampleFrame": first.get("f"),
                    "sampleTime": first.get("e"),
                    "visibleMB": visible_mb,
                    "reason": "single sample; likely released or replaced during capture",
                }
            )
            continue
        charts.append(
            {
                "poolId": pool_id,
                "label": pool_label(pool_id, meta),
                "poolKey": meta.get("poolKey") if meta else "",
                "capacityMB": meta.get("capacityMB") if meta else None,
                "samples": len(all_rows),
                "shownSamples": len(rows),
                "lines": [
                    {
                        "name": "Needed",
                        "metric": needed_metric,
                        "unit": "MB",
                        "color": NEEDED_COLOR,
                        "points": needed,
                    },
                    {
                        "name": "Pool Size",
                        "metric": "capacityMB",
                        "unit": "MB",
                        "color": CAPACITY_COLOR,
                        "points": capacity_line,
                    },
                ],
            }
        )

    return {
        "charts": charts,
        "archivedPools": archived_pools,
        "capacityMetric": "capacityMB",
        "neededMetric": needed_metric,
        "unit": "MB",
        "run": report["run"],
        "skipped": report["skipped"],
    }


def render_html(title: str, source: Path, chart_data: dict[str, Any]) -> str:
    payload = json.dumps(chart_data, ensure_ascii=False, separators=(",", ":"))
    safe_title = html.escape(title)
    safe_source = html.escape(str(source))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: light; --border:#d7dce5; --text:#1f2937; --muted:#64748b; --panel:#f8fafc; --capacity:{CAPACITY_COLOR}; --needed:{NEEDED_COLOR}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: var(--text); background: #ffffff; }}
header {{ position: sticky; top: 0; z-index: 2; padding: 16px 24px 10px; border-bottom: 1px solid var(--border); background: rgba(255,255,255,.96); }}
h1 {{ margin: 0 0 6px; font-size: 22px; font-weight: 650; letter-spacing: 0; }}
.source {{ color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }}
main {{ display: grid; grid-template-columns: 280px minmax(0, 1fr); min-height: calc(100vh - 70px); }}
aside {{ position: sticky; top: 70px; height: calc(100vh - 70px); border-right: 1px solid var(--border); padding: 14px; background: var(--panel); overflow: auto; }}
.legend {{ display: grid; gap: 8px; margin-bottom: 16px; font-size: 13px; }}
.legend-row {{ display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; gap: 8px; }}
.legend-name {{ min-width: 0; font-weight: 600; }}
.legend-meta {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
.swatch {{ width: 22px; height: 3px; border-radius: 999px; flex: 0 0 auto; }}
.section-title {{ margin: 14px 0 8px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
.pool-link {{ display: block; padding: 7px 8px; border-radius: 6px; color: var(--text); text-decoration: none; font-size: 13px; line-height: 1.25; }}
.pool-link:hover {{ background: #fff; outline: 1px solid var(--border); }}
.charts {{ display: grid; gap: 18px; padding: 18px; }}
.chart-card {{ border: 1px solid var(--border); border-radius: 8px; background: #fff; overflow: hidden; }}
.chart-head {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 12px 14px; border-bottom: 1px solid var(--border); }}
.chart-title {{ margin: 0 0 4px; font-size: 15px; font-weight: 650; }}
.meta {{ color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }}
.counts {{ text-align: right; color: var(--muted); font-size: 12px; white-space: nowrap; }}
.canvas-wrap {{ position: relative; height: 260px; padding: 10px 12px 12px; }}
canvas {{ width: 100%; height: 100%; display: block; }}
.archive {{ border: 1px solid var(--border); border-radius: 8px; background: #fff; overflow: hidden; }}
.archive-head {{ padding: 12px 14px; border-bottom: 1px solid var(--border); }}
.archive-title {{ margin: 0 0 4px; font-size: 15px; font-weight: 650; }}
.archive-list {{ display: grid; gap: 0; }}
.archive-row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; padding: 10px 14px; border-top: 1px solid #eef2f7; }}
.archive-row:first-child {{ border-top: 0; }}
.archive-stats {{ color: var(--muted); font-size: 12px; text-align: right; white-space: nowrap; }}
.tooltip {{ position: fixed; pointer-events: none; display: none; padding: 7px 9px; background: rgba(15, 23, 42, .92); color: white; border-radius: 6px; font-size: 12px; max-width: 360px; z-index: 4; }}
.empty {{ padding: 24px; color: var(--muted); }}
@media (max-width: 860px) {{
  main {{ grid-template-columns: 1fr; }}
  aside {{ position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }}
  .charts {{ padding: 12px; }}
  .chart-head {{ grid-template-columns: 1fr; }}
  .counts {{ text-align: left; }}
}}
</style>
</head>
<body>
<header>
  <h1>{safe_title}</h1>
  <div class="source">{safe_source}</div>
</header>
<main>
  <aside>
    <div class="legend">
      <div class="legend-row"><span class="swatch" style="background:var(--capacity)"></span><span class="legend-name">Pool Size / 池大小</span><span class="legend-meta" id="capacityMetric"></span></div>
      <div class="legend-row"><span class="swatch" style="background:var(--needed)"></span><span class="legend-name">Visible / 当前可见</span><span class="legend-meta" id="neededMetric"></span></div>
    </div>
    <div class="section-title">Pools</div>
    <nav id="poolNav"></nav>
    <div class="section-title">Archived</div>
    <nav id="archiveNav"></nav>
  </aside>
  <section id="charts" class="charts"></section>
</main>
<div id="tooltip" class="tooltip"></div>
<script>
const chartData = {payload};
const chartsEl = document.getElementById('charts');
const poolNav = document.getElementById('poolNav');
const archiveNav = document.getElementById('archiveNav');
const tooltip = document.getElementById('tooltip');
document.getElementById('capacityMetric').textContent = `${{chartData.capacityMetric}} / MB`;
document.getElementById('neededMetric').textContent = `${{chartData.neededMetric}} / MB`;

function escapeHtml(value) {{
  return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}

function formatNumber(value) {{
  if (Math.abs(value) >= 1000) return Math.round(value).toLocaleString();
  if (Math.abs(value) >= 10) return value.toFixed(1).replace(/\\.0$/, '');
  return value.toFixed(2).replace(/0+$/, '').replace(/\\.$/, '');
}}

function bounds(chart) {{
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const line of chart.lines) {{
    for (const p of line.points) {{
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    }}
  }}
  if (!Number.isFinite(minX)) return {{minX: 0, maxX: 1, minY: 0, maxY: 1}};
  if (minX === maxX) maxX = minX + 1;
  maxY = Math.max(1, maxY);
  return {{minX, maxX, minY: 0, maxY: maxY * 1.08}};
}}

function plotArea(rect) {{
  return {{left: 58, top: 12, right: rect.width - 14, bottom: rect.height - 34}};
}}

function drawChart(canvas, chart) {{
  const ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const b = bounds(chart);
  const a = plotArea(rect);
  const width = Math.max(1, a.right - a.left);
  const height = Math.max(1, a.bottom - a.top);
  const sx = x => a.left + ((x - b.minX) / (b.maxX - b.minX)) * width;
  const sy = y => a.bottom - ((y - b.minY) / (b.maxY - b.minY)) * height;

  ctx.strokeStyle = '#d7dce5';
  ctx.lineWidth = 1;
  ctx.strokeRect(a.left, a.top, width, height);
  ctx.font = '12px Segoe UI, Arial, sans-serif';
  ctx.fillStyle = '#64748b';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {{
    const y = b.minY + ((b.maxY - b.minY) * i / 4);
    const py = sy(y);
    ctx.strokeStyle = '#eef2f7';
    ctx.beginPath(); ctx.moveTo(a.left, py); ctx.lineTo(a.right, py); ctx.stroke();
    ctx.fillText(formatNumber(y), a.left - 8, py);
  }}
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let i = 0; i <= 5; i++) {{
    const x = b.minX + ((b.maxX - b.minX) * i / 5);
    ctx.fillText(formatNumber(x), sx(x), a.bottom + 9);
  }}

  for (const line of chart.lines) {{
    if (!line.points.length) continue;
    ctx.strokeStyle = line.color;
    ctx.lineWidth = line.dash ? 2.5 : 2;
    ctx.setLineDash(line.dash || []);
    ctx.beginPath();
    line.points.forEach((p, index) => {{
      const x = sx(p.x), y = sy(p.y);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }});
    ctx.stroke();
  }}
  ctx.setLineDash([]);
}}

function nearestPoint(canvas, chart, clientX, clientY) {{
  const rect = canvas.getBoundingClientRect();
  const localX = clientX - rect.left;
  const localY = clientY - rect.top;
  const b = bounds(chart);
  const a = plotArea(rect);
  const sx = x => a.left + ((x - b.minX) / (b.maxX - b.minX)) * (a.right - a.left);
  const sy = y => a.bottom - ((y - b.minY) / (b.maxY - b.minY)) * (a.bottom - a.top);
  let best = null;
  for (const line of chart.lines) {{
    for (const p of line.points) {{
      const dx = sx(p.x) - localX;
      const dy = sy(p.y) - localY;
      const dist = dx * dx + dy * dy;
      if (dist < 144 && (!best || dist < best.dist)) best = {{line, point: p, dist}};
    }}
  }}
  return best;
}}

function render() {{
  chartsEl.innerHTML = '';
  poolNav.innerHTML = '';
  archiveNav.innerHTML = '';
  if (!chartData.charts.length) {{
    chartsEl.innerHTML = '<div class="empty">No pool has enough samples to draw a curve.</div>';
  }}
  for (const chart of chartData.charts) {{
    const id = `pool-${{chart.poolId}}`;
    const link = document.createElement('a');
    link.className = 'pool-link';
    link.href = `#${{id}}`;
    link.textContent = chart.label;
    poolNav.append(link);

    const card = document.createElement('article');
    card.className = 'chart-card';
    card.id = id;
    card.innerHTML = `
      <div class="chart-head">
        <div>
          <h2 class="chart-title">${{escapeHtml(chart.label)}}</h2>
          <div class="meta">${{escapeHtml(chart.poolKey)}}</div>
        </div>
        <div class="counts">samples: ${{chart.samples.toLocaleString()}}<br>shown: ${{chart.shownSamples.toLocaleString()}}</div>
      </div>
      <div class="canvas-wrap"><canvas></canvas></div>`;
    const canvas = card.querySelector('canvas');
    canvas.addEventListener('mousemove', event => {{
      const hit = nearestPoint(canvas, chart, event.clientX, event.clientY);
      if (!hit) {{
        tooltip.style.display = 'none';
        return;
      }}
      tooltip.style.display = 'block';
      tooltip.style.left = `${{event.clientX + 12}}px`;
      tooltip.style.top = `${{event.clientY + 12}}px`;
      tooltip.innerHTML = `${{escapeHtml(hit.line.name)}} (${{escapeHtml(hit.line.metric)}})<br>x: ${{formatNumber(hit.point.x)}}<br>y: ${{formatNumber(hit.point.y)}} MB`;
    }});
    canvas.addEventListener('mouseleave', () => {{ tooltip.style.display = 'none'; }});
    chartsEl.append(card);
    drawChart(canvas, chart);
  }}

  for (const pool of chartData.archivedPools || []) {{
    const link = document.createElement('a');
    link.className = 'pool-link';
    link.href = '#archived-pools';
    link.textContent = pool.label;
    archiveNav.append(link);
  }}

  if ((chartData.archivedPools || []).length) {{
    const archive = document.createElement('section');
    archive.className = 'archive';
    archive.id = 'archived-pools';
    const rows = chartData.archivedPools.map(pool => `
      <div class="archive-row">
        <div>
          <div class="chart-title">${{escapeHtml(pool.label)}}</div>
          <div class="meta">${{escapeHtml(pool.poolKey)}}</div>
          <div class="meta">${{escapeHtml(pool.reason)}}</div>
        </div>
        <div class="archive-stats">
          frame: ${{pool.sampleFrame ?? '-'}}<br>
          time: ${{pool.sampleTime != null ? formatNumber(pool.sampleTime) : '-'}}s<br>
          visible: ${{pool.visibleMB != null ? formatNumber(pool.visibleMB) : '-'}} MB
        </div>
      </div>`).join('');
    archive.innerHTML = `
      <div class="archive-head">
        <h2 class="archive-title">Archived Single-Sample Pools</h2>
        <div class="meta">These pools are kept for bookkeeping but omitted from curve charts because they cannot form a line.</div>
      </div>
      <div class="archive-list">${{rows}}</div>`;
    chartsEl.append(archive);
  }}
}}

window.addEventListener('resize', () => {{
  document.querySelectorAll('.chart-card').forEach((card, index) => {{
    drawChart(card.querySelector('canvas'), chartData.charts[index]);
  }});
}});
render();
</script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    output_path = Path(args.output).expanduser().resolve() if args.output else input_path.with_suffix(".html")
    report = load_report(input_path)
    chart_data = build_chart_data(report, args.needed_metric, args.max_points)
    title = args.title or input_path.stem
    output_path.write_text(render_html(title, input_path, chart_data), encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Charts: {len(chart_data['charts'])}; capacity: capacityMB; needed: {args.needed_metric} converted to MB")


if __name__ == "__main__":
    main()
