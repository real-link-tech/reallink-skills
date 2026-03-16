#!/usr/bin/env python3
"""
Render a memreport analysis HTML report from parsed.json + analysis.json.

Usage:
    python render_report.py <parsed.json> <analysis.json> [--output <report.html>] [--lang zh|en]

parsed.json: output from parse_memreport.py
analysis.json: LLM-generated analysis (health_summary, suggestions, notes)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# --- Localization ---

STRINGS = {
    "zh": {
        "title_prefix": "内存分析报告",
        "subtitle_tpl": "平台: {platform} | 配置: {config} | CL: {cl} | 快照时间: {boot}s",
        "section_overview": "概览",
        "section_tree": "内存树",
        "section_top_assets": "分类最大资源",
        "section_suggestions": "优化建议",
        "section_data_gaps": "数据缺失",
        "os_physical": "OS 物理内存",
        "peak_physical": "峰值物理内存",
        "llm_total": "LLM 追踪总量",
        "available": "可用内存",
        "test_equiv": "Test 等效",
        "peak_test_equiv": "峰值 Test 等效",
        "fmalloc_total": "FMalloc OS 总量",
        "no_llm_title": "缺少 LLM 数据",
        "no_llm_body": "此 memreport 未包含 LLM 标签数据（游戏未以 <code>-llm</code> 参数启动）。无法进行标签级内存分解。建议使用 <code>-llm</code> 参数重新采集。",
        "test_build_title": "Test 包数据受限",
        "test_build_body": "当前为 Test 配置，<code>rhi.DumpResourceMemory</code> 等控制台命令不可用，无法展示 UAV、Buffer、Nanite、Lumen 等 GPU 资源分类及纹理 NonStreaming 明细。如需完整数据请使用 Development 包采集。",
        "health_summary_label": "健康摘要",
        "col_name": "名称",
        "col_size": "大小 (MB)",
        "col_source": "数据来源",
        "col_type": "类型",
        "col_format": "格式",
        "finding": "发现",
        "saving": "潜在节省",
        "action": "操作",
        "risk": "风险",
        "no_suggestions": "无优化建议（数据不足或内存状态良好）",
        "no_data_gaps": "所有关键数据段均已采集",
        "missing_section": "缺失: {cmd} — {impact}",
        "generated_at": "生成于 {dt}",
        "budget_label": "预算",
        "over_budget": "超预算",
        "under_budget": "余量",
        "tree_textures_detail": "纹理明细 (listtextures)",
        "tex_nonstreaming": "NonStreaming (UAV)",
        "tex_neverstream": "NeverStream",
        "tex_streaming": "Streaming",
    },
    "en": {
        "title_prefix": "Memory Analysis Report",
        "subtitle_tpl": "Platform: {platform} | Config: {config} | CL: {cl} | Snapshot: {boot}s",
        "section_overview": "Overview",
        "section_tree": "Memory Tree",
        "section_top_assets": "Top Assets by Category",
        "section_suggestions": "Optimization Suggestions",
        "section_data_gaps": "Data Gaps",
        "os_physical": "OS Physical",
        "peak_physical": "Peak Physical",
        "llm_total": "LLM Total",
        "available": "Available",
        "test_equiv": "Test Equivalent",
        "peak_test_equiv": "Peak Test Equiv",
        "fmalloc_total": "FMalloc OS Total",
        "no_llm_title": "Missing LLM Data",
        "no_llm_body": "This memreport does not contain LLM tag data (game was not launched with <code>-llm</code>). Tag-level breakdown is not possible. Recommend re-capturing with <code>-llm</code> launch parameter.",
        "test_build_title": "Test Build — Limited Data",
        "test_build_body": "This is a Test configuration build. Console commands like <code>rhi.DumpResourceMemory</code> are unavailable, so UAV, Buffer, Nanite, Lumen and other GPU resource categories and NonStreaming texture details cannot be shown. Use a Development build for full data.",
        "health_summary_label": "Health Summary",
        "col_name": "Name",
        "col_size": "Size (MB)",
        "col_source": "Source",
        "col_type": "Type",
        "col_format": "Format",
        "finding": "Finding",
        "saving": "Potential Saving",
        "action": "Action",
        "risk": "Risk",
        "no_suggestions": "No optimization suggestions (insufficient data or healthy memory state)",
        "no_data_gaps": "All critical data sections present",
        "missing_section": "Missing: {cmd} — {impact}",
        "generated_at": "Generated at {dt}",
        "budget_label": "Budget",
        "over_budget": "Over budget",
        "under_budget": "Headroom",
        "tree_textures_detail": "Texture details (listtextures)",
        "tex_nonstreaming": "NonStreaming (UAV)",
        "tex_neverstream": "NeverStream",
        "tex_streaming": "Streaming",
    },
}

# --- LLM Tag Hierarchy (from KB section 3.0) for building the memory tree ---

TAG_HIERARCHY = {
    "FMalloc": {
        "children": [
            {"Textures": ["TextureMetaData", "VirtualTextureSystem"]},
            "RenderTargets",
            {"Meshes": ["StaticMesh", "SkeletalMesh", "InstancedMesh", "Landscape"]},
            {"Physics": ["ChaosTrimesh", "ChaosAcceleration", "ChaosGeometry", "ChaosUpdate", "ChaosBody", "ChaosActor", "ChaosConvex", "Chaos"]},
            {"UObject": ["_uobject_breakdown"]}, "Shaders", "Nanite",
            {"Audio": ["MetaSound", "AudioSoundWaves"]},
            "RHIMisc", "Animation", "NavigationRecast", "SceneRender",
            "Lumen", "DistanceFields",
            {"UI": ["UI_Style", "UI_Texture", "UI_Text", "UI_UMG", "UI_Slate"]},
            "Niagara", "AssetRegistry", "StreamingManager", "ConfigSystem",
            "FMallocUnused", "Untagged",
        ]
    },
    "AgcTransientHeaps": {},
    "ProgramSize": {},
    "LLMOverhead": {},
    "OOMBackupPool": {},
    "Untracked": {},
}

# Budget reference for tags that have one: (tag_name, budget_mb, hardcap_mb)
BUDGET_MAP = {
    "ProgramSize": (255, 270),
    "LLMOverhead": (30, 50),
    "OOMBackupPool": (8, 8),
    "Shaders": (550, 650),
    "AssetRegistry": (80, 100),
    "ConfigSystem": (40, 50),
    "AgcTransientHeaps": (530, 600),
    "FMallocUnused": (750, 950),
    "RHIMisc": (400, 500),
    "SceneRender": (120, 160),
    "Untracked": (400, 450),
    "RenderTargets": (350, 450),
    "Textures": (1600, 1900),
    "Meshes": (1100, 1300),
    "Physics": (550, 700),
    "UObject": (700, 850),
    "Nanite": (500, 650),
    "Audio": (300, 400),
    "Animation": (280, 350),
    "NavigationRecast": (180, 250),
    "UI": (40, 60),
    "Lumen": (60, 80),
    "DistanceFields": (55, 70),
    "StreamingManager": (60, 80),
}

# Expected memreport sections and their impact when missing
EXPECTED_SECTIONS = [
    ("obj list -resourcesizesort", "No per-class memory breakdown"),
    ("obj list class=SkeletalMesh -resourcesizesort", "No per-asset skeletal mesh data"),
    ("obj list class=StaticMesh -resourcesizesort", "No per-asset static mesh data"),
    ("listtextures nonvt", "No per-texture size/format data"),
    ("rhi.DumpMemory", "No GPU resource type breakdown"),
    ("rhi.DumpResourceMemory", "No per-resource GPU data"),
    ("r.DumpRenderTargetPoolMemory", "No render target pool data"),
]


def esc(s):
    """HTML-escape a string."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fmt_mb(v):
    """Format a float as MB string with 1 decimal."""
    if v is None:
        return "\u2014"
    return f"{v:,.1f}"


def build_overview_cards(parsed, s):
    """Build HTML for overview metric cards."""
    pm = parsed.get("platform_memory", {})
    derived = parsed.get("derived", {})
    fm = parsed.get("fmalloc", {})

    cards = []

    def add_card(label, value, sub="", css=""):
        cards.append(
            f'<div class="card"><div class="label">{esc(label)}</div>'
            f'<div class="value {css}">{esc(value)}</div>'
            f'{"<div class=sub>" + esc(sub) + "</div>" if sub else ""}</div>'
        )

    os_phys = pm.get("process_physical_used_mb")
    peak = pm.get("process_physical_peak_mb")
    llm_total = derived.get("llm_total_mb")
    test_eq = derived.get("test_equivalent_mb")
    peak_test_eq = derived.get("peak_test_equivalent_mb")

    # When peak exceeds crash threshold, use peak for budget assessment
    use_peak_for_budget = peak_test_eq is not None and peak_test_eq > 12000

    # Current card color
    assess_val = peak_test_eq if use_peak_for_budget else test_eq
    os_css = ""
    if assess_val is not None:
        if assess_val <= 10500:
            os_css = "good"
        elif assess_val <= 11000:
            os_css = "warn"
        else:
            os_css = "bad"

    sub_parts = []
    if derived.get("is_dev_build") and test_eq:
        sub_parts.append(f'{s["test_equiv"]}: {fmt_mb(test_eq)} MB')
    add_card(s["os_physical"], fmt_mb(os_phys) + " MB", " | ".join(sub_parts), os_css)

    peak_css = ""
    if peak_test_eq:
        if peak_test_eq <= 11500:
            peak_css = "good"
        elif peak_test_eq <= 12000:
            peak_css = "warn"
        else:
            peak_css = "bad"
    peak_sub = ""
    if derived.get("is_dev_build") and peak_test_eq:
        peak_sub = f'{s["peak_test_equiv"]}: {fmt_mb(peak_test_eq)} MB'
    add_card(s["peak_physical"], fmt_mb(peak) + " MB", peak_sub, peak_css)

    add_card(s["llm_total"], fmt_mb(llm_total) + " MB" if llm_total else "\u2014")
    add_card(s["fmalloc_total"], fmt_mb(fm.get("os_total_mb")) + " MB" if fm.get("os_total_mb") else "\u2014")

    avail = pm.get("physical_free_mb")
    if avail:
        add_card(s["available"], fmt_mb(avail) + " MB")

    return '<div class="cards">' + "\n".join(cards) + "</div>"


def _normalize_tag_values(parsed):
    """Build normalized tag name -> value lookup from LLM tags."""
    tag_values = {}
    for tag in parsed.get("llm_platform", []):
        tag_values[tag["name"]] = tag["value_mb"]
    for tag in parsed.get("llm_full", []):
        tag_values[tag["name"]] = tag["value_mb"]
    name_map = {
        "FMalloc Unused": "FMallocUnused", "FMalloc": "FMalloc",
        "Program Size": "ProgramSize", "LLM Overhead": "LLMOverhead",
        "OOM Backup Pool": "OOMBackupPool", "Agc Transient Heaps": "AgcTransientHeaps",
        "Scene Render": "SceneRender", "Render Targets": "RenderTargets",
        "Distance Fields": "DistanceFields", "Asset Registry": "AssetRegistry",
        "Streaming Manager": "StreamingManager", "Config System": "ConfigSystem",
        "Virtual Texture System": "VirtualTextureSystem", "Texture MetaData": "TextureMetaData",
        "Instanced Mesh": "InstancedMesh", "Static Mesh": "StaticMesh",
        "Skeletal Mesh": "SkeletalMesh", "RHI Misc": "RHIMisc",
        "Chaos Trimesh": "ChaosTrimesh", "Chaos Acceleration": "ChaosAcceleration",
        "Chaos Geometry": "ChaosGeometry", "Chaos Update": "ChaosUpdate",
        "Chaos Body": "ChaosBody", "Chaos Actor": "ChaosActor",
        "Chaos Convex": "ChaosConvex", "Chaos Scene": "ChaosScene",
        "Meta Sound": "MetaSound", "Navigation Recast": "NavigationRecast",
        "Audio Sound Waves": "AudioSoundWaves", "Load Map Misc": "LoadMapMisc",
        "Scene Culling": "SceneCulling",
    }
    normalized = {}
    for name, val in tag_values.items():
        canonical = name_map.get(name, name)
        if canonical not in normalized or val > normalized[canonical]:
            normalized[canonical] = val
    for name, val in tag_values.items():
        if name not in normalized:
            normalized[name] = val
    return normalized


def _budget_bar_html(tag_name, actual):
    """Return HTML for inline budget bar + delta text. Empty string if no budget."""
    if tag_name not in BUDGET_MAP or actual is None or actual <= 0:
        return ""
    budget, hardcap = BUDGET_MAP[tag_name]
    delta = actual - budget

    # Determine color class
    if actual > hardcap:
        css = "bad"
    elif actual > budget:
        css = "warn"
    else:
        css = "good"

    # Bar fill: actual/hardcap ratio, capped at 100%
    fill_pct = min(actual / hardcap * 100, 100) if hardcap > 0 else 0
    # Budget marker position
    mark_pct = min(budget / hardcap * 100, 100) if hardcap > 0 else 0

    bar_html = (
        f'<span class="tbar">'
        f'<span class="bf {css}" style="width:{fill_pct:.0f}%"></span>'
        f'<span class="bm" style="left:{mark_pct:.0f}%"></span>'
        f'</span>'
    )

    delta_sign = "+" if delta > 0 else ""
    delta_html = f'<span class="td {css}">{delta_sign}{delta:,.0f} / {budget:,}</span>'

    return bar_html + delta_html


def _shorten_group_name(group):
    """Shorten TEXTUREGROUP_WorldNormalMap → WorldNormalMap."""
    return group.replace("TEXTUREGROUP_", "") if group.startswith("TEXTUREGROUP_") else group


def _row_content_html(name, val, parent_val=0, tag_name=None, extra_class="", suffix=""):
    """Generate the inner content spans of a single tree row."""
    pct = ""
    if parent_val > 0 and val > 0:
        pct = f" ({val / parent_val * 100:.1f}%)"
    budget_html = _budget_bar_html(tag_name or name, val) if val > 0 else ""

    val_css = ""
    bn = tag_name or name
    if bn in BUDGET_MAP and val > 0:
        budget, hardcap = BUDGET_MAP[bn]
        if val > hardcap:
            val_css = "bad"
        elif val > budget:
            val_css = "warn"

    suffix_html = f'<span class="tpct tex-info">{esc(suffix)}</span>' if suffix else ""

    return (
        f'<span class="tn">{esc(name)}</span>'
        f'<span class="tv {val_css}">{fmt_mb(val)} MB</span>'
        f'<span class="tpct">{esc(pct)}</span>'
        f'{budget_html}{suffix_html}'
    )


def _tree_leaf(name, val, parent_val=0, tag_name=None, extra_class="", suffix=""):
    """Render a leaf node (no children, not expandable)."""
    content = _row_content_html(name, val, parent_val, tag_name, extra_class, suffix)
    return f'<div class="tr leaf {extra_class}">{content}</div>'


def _tree_branch(name, val, children_html, parent_val=0, tag_name=None, extra_class="", initially_open=True):
    """Render a branch node (expandable with children)."""
    content = _row_content_html(name, val, parent_val, tag_name, extra_class)
    open_attr = " open" if initially_open else ""
    return (
        f'<details class="tree-node {extra_class}"{open_attr}>'
        f'<summary class="tr">{content}</summary>'
        f'<div class="tree-children">{children_html}</div>'
        f'</details>'
    )


def _build_uobject_breakdown(parsed, parent_val):
    """Build UObject sub-tree from obj_list_summary — all classes, with overlap warning."""
    obj_summary = parsed.get("obj_list_summary", [])
    if not obj_summary:
        return []

    items = []
    for entry in obj_summary:
        cls = entry.get("class", "")
        mb = entry.get("res_exc_mb", 0)
        if mb < 0.5:
            continue
        count = entry.get("count", 0)
        label = f"{cls} ({count:,})" if count else cls
        items.append((label, mb))

    items.sort(key=lambda x: x[1], reverse=True)

    parts = []
    # Disclaimer
    parts.append(
        '<div class="tr leaf disclaimer">'
        '<span class="tn">* 数据来自 obj list ResExcKB，与上方 LLM 标签口径不同，'
        '部分类与 Textures/Meshes/Physics 等存在重叠，仅供参考</span></div>'
    )

    for label, mb in items:
        if mb >= 1.0:
            parts.append(_tree_leaf(label, mb, parent_val, tag_name="_", extra_class="tex-detail"))

    small_total = sum(mb for _, mb in items if mb < 1.0)
    if small_total >= 1.0:
        parts.append(_tree_leaf("Other (<1MB)", small_total, parent_val,
                                 tag_name="_", extra_class="tex-detail"))
    return parts


def build_memory_tree(parsed):
    """Build the memory tree as nested collapsible HTML with inline budget bars."""
    pm = parsed.get("platform_memory", {})
    os_phys = pm.get("process_physical_used_mb", 0)
    normalized = _normalize_tag_values(parsed)
    tex_breakdown = parsed.get("texture_breakdown", {})
    transient_bd = parsed.get("transient_breakdown", {})

    def get_val(tag_name):
        return normalized.get(tag_name, 0)

    def _build_rt_breakdown(child_val, rt_data):
        """Build the RenderTargets breakdown sub-tree as collapsible HTML."""
        rt_items = sorted(rt_data.get("categories", {}).items(), key=lambda x: -x[1]["size_mb"])
        if not rt_items:
            return ""

        big = [(n, d) for n, d in rt_items if d.get("size_mb", 0) >= 1.0]
        small_total = sum(d.get("size_mb", 0) for n, d in rt_items if d.get("size_mb", 0) < 1.0)

        sub_parts = []
        for item_name, item_data in big:
            item_mb = item_data.get("size_mb", 0)
            top_names = ", ".join(i["name"] for i in item_data.get("items", [])[:2])
            llm_tag = item_data.get("llm_tag")
            if llm_tag:
                suffix_text = f"{top_names}  \u2190 {llm_tag}" if top_names else f"\u2190 {llm_tag}"
            else:
                suffix_text = top_names
            sub_parts.append(_tree_leaf(item_name, item_mb, rt_data.get("total_mb", 0),
                                        tag_name="_", extra_class="tex-detail", suffix=suffix_text))

        if small_total >= 1.0:
            sub_parts.append(_tree_leaf("Other", small_total, rt_data.get("total_mb", 0),
                                        tag_name="_", extra_class="tex-detail"))

        return "\n".join(sub_parts)

    def _build_tex_breakdown(child_val):
        """Build the texture breakdown sub-tree as collapsible HTML."""
        sections_data = []

        ns = tex_breakdown.get("nonstreaming", {})
        ns_total = ns.get("total_mb", 0)
        if ns_total > 0:
            ns_items = sorted(ns.get("categories", {}).items(), key=lambda x: -x[1]["size_mb"])
            sections_data.append(("NonStreaming (UAV)", ns_total, ns_items, "cat"))

        nev = tex_breakdown.get("neverstream", {})
        nev_total = nev.get("total_mb", 0)
        nev_count = nev.get("count", 0)
        if nev_total > 0:
            nev_items = sorted(nev.get("by_group", {}).items(), key=lambda x: -x[1]["size_mb"])
            sections_data.append((f"NeverStream ({nev_count})", nev_total, nev_items, "group"))

        st = tex_breakdown.get("streaming", {})
        st_total = st.get("total_mb", 0)
        st_count = st.get("count", 0)
        if st_total > 0:
            st_items = sorted(st.get("by_group", {}).items(), key=lambda x: -x[1]["size_mb"])
            sections_data.append((f"Streaming ({st_count})", st_total, st_items, "group"))

        parts = []
        for sec_label, sec_total, sec_items, sec_type in sections_data:
            big = [(n, d) for n, d in sec_items if d.get("size_mb", 0) >= 1.0]
            small_total = sum(d.get("size_mb", 0) for n, d in sec_items if d.get("size_mb", 0) < 1.0)

            sub_parts = []
            for item_name, item_data in big:
                item_mb = item_data.get("size_mb", 0)
                if sec_type == "cat":
                    # Build suffix: top item names + LLM tag annotation
                    top_names = ", ".join(i["name"] for i in item_data.get("items", [])[:2])
                    llm_tag = item_data.get("llm_tag")
                    if llm_tag:
                        suffix_text = f"{top_names}  ← {llm_tag}" if top_names else f"← {llm_tag}"
                    else:
                        suffix_text = top_names
                    sub_parts.append(_tree_leaf(item_name, item_mb, sec_total,
                                                tag_name="_", extra_class="tex-detail", suffix=suffix_text))
                else:
                    count = item_data.get("count", 0)
                    sub_parts.append(_tree_leaf(_shorten_group_name(item_name), item_mb, sec_total,
                                                tag_name="_", extra_class="tex-detail", suffix=f"{count} tex"))

            if small_total >= 1.0:
                sub_parts.append(_tree_leaf("Other", small_total, sec_total,
                                            tag_name="_", extra_class="tex-detail"))

            if sub_parts:
                parts.append(_tree_branch(sec_label, sec_total, "\n".join(sub_parts),
                                          child_val, tag_name="_", extra_class="tex-section", initially_open=False))
            else:
                parts.append(_tree_leaf(sec_label, sec_total, child_val,
                                        tag_name="_", extra_class="tex-section"))

        return "\n".join(parts)

    # Root
    root_val = os_phys or get_val("UsedPhysical")

    # Level 1: platform-level tags
    level1_items = []
    for tag_name in TAG_HIERARCHY:
        val = get_val(tag_name)
        if val > 0:
            level1_items.append((tag_name, val))
    level1_items.sort(key=lambda x: x[1], reverse=True)

    level1_parts = []
    for tag_name, val in level1_items:
        hierarchy_entry = TAG_HIERARCHY.get(tag_name, {})
        children_def = hierarchy_entry.get("children", [])

        if not children_def:
            # Special: AgcTransientHeaps shows informational note about contents
            if tag_name == "AgcTransientHeaps" and transient_bd.get("total_mb", 0) > 0:
                types = transient_bd.get("known_fastvram_types", [])
                suffix = "per-frame aliased RDG resources (not in any dump)"
                if types:
                    suffix += " — FastVRAM: " + ", ".join(types[:6]) + "..."
                level1_parts.append(_tree_leaf(tag_name, val, root_val, tag_name,
                                               suffix=suffix))
                continue
            level1_parts.append(_tree_leaf(tag_name, val, root_val, tag_name))
            continue

        # Collect children with values
        child_items = []
        for child in children_def:
            if isinstance(child, dict):
                for parent_name, sub_children in child.items():
                    parent_val = get_val(parent_name)
                    if parent_val > 0:
                        child_items.append((parent_name, parent_val, sub_children))
                    else:
                        sub_total = sum(get_val(sc) for sc in sub_children)
                        if sub_total > 0:
                            child_items.append((parent_name, sub_total, sub_children))
            else:
                child_val = get_val(child)
                # Fallback: if RenderTargets LLM tag is missing, use breakdown total
                if child == "RenderTargets" and child_val <= 0.5 and tex_breakdown:
                    rt_bd = tex_breakdown.get("rendertargets", {})
                    child_val = rt_bd.get("total_mb", 0)
                if child_val > 0.5:
                    child_items.append((child, child_val, []))

        child_items.sort(key=lambda x: x[1], reverse=True)

        small_items = [ci for ci in child_items if ci[1] < 1.0]
        big_items = [ci for ci in child_items if ci[1] >= 1.0]

        l2_parts = []
        for child_name, child_val, sub_children in big_items:
            l3_parts = []

            if sub_children and sub_children != ["_uobject_breakdown"]:
                sub_items = [(sc, get_val(sc)) for sc in sub_children if get_val(sc) > 0.5]
                sub_items.sort(key=lambda x: x[1], reverse=True)
                for sc_name, sc_val in sub_items:
                    l3_parts.append(_tree_leaf(sc_name, sc_val, child_val))

            if child_name == "UObject":
                l3_parts.extend(_build_uobject_breakdown(parsed, child_val))

            if child_name == "Textures" and tex_breakdown:
                l3_parts.append(_build_tex_breakdown(child_val))

            if child_name == "RenderTargets" and tex_breakdown:
                rt_bd = tex_breakdown.get("rendertargets", {})
                if rt_bd.get("total_mb", 0) > 0:
                    rt_html = _build_rt_breakdown(child_val, rt_bd)
                    if rt_html:
                        l3_parts.append(rt_html)

            if l3_parts:
                l2_parts.append(_tree_branch(child_name, child_val, "\n".join(l3_parts),
                                             val, child_name))
            else:
                l2_parts.append(_tree_leaf(child_name, child_val, val, child_name))

        if small_items:
            other_total = sum(ci[1] for ci in small_items)
            l2_parts.append(_tree_leaf("Other (<1MB)", other_total, val))

        if l2_parts:
            level1_parts.append(_tree_branch(tag_name, val, "\n".join(l2_parts), root_val, tag_name))
        else:
            level1_parts.append(_tree_leaf(tag_name, val, root_val, tag_name))

    return _tree_branch("OS Process Physical", root_val, "\n".join(level1_parts),
                         extra_class="root", initially_open=True)


def build_top_assets_table(parsed, s):
    """Build per-category top assets tables."""
    top_assets = parsed.get("top_assets", {})
    if not top_assets:
        return "<p>No asset data available</p>"

    # Define display order and Chinese names
    cat_names_zh = {
        "SkeletalMesh": "骨骼网格", "StaticMesh": "静态网格",
        "Texture": "纹理", "Texture2D": "纹理 (Texture2D)",
        "UAV": "UAV 纹理 (引擎内部)",
        "Buffer": "GPU Buffer", "Nanite": "Nanite",
        "Lumen": "Lumen", "Shadow": "阴影",
        "Hair": "毛发", "DistanceFields": "距离场",
        "TSR": "TSR", "GPUScene": "GPU Scene",
        "SoundWave": "音频", "GroomAsset": "毛发资产",
        "MaterialInstanceConstant": "材质实例",
        "BodySetup": "碰撞体 (BodySetup)",
        "FontFace": "字体",
        "AnimSequence": "动画序列",
        "AnimMontage": "动画蒙太奇",
        "AnimBlueprintGeneratedClass": "动画蓝图",
        "StaticMeshComponent": "静态网格组件",
        "SoundWave": "音频 (SoundWave)",
        "Level": "关卡",
        "LevelSequence": "关卡序列",
        "Other": "其他",
    }

    html_parts = []

    # Sort categories by total size descending
    sorted_cats = sorted(top_assets.items(), key=lambda x: sum(a["size_mb"] for a in x[1]), reverse=True)

    for cat, assets in sorted_cats:
        if not assets:
            continue
        cat_label = cat_names_zh.get(cat, cat) if s is STRINGS["zh"] else cat
        cat_total = sum(a["size_mb"] for a in assets)

        max_rows = 100
        rows = []
        for i, a in enumerate(assets[:max_rows], 1):
            name = a["name"]
            # Shorten long paths
            if "/" in name and len(name) > 60:
                name = "..." + name[name.rfind("/", 0, -1):]
            rows.append(
                f'<tr><td>{i}</td><td title="{esc(a["name"])}">{esc(name)}</td>'
                f'<td class="num">{fmt_mb(a["size_mb"])}</td>'
                f'<td>{esc(a.get("source", ""))}</td></tr>'
            )
        if len(assets) > max_rows:
            omitted = len(assets) - max_rows
            rows.append(
                f'<tr><td colspan="4" style="text-align:center;opacity:0.6">'
                f'... 还有 {omitted:,} 项未显示</td></tr>'
            )

        html_parts.append(
            f'<details><summary><strong>{esc(cat_label)}</strong>'
            f' <span class="cat-total">({fmt_mb(cat_total)} MB, {len(assets):,} items)</span></summary>'
            f'<table><thead><tr><th>#</th><th>{s["col_name"]}</th>'
            f'<th>{s["col_size"]}</th><th>{s["col_source"]}</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></details>'
        )

    return "\n".join(html_parts)


def build_suggestions_html(analysis, s):
    """Build optimization suggestions HTML from analysis.json."""
    suggestions = analysis.get("suggestions", [])
    if not suggestions:
        return f'<p>{s["no_suggestions"]}</p>'

    groups = {"P0": [], "P1": [], "P2": []}
    for sg in suggestions:
        p = sg.get("priority", "P2")
        groups.setdefault(p, []).append(sg)

    html_parts = []
    for priority in ["P0", "P1", "P2"]:
        items = groups.get(priority, [])
        if not items:
            continue
        css = f"priority-{priority.lower()}"
        for sg in items:
            tags_html = " ".join(f'<span class="tag">{esc(t)}</span>' for t in sg.get("tags", []))
            saving = sg.get("potential_saving_mb")
            saving_str = f'{saving} MB' if saving else "\u2014"
            html_parts.append(
                f'<div class="{css} suggestion">'
                f'<strong>[{priority}]</strong> {tags_html}'
                f'<div class="finding"><strong>{s["finding"]}:</strong> {esc(sg.get("finding", ""))}</div>'
                f'<div class="saving"><strong>{s["saving"]}:</strong> {saving_str}</div>'
                f'<div class="action"><strong>{s["action"]}:</strong> {esc(sg.get("action", ""))}</div>'
                f'<div class="risk"><strong>{s["risk"]}:</strong> {esc(sg.get("risk", ""))}</div>'
                f'</div>'
            )

    return "\n".join(html_parts)


def build_data_gaps_html(parsed, s):
    """Build data gaps section."""
    available_cmds = {sec["command"] for sec in parsed.get("sections", [])}
    gaps = []

    for cmd, impact in EXPECTED_SECTIONS:
        if cmd not in available_cmds:
            gaps.append(f'<div class="data-gap">{s["missing_section"].format(cmd=cmd, impact=impact)}</div>')

    if not parsed.get("has_llm_data"):
        gaps.insert(0, '<div class="data-gap" style="color:var(--red)">LLM tags missing \u2014 launch with -llm for full breakdown</div>')

    if not gaps:
        return f'<p style="color:var(--green)">{s["no_data_gaps"]}</p>'

    return "\n".join(gaps)


def render(parsed, analysis, lang="zh"):
    """Render the full HTML report."""
    s = STRINGS.get(lang, STRINGS["zh"])

    template_path = Path(__file__).parent / "report_template.html"
    template = template_path.read_text(encoding="utf-8")

    header = parsed.get("header", {})
    config = header.get("config", "Unknown")
    cl = header.get("changelist", "?")
    boot = header.get("boot_seconds", "?")
    platform = parsed.get("platform", "Unknown")

    title = f'{s["title_prefix"]} \u2014 {platform} / {config} / CL {cl}'
    subtitle = s["subtitle_tpl"].format(platform=platform, config=config, cl=cl, boot=boot)

    # No-LLM banner
    no_llm = ""
    if not parsed.get("has_llm_data"):
        no_llm = f'<div class="banner-warn"><strong>{s["no_llm_title"]}</strong><p>{s["no_llm_body"]}</p></div>'

    # Test build banner — RHI console commands unavailable
    test_banner = ""
    if config == "Test":
        test_banner = f'<div class="banner-warn" style="border-color:var(--yellow);background:#3a3a1c"><strong>{s["test_build_title"]}</strong><p>{s["test_build_body"]}</p></div>'

    # Health summary from LLM analysis
    health = analysis.get("health_summary", "")
    notes = analysis.get("notes", [])
    health_html = ""
    if health:
        health_html = f'<h3>{s["health_summary_label"]}</h3><p>{esc(health)}</p>'
        if notes:
            health_html += "<ul>" + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>"

    # Build all sections
    replacements = {
        "{{LANG}}": lang,
        "{{TITLE}}": esc(title),
        "{{SUBTITLE}}": esc(subtitle),
        "{{NO_LLM_BANNER}}": no_llm,
        "{{TEST_BUILD_BANNER}}": test_banner,
        "{{SECTION_OVERVIEW}}": s["section_overview"],
        "{{OVERVIEW_CARDS}}": build_overview_cards(parsed, s),
        "{{LLM_HEALTH_SUMMARY}}": health_html,
        "{{SECTION_TREE}}": s["section_tree"],
        "{{MEMORY_TREE}}": build_memory_tree(parsed),
        "{{SECTION_TOP_ASSETS}}": s["section_top_assets"],
        "{{TOP_ASSETS_TABLE}}": build_top_assets_table(parsed, s),
        "{{SECTION_SUGGESTIONS}}": s["section_suggestions"],
        "{{SUGGESTIONS_HTML}}": build_suggestions_html(analysis, s),
        "{{SECTION_DATA_GAPS}}": s["section_data_gaps"],
        "{{DATA_GAPS_HTML}}": build_data_gaps_html(parsed, s),
        "{{GENERATED_AT}}": s["generated_at"].format(dt=datetime.now().strftime("%Y-%m-%d %H:%M")),
    }

    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    return html


def main():
    parser = argparse.ArgumentParser(description="Render memreport analysis HTML from parsed + analysis JSON")
    parser.add_argument("parsed_json", help="Path to parsed.json from parse_memreport.py")
    parser.add_argument("analysis_json", help="Path to analysis.json from LLM")
    parser.add_argument("--output", "-o", help="Output HTML file path (default: report.html)")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="Report language (default: zh)")
    args = parser.parse_args()

    parsed = json.loads(Path(args.parsed_json).read_text(encoding="utf-8"))
    analysis = json.loads(Path(args.analysis_json).read_text(encoding="utf-8"))

    html = render(parsed, analysis, lang=args.lang)

    output_path = args.output or "report.html"
    Path(output_path).write_text(html, encoding="utf-8")
    print(f"Report written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
