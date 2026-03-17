#!/usr/bin/env python3
"""Generate a side-by-side LLM comparison HTML from two parsed memreport LLM JSONs.

Usage:
    python render_comparison.py <older_llm.json> <newer_llm.json> -o comparison.html [--lang zh|en]

Inputs are the *_llm.json files produced by parse_memreport.py.
"""

import json
import sys
import argparse
from pathlib import Path

# ──────────────────────────────────────────────
# Localisation
# ──────────────────────────────────────────────
LABELS = {
    "zh": {
        "title": "LLM 内存对比报告",
        "overview": "总览",
        "budget": "预算达标",
        "movers": "变化排行",
        "movers_threshold": "|delta| ≥ 5 MB",
        "llm_detail": "LLM Full 标签明细",
        "tex_section": "贴图分组对比 (NeverStream / Streaming)",
        "obj_section": "Obj List 资源类对比 (ResExcKB)",
        "rhi_section": "RHI 分类对比",
        "tag": "标签",
        "change": "变化",
        "change_pct": "变化 %",
        "check": "检查项",
        "threshold": "阈值",
        "group": "分组",
        "class": "Class",
        "count": "Count",
        "res_exc": "ResExc",
        "rhi_cat": "RHI 类别",
        "boot": "启动",
        "scene": "场景",
        "current_target": "当前 Test 等效 目标",
        "peak_safe": "峰值 Test 等效 安全线",
        "peak_crash": "峰值 崩溃阈值",
        "os_phys_cur": "OS 物理内存 (当前)",
        "os_phys_peak": "OS 物理内存 (峰值)",
        "test_eq_cur": "Test 等效 (当前)",
        "test_eq_peak": "Test 等效 (峰值)",
        "ns_total": "NeverStream 总计",
        "st_total": "Streaming 总计",
    },
    "en": {
        "title": "LLM Memory Comparison Report",
        "overview": "Overview",
        "budget": "Budget Status",
        "movers": "Top Movers",
        "movers_threshold": "|delta| ≥ 5 MB",
        "llm_detail": "LLM Full Tag Details",
        "tex_section": "Texture Group Comparison (NeverStream / Streaming)",
        "obj_section": "Obj List Class Comparison (ResExcKB)",
        "rhi_section": "RHI Category Comparison",
        "tag": "Tag",
        "change": "Delta",
        "change_pct": "Delta %",
        "check": "Check",
        "threshold": "Threshold",
        "group": "Group",
        "class": "Class",
        "count": "Count",
        "res_exc": "ResExc",
        "rhi_cat": "RHI Category",
        "boot": "boot",
        "scene": "Scene",
        "current_target": "Current Test-equiv Target",
        "peak_safe": "Peak Test-equiv Safe Line",
        "peak_crash": "Peak Crash Threshold",
        "os_phys_cur": "OS Physical (Current)",
        "os_phys_peak": "OS Physical (Peak)",
        "test_eq_cur": "Test Equiv (Current)",
        "test_eq_peak": "Test Equiv (Peak)",
        "ns_total": "NeverStream Total",
        "st_total": "Streaming Total",
    },
}

# ──────────────────────────────────────────────
# Tag hierarchy for grouped display
# ──────────────────────────────────────────────
HIERARCHY = {
    "Textures": ["VirtualTextureSystem", "TextureMetaData", "Render Targets"],
    "Meshes": ["StaticMesh", "SkeletalMesh", "InstancedMesh"],
    "Physics": [
        "ChaosBody", "ChaosActor", "ChaosUpdate", "ChaosScene",
        "ChaosConvex", "ChaosTrimesh", "ChaosAcceleration",
        "ChaosGeometry", "Chaos",
    ],
    "UI": ["UI_Texture", "UI_Text", "UI_Slate"],
}
PARENT_ORDER = ["Textures", "Meshes", "Physics", "UI"]
META_TAGS = {
    "Tracked Total", "Total", "Untracked", "Untagged",
    "FMalloc Unused", "OOM Backup Pool", "Program Size",
}

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt(v):
    return "-" if v is None else f"{v:,.1f}"


def delta_cls(d) -> str:
    if d is None:
        return ""
    if d < -5:
        return "good"
    if d > 5:
        return "bad"
    return "neutral"


def delta_str(d) -> str:
    if d is None:
        return "-"
    sign = "+" if d > 0 else ""
    return f"{sign}{d:,.1f}"


def pct_str(d, base) -> str:
    if d is None or base is None or base == 0:
        return ""
    return f"{d / base * 100:+.1f}%"


def _try_extract_scene(loc: str) -> str:
    """Best-effort scene name from player_location string."""
    if not loc:
        return "Unknown"
    # common patterns: X=... inside a map path, or just the map name
    for token in loc.split():
        if "Maps/" in token or "PBZ_" in token:
            parts = token.split("/")
            for p in parts:
                if p.startswith("PBZ_"):
                    return p.split(".")[0]
    return "Unknown"

# ──────────────────────────────────────────────
# Section builders
# ──────────────────────────────────────────────

def build_overview_cards(a, b, cl_a, cl_b, L):
    """Return HTML for the overview card grid."""
    a_llm = a.get("llm_full", {})
    b_llm = b.get("llm_full", {})
    a_pm = a.get("platform_memory", {})
    b_pm = b.get("platform_memory", {})
    a_der = a.get("derived", {})
    b_der = b.get("derived", {})
    a_fm = a.get("fmalloc", {})
    b_fm = b.get("fmalloc", {})

    items = [
        (L["os_phys_cur"], a_pm["process_physical_used_mb"], b_pm["process_physical_used_mb"]),
        (L["os_phys_peak"], a_pm["process_physical_peak_mb"], b_pm["process_physical_peak_mb"]),
        (L["test_eq_cur"], a_der["test_equivalent_mb"], b_der["test_equivalent_mb"]),
        (L["test_eq_peak"], a_der["peak_test_equivalent_mb"], b_der["peak_test_equivalent_mb"]),
        ("LLM Total", a_llm.get("Total", 0), b_llm.get("Total", 0)),
        ("FMalloc OS Total", a_fm["os_total_mb"], b_fm["os_total_mb"]),
        ("FMalloc Unused", a_llm.get("FMalloc Unused", 0), b_llm.get("FMalloc Unused", 0)),
        ("Untracked", a_llm.get("Untracked", 0), b_llm.get("Untracked", 0)),
    ]
    cards = []
    for label, va, vb in items:
        d = vb - va
        c = "good" if d < -5 else ("bad" if d > 5 else "neutral")
        cards.append(
            f'<div class="card">'
            f'<div class="card-label">{label}</div>'
            f'<div class="card-row"><span class="card-cl">CL {cl_a}</span><span class="card-val">{fmt(va)} MB</span></div>'
            f'<div class="card-row"><span class="card-cl">CL {cl_b}</span><span class="card-val">{fmt(vb)} MB</span></div>'
            f'<div class="card-delta {c}">{delta_str(d)} MB</div>'
            f'</div>'
        )
    return '<div class="cards">' + "\n".join(cards) + "</div>"


def build_budget_table(a, b, cl_a, cl_b, L):
    a_der = a["derived"]
    b_der = b["derived"]

    def row(label, target, va, vb):
        sa = "PASS" if va <= target else "FAIL"
        sb = "PASS" if vb <= target else "FAIL"
        ca = "budget-pass" if va <= target else "budget-fail"
        cb = "budget-pass" if vb <= target else "budget-fail"
        return (
            f'<tr><td>{label}</td><td class="num">{fmt(target)}</td>'
            f'<td class="num {ca}">{fmt(va)} ({sa})</td>'
            f'<td class="num {cb}">{fmt(vb)} ({sb})</td></tr>'
        )

    rows = [
        row(L["current_target"], 10500, a_der["test_equivalent_mb"], b_der["test_equivalent_mb"]),
        row(L["peak_safe"], 11500, a_der["peak_test_equivalent_mb"], b_der["peak_test_equivalent_mb"]),
        row(L["peak_crash"], 12000, a_der["peak_test_equivalent_mb"], b_der["peak_test_equivalent_mb"]),
    ]
    return (
        f'<table><tr><th>{L["check"]}</th><th>{L["threshold"]}</th>'
        f'<th>CL {cl_a}</th><th>CL {cl_b}</th></tr>'
        + "\n".join(rows) + "</table>"
    )


def _build_ordered_tags(a_llm, b_llm):
    """Return [(tag, is_child), ...] in display order."""
    children_set = set()
    for kids in HIERARCHY.values():
        children_set.update(kids)

    ordered = []
    visited = set()
    for p in PARENT_ORDER:
        if p in a_llm or p in b_llm:
            ordered.append((p, False))
            visited.add(p)
            for c in HIERARCHY.get(p, []):
                if c in a_llm or c in b_llm:
                    ordered.append((c, True))
                    visited.add(c)

    remaining = []
    for t in sorted(set(list(a_llm.keys()) + list(b_llm.keys())) - visited - META_TAGS):
        va = a_llm.get(t, 0)
        vb = b_llm.get(t, 0)
        remaining.append((t, abs(vb - va)))
    remaining.sort(key=lambda x: -x[1])
    for t, _ in remaining:
        ordered.append((t, False))
    return ordered


def build_movers(a_llm, b_llm, ordered_tags):
    """Return HTML for the delta-bar ranking."""
    movers = []
    for tag, is_child in ordered_tags:
        va = a_llm.get(tag)
        vb = b_llm.get(tag)
        if va is None or vb is None:
            continue
        d = vb - va
        if abs(d) >= 5:
            movers.append((tag, va, vb, d))
    movers.sort(key=lambda x: x[3])

    html_parts = []
    for tag, va, vb, d in movers:
        cls = "good" if d < 0 else "bad"
        pct = d / va * 100 if va else 0
        bar_w = min(abs(d) / 4, 100)
        html_parts.append(
            f'<div class="mover-row {cls}">'
            f'<span class="mover-tag">{tag}</span>'
            f'<span class="mover-vals">{fmt(va)} → {fmt(vb)}</span>'
            f'<span class="mover-delta">{delta_str(d)} MB ({pct:+.1f}%)</span>'
            f'<div class="mover-bar-bg"><div class="mover-bar {cls}" style="width:{bar_w}%"></div></div>'
            f'</div>'
        )
    return '<div class="movers">' + "\n".join(html_parts) + "</div>"


def build_llm_table(a_llm, b_llm, ordered_tags, cl_a, cl_b, L):
    """Return HTML for the full LLM tag comparison table."""
    rows = []
    for tag, is_child in ordered_tags:
        va = a_llm.get(tag)
        vb = b_llm.get(tag)
        d = (vb - va) if (va is not None and vb is not None) else None
        cls = delta_cls(d)
        indent = "child" if is_child else ("parent" if tag in HIERARCHY else "")
        bold = ' style="font-weight:600;"' if tag in HIERARCHY else ""
        prefix = "&nbsp;&nbsp;&nbsp;&nbsp;" if is_child else ""
        rows.append(
            f'<tr class="{cls} {indent}">'
            f'<td{bold}>{prefix}{tag}</td>'
            f'<td class="num">{fmt(va)}</td>'
            f'<td class="num">{fmt(vb)}</td>'
            f'<td class="num delta">{delta_str(d)}</td>'
            f'<td class="num pct">{pct_str(d, va)}</td>'
            f'</tr>'
        )

    # Footer rows
    for tag, style in [
        ("FMalloc Unused", 'style="border-top:2px solid var(--border); font-weight:700;"'),
        ("Untracked", 'style="font-weight:700;"'),
        ("Tracked Total", 'style="font-weight:700; border-top:2px solid var(--accent);"'),
        ("Total", 'style="font-weight:700;"'),
    ]:
        va = a_llm.get(tag, 0)
        vb = b_llm.get(tag, 0)
        d = vb - va
        color = delta_cls(d)
        color_style = f' style="color:var(--{color})"' if color in ("good", "bad") else ""
        rows.append(
            f'<tr {style}>'
            f'<td>{tag}</td>'
            f'<td class="num">{fmt(va)}</td>'
            f'<td class="num">{fmt(vb)}</td>'
            f'<td class="num delta"{color_style}>{delta_str(d)}</td>'
            f'<td class="num pct">{pct_str(d, va)}</td>'
            f'</tr>'
        )

    header = (
        f'<tr><th>{L["tag"]}</th><th>CL {cl_a} (MB)</th><th>CL {cl_b} (MB)</th>'
        f'<th>{L["change"]} (MB)</th><th>{L["change_pct"]}</th></tr>'
    )
    return (
        '<div class="table-wrap"><table>'
        + header + "\n".join(rows)
        + "</table></div>"
    )


def build_texture_section(a, b, cl_a, cl_b, L):
    """Collapsible NeverStream / Streaming texture group comparison."""
    a_tex = a.get("texture_breakdown", {})
    b_tex = b.get("texture_breakdown", {})
    rows = []

    for section_key, total_label in [("neverstream", L["ns_total"]), ("streaming", L["st_total"])]:
        a_s = a_tex.get(section_key, {})
        b_s = b_tex.get(section_key, {})
        at = a_s.get("total_mb", 0)
        bt = b_s.get("total_mb", 0)
        rows.append(
            f'<tr class="parent"><td><b>{total_label}</b></td>'
            f'<td class="num">{fmt(at)}</td><td class="num">{fmt(bt)}</td>'
            f'<td class="num delta">{delta_str(bt - at)}</td></tr>'
        )
        all_groups = sorted(set(
            list(a_s.get("by_group", {}).keys()) + list(b_s.get("by_group", {}).keys())
        ))
        for g in all_groups:
            ga = a_s.get("by_group", {}).get(g, {})
            gb = b_s.get("by_group", {}).get(g, {})
            va = ga.get("size_mb", 0) if ga else 0
            vb = gb.get("size_mb", 0) if gb else 0
            ca = ga.get("count", 0) if ga else 0
            cb = gb.get("count", 0) if gb else 0
            d = vb - va
            cls = delta_cls(d)
            count_info = f" ({ca}→{cb})" if (ca or cb) else ""
            rows.append(
                f'<tr class="child {cls}">'
                f'<td>&nbsp;&nbsp;&nbsp;&nbsp;{g}{count_info}</td>'
                f'<td class="num">{fmt(va)}</td><td class="num">{fmt(vb)}</td>'
                f'<td class="num delta">{delta_str(d)}</td></tr>'
            )

    header = (
        f'<tr><th>{L["group"]}</th><th>CL {cl_a} (MB)</th>'
        f'<th>CL {cl_b} (MB)</th><th>{L["change"]} (MB)</th></tr>'
    )
    return (
        f'<details><summary>{L["tex_section"]}</summary>'
        f'<div class="table-wrap"><table>{header}'
        + "\n".join(rows) + "</table></div></details>"
    )


def build_obj_section(a, b, cl_a, cl_b, L):
    """Collapsible obj list class comparison."""
    a_obj = {x["class"]: x for x in a.get("obj_list_summary_top15", [])}
    b_obj = {x["class"]: x for x in b.get("obj_list_summary_top15", [])}
    all_classes = sorted(
        set(list(a_obj.keys()) + list(b_obj.keys())),
        key=lambda c: -(abs(b_obj.get(c, {}).get("res_exc_mb", 0) - a_obj.get(c, {}).get("res_exc_mb", 0))),
    )
    rows = []
    for c in all_classes:
        ao = a_obj.get(c, {})
        bo = b_obj.get(c, {})
        va = ao.get("res_exc_mb", 0)
        vb = bo.get("res_exc_mb", 0)
        ca = ao.get("count", 0)
        cb = bo.get("count", 0)
        d = vb - va
        cls = delta_cls(d)
        rows.append(
            f'<tr class="{cls}"><td>{c}</td>'
            f'<td class="num">{ca:,}</td><td class="num">{cb:,}</td>'
            f'<td class="num">{fmt(va)}</td><td class="num">{fmt(vb)}</td>'
            f'<td class="num delta">{delta_str(d)}</td></tr>'
        )
    header = (
        f'<tr><th>{L["class"]}</th>'
        f'<th>{L["count"]} ({cl_a})</th><th>{L["count"]} ({cl_b})</th>'
        f'<th>{L["res_exc"]} ({cl_a}) MB</th><th>{L["res_exc"]} ({cl_b}) MB</th>'
        f'<th>{L["change"]} (MB)</th></tr>'
    )
    return (
        f'<details><summary>{L["obj_section"]}</summary>'
        f'<div class="table-wrap"><table>{header}'
        + "\n".join(rows) + "</table></div></details>"
    )


def build_rhi_section(a, b, cl_a, cl_b, L):
    """Collapsible RHI category comparison."""
    a_rhi = a.get("rhi_summaries", {})
    b_rhi = b.get("rhi_summaries", {})
    all_keys = sorted(
        set(list(a_rhi.keys()) + list(b_rhi.keys())),
        key=lambda k: -(abs(b_rhi.get(k, {}).get("size_mb", 0) - a_rhi.get(k, {}).get("size_mb", 0))),
    )
    rows = []
    for k in all_keys:
        ar = a_rhi.get(k, {})
        br = b_rhi.get(k, {})
        va = ar.get("size_mb", 0)
        vb = br.get("size_mb", 0)
        if va == 0 and vb == 0:
            continue
        d = vb - va
        cls = delta_cls(d)
        label = k.replace("name=", "").replace("Type=", "")
        rows.append(
            f'<tr class="{cls}"><td>{label}</td>'
            f'<td class="num">{fmt(va)}</td><td class="num">{fmt(vb)}</td>'
            f'<td class="num delta">{delta_str(d)}</td></tr>'
        )
    header = (
        f'<tr><th>{L["rhi_cat"]}</th><th>CL {cl_a} (MB)</th>'
        f'<th>CL {cl_b} (MB)</th><th>{L["change"]} (MB)</th></tr>'
    )
    return (
        f'<details><summary>{L["rhi_section"]}</summary>'
        f'<div class="table-wrap"><table>{header}'
        + "\n".join(rows) + "</table></div></details>"
    )

# ──────────────────────────────────────────────
# CSS (shared with render_report.py style)
# ──────────────────────────────────────────────

CSS = """\
:root {
  --bg: #1a1a2e; --bg2: #16213e; --bg3: #0f3460;
  --fg: #e0e0e0; --fg2: #a0a0b0;
  --good: #00c853; --good-bg: rgba(0,200,83,0.08);
  --bad: #ff5252; --bad-bg: rgba(255,82,82,0.08);
  --accent: #64b5f6; --border: #2a2a4a;
  --card-bg: #1e2747;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--fg); font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; font-size: 14px; line-height: 1.5; }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
h1 { font-size: 22px; font-weight: 600; margin-bottom: 4px; color: #fff; }
h2 { font-size: 17px; font-weight: 600; margin: 28px 0 12px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.subtitle { color: var(--fg2); font-size: 13px; margin-bottom: 20px; }

/* Cards */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-bottom: 8px; }
.card { background: var(--card-bg); border-radius: 8px; padding: 14px 16px; border: 1px solid var(--border); }
.card-label { font-size: 12px; color: var(--fg2); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.card-row { display: flex; justify-content: space-between; font-size: 13px; margin: 2px 0; }
.card-cl { color: var(--fg2); }
.card-val { font-weight: 500; }
.card-delta { font-size: 16px; font-weight: 700; margin-top: 6px; text-align: center; padding: 4px; border-radius: 4px; }
.card-delta.good { color: var(--good); background: var(--good-bg); }
.card-delta.bad { color: var(--bad); background: var(--bad-bg); }
.card-delta.neutral { color: var(--fg2); }

/* Budget */
.budget-pass { color: var(--good); font-weight: 600; }
.budget-fail { color: var(--bad); font-weight: 600; }

/* Movers */
.movers { margin: 12px 0; }
.mover-row { display: grid; grid-template-columns: 180px 200px 180px 1fr; align-items: center; padding: 6px 12px; border-radius: 4px; margin: 2px 0; font-size: 13px; }
.mover-row.good { background: var(--good-bg); }
.mover-row.bad { background: var(--bad-bg); }
.mover-tag { font-weight: 600; }
.mover-vals { color: var(--fg2); }
.mover-delta { font-weight: 600; }
.mover-row.good .mover-delta { color: var(--good); }
.mover-row.bad .mover-delta { color: var(--bad); }
.mover-bar-bg { height: 8px; background: rgba(255,255,255,0.05); border-radius: 4px; overflow: hidden; }
.mover-bar { height: 100%; border-radius: 4px; }
.mover-bar.good { background: var(--good); }
.mover-bar.bad { background: var(--bad); }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px 10px; background: var(--bg3); color: var(--accent); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.3px; position: sticky; top: 0; z-index: 1; }
td { padding: 5px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); }
tr:hover { background: rgba(255,255,255,0.03); }
.num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'Cascadia Code', 'Consolas', monospace; }
.delta { font-weight: 600; }
tr.good .delta { color: var(--good); }
tr.bad .delta { color: var(--bad); }
tr.neutral .delta { color: var(--fg2); }
.pct { color: var(--fg2); font-size: 12px; }
tr.parent > td { font-weight: 600; background: rgba(255,255,255,0.02); }
tr.child > td:first-child { color: var(--fg2); }

/* Collapsible */
details { margin: 4px 0; }
details > summary { cursor: pointer; padding: 6px 0; color: var(--accent); font-weight: 500; font-size: 14px; list-style: none; }
details > summary::before { content: "\\25B6 "; font-size: 10px; transition: transform 0.2s; display: inline-block; margin-right: 6px; }
details[open] > summary::before { transform: rotate(90deg); }
details > summary::-webkit-details-marker { display: none; }

.table-wrap { max-height: 600px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 8px; }
.table-wrap::-webkit-scrollbar { width: 6px; }
.table-wrap::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
"""

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Render LLM comparison HTML")
    parser.add_argument("older", help="Older parsed_llm.json")
    parser.add_argument("newer", help="Newer parsed_llm.json")
    parser.add_argument("-o", "--output", required=True, help="Output HTML path")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"], help="Language (default: zh)")
    args = parser.parse_args()

    a = load_json(args.older)
    b = load_json(args.newer)
    L = LABELS[args.lang]

    a_hdr = a.get("header", {})
    b_hdr = b.get("header", {})
    cl_a = a_hdr.get("changelist", "A")
    cl_b = b_hdr.get("changelist", "B")

    a_llm = a.get("llm_full", {})
    b_llm = b.get("llm_full", {})
    ordered_tags = _build_ordered_tags(a_llm, b_llm)

    platform = a.get("platform", b.get("platform", "Unknown"))
    config = a_hdr.get("config", "")
    scene = _try_extract_scene(a_hdr.get("player_location", ""))

    subtitle = (
        f'CL {cl_a} ({config}, {L["boot"]} {a_hdr.get("boot_seconds", 0):.0f}s) '
        f'&nbsp;vs&nbsp; '
        f'CL {cl_b} ({config}, {L["boot"]} {b_hdr.get("boot_seconds", 0):.0f}s) '
        f'&nbsp;|&nbsp; {platform} {config} '
        f'&nbsp;|&nbsp; {L["scene"]}: {scene}'
    )

    html = f"""<!DOCTYPE html>
<html lang="{args.lang}">
<head>
<meta charset="utf-8">
<title>{L["title"]}: CL {cl_a} vs CL {cl_b}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
<h1>{L["title"]}</h1>
<div class="subtitle">{subtitle}</div>

<h2>{L["overview"]}</h2>
{build_overview_cards(a, b, cl_a, cl_b, L)}

<h2>{L["budget"]}</h2>
{build_budget_table(a, b, cl_a, cl_b, L)}

<h2>{L["movers"]} ({L["movers_threshold"]})</h2>
{build_movers(a_llm, b_llm, ordered_tags)}

<h2>{L["llm_detail"]}</h2>
{build_llm_table(a_llm, b_llm, ordered_tags, cl_a, cl_b, L)}

{build_texture_section(a, b, cl_a, cl_b, L)}
{build_obj_section(a, b, cl_a, cl_b, L)}
{build_rhi_section(a, b, cl_a, cl_b, L)}

</div>
</body>
</html>"""

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Comparison report written to {args.output}")


if __name__ == "__main__":
    main()
