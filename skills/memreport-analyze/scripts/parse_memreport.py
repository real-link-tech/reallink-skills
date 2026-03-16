#!/usr/bin/env python3
"""
Parse UE5 memreport files and extract structured data as JSON.

Usage:
    python parse_memreport.py <memreport_file> [--output <output.json>]

Outputs a JSON object with:
- header: changelist, config, device, boot time, player location
- platform_memory: OS process physical, peak, available, total
- fmalloc: OS total, small/large pool, cached free, per-bin fragmentation
- llm_platform: all STATGROUP_LLMPlatform tags
- llm_summary: all STATGROUP_LLM tags (warning: Summary Bug)
- llm_full: all STATGROUP_LLMFULL tags
- sections: list of available sections with line ranges
- rhi_dump: RHI memory stats by type
- rhi_top_resources: top 50 RHI resources by size
- rhi_summaries: named RHI resource summaries (Nanite, Lumen, etc.)
- obj_list_summary: top classes by ResExcKB from obj list -resourcesizesort
- obj_list_assets: per-asset lists for key classes (SkeletalMesh, StaticMesh, etc.)
- listtextures: top 100 textures from listtextures nonvt
- navigation: Detour/Recast memory breakdown
- rt_pool: render target pool entries (top 30)
- has_llm_data: bool, whether LLM tags are present
- derived: computed fields (ratios, gaps, flags)
- validation: pre-computed validation checks with status
- top_assets: merged top 20 assets across all data sources
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_header(lines):
    """Extract header info from first ~20 lines."""
    header = {}
    for line in lines[:20]:
        if line.startswith("Changelist:"):
            header["changelist"] = line.split(":", 1)[1].strip()
        elif line.startswith("Config:"):
            header["config"] = line.split(":", 1)[1].strip()
        elif line.startswith("Device Name:"):
            header["device"] = line.split(":", 1)[1].strip()
        elif line.startswith("Time Since Boot:"):
            header["boot_seconds"] = float(re.search(r"([\d.]+)", line).group(1))
        elif "View Location:" in line:
            header["player_location"] = line.strip()
    return header


def parse_stat_line(line):
    """Parse a STAT line like '  1234.567MB  -  Name - STAT_X - STATGROUP_Y'."""
    m = re.match(r"\s+([\d.]+)MB\s+-\s+(.+?)\s+-\s+(STAT_\w+)\s+-\s+(STATGROUP_\w+)", line)
    if m:
        return {
            "value_mb": float(m.group(1)),
            "name": m.group(2).strip(),
            "stat_name": m.group(3),
            "stat_group": m.group(4),
        }
    return None


def parse_platform_memory(lines):
    """Extract platform memory stats."""
    mem = {}
    for line in lines:
        if "Process Physical Memory:" in line:
            m = re.search(r"([\d.]+)\s*MB\s*used.*?([\d.]+)\s*MB\s*peak", line)
            if m:
                mem["process_physical_used_mb"] = float(m.group(1))
                mem["process_physical_peak_mb"] = float(m.group(2))
        elif line.startswith("Physical Memory:"):
            m = re.search(r"([\d.]+)\s*MB\s*used.*?([\d.]+)\s*MB\s*free.*?([\d.]+)\s*MB\s*total", line)
            if m:
                mem["physical_used_mb"] = float(m.group(1))
                mem["physical_free_mb"] = float(m.group(2))
                mem["physical_total_mb"] = float(m.group(3))
    return mem


def parse_fmalloc(lines):
    """Extract FMallocBinned2 stats and per-bin fragmentation."""
    fmalloc = {"bins": []}
    in_fmalloc = False
    for line in lines:
        if "FMallocBinned2 Mem report" in line:
            in_fmalloc = True
            continue
        if not in_fmalloc:
            continue
        if "Memory Stats:" in line:
            break

        if "Small Pool Allocations:" in line:
            m = re.search(r"([\d.]+)mb", line)
            if m:
                fmalloc["small_pool_used_mb"] = float(m.group(1))
        elif "Small Pool OS Allocated:" in line:
            m = re.search(r"([\d.]+)mb", line)
            if m:
                fmalloc["small_pool_os_mb"] = float(m.group(1))
        elif "Large Pool Requested" in line:
            m = re.search(r"([\d.]+)mb", line)
            if m:
                fmalloc["large_pool_requested_mb"] = float(m.group(1))
        elif "Large Pool OS Allocated:" in line:
            m = re.search(r"([\d.]+)mb", line)
            if m:
                fmalloc["large_pool_os_mb"] = float(m.group(1))
        elif "Total allocated from OS:" in line:
            m = re.search(r"([\d.]+)mb", line)
            if m:
                fmalloc["os_total_mb"] = float(m.group(1))
        elif "Cached free OS pages:" in line:
            m = re.search(r"([\d.]+)mb", line)
            if m:
                fmalloc["cached_free_mb"] = float(m.group(1))
        elif line.startswith("Bin"):
            m = re.match(
                r"Bin\s+(\d+)\s+Fragmentation\s+(\d+)\s*%.*?Wasted Mem\s+([\d.]+)\s*MB.*?Total Allocated Mem\s+([\d.]+)\s*MB",
                line,
            )
            if m:
                frag_pct = int(m.group(2))
                wasted = float(m.group(3))
                if frag_pct >= 10 or wasted >= 5.0:  # only include notable bins
                    fmalloc["bins"].append({
                        "bin_size": int(m.group(1)),
                        "fragmentation_pct": frag_pct,
                        "wasted_mb": wasted,
                        "total_allocated_mb": float(m.group(4)),
                    })
    return fmalloc


def parse_llm_tags(lines):
    """Extract all LLM tags grouped by stat group."""
    platform = []
    summary = []
    full = []
    for line in lines:
        stat = parse_stat_line(line)
        if not stat:
            continue
        if stat["stat_group"] == "STATGROUP_LLMPlatform":
            platform.append(stat)
        elif stat["stat_group"] == "STATGROUP_LLM":
            summary.append(stat)
        elif stat["stat_group"] == "STATGROUP_LLMFULL":
            full.append(stat)
    return platform, summary, full


def parse_navigation(lines):
    """Extract navigation/recast memory stats."""
    nav = []
    for line in lines:
        stat = parse_stat_line(line)
        if stat and stat["stat_group"] == "STATGROUP_Navigation" and stat["value_mb"] > 0.001:
            nav.append(stat)
    return nav


def find_sections(lines):
    """Find all MemReport sections with their line ranges."""
    sections = []
    for i, line in enumerate(lines):
        m = re.match(r'MemReport: Begin command "(.+)"', line)
        if m:
            sections.append({"command": m.group(1), "start_line": i + 1})
        m = re.match(r'MemReport: End command "(.+)"', line)
        if m:
            for s in reversed(sections):
                if s["command"] == m.group(1) and "end_line" not in s:
                    s["end_line"] = i + 1
                    s["line_count"] = s["end_line"] - s["start_line"]
                    break
    return sections


def parse_rhi_dump(lines):
    """Extract rhi.DumpMemory section."""
    rhi = []
    in_section = False
    for line in lines:
        if 'Begin command "rhi.DumpMemory"' in line:
            in_section = True
            continue
        if 'End command "rhi.DumpMemory"' in line:
            break
        if not in_section:
            continue
        stat = parse_stat_line(line)
        if stat:
            rhi.append(stat)
        elif "total" in line.lower() and "MB" in line:
            m = re.search(r"([\d.]+)MB\s+total", line)
            if m:
                rhi.append({"name": "RHI Total", "value_mb": float(m.group(1))})
    return rhi


def parse_rhi_resources(lines):
    """Extract top resources from rhi.DumpResourceMemory."""
    resources = []
    in_section = False
    for line in lines:
        if 'Begin command "rhi.DumpResourceMemory"' in line:
            in_section = True
            continue
        if 'End command "rhi.DumpResourceMemory"' in line:
            break
        if not in_section:
            continue
        m = re.match(r"Name:\s+(.+?)\s+-\s+Type:\s+(\w+)\s+-\s+Size:\s+([\d.]+)\s+MB(?:\s+-\s+Flags:\s+(.+))?", line)
        if m:
            flags_raw = m.group(4)
            flags_set = set()
            if flags_raw:
                flags_set = {f.strip() for f in flags_raw.split("|") if f.strip()}
            resources.append({
                "name": m.group(1).strip(),
                "type": m.group(2),
                "size_mb": float(m.group(3)),
                "flags": flags_set,
                "flags_raw": flags_raw or "",
            })
        elif line.startswith("Shown") or line.startswith("Total tracked"):
            m_summary = re.search(r"Size:\s+([\d.]+)/([\d.]+)\s+MB", line)
            if m_summary:
                resources.append({
                    "name": "__summary__",
                    "shown_mb": float(m_summary.group(1)),
                    "total_mb": float(m_summary.group(2)),
                    "raw": line.strip(),
                })
    return resources


def parse_rhi_summaries(lines):
    """Extract named RHI resource summaries."""
    summaries = {}
    for i, line in enumerate(lines):
        m = re.match(r'MemReport: Begin command "rhi\.dumpresourcememory summary (.+)"', line)
        if m:
            key = m.group(1).strip()
            # Next line should have the summary
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                sm = re.search(r"Shown\s+(\d+)\s+entries.*?Size:\s+([\d.]+)/([\d.]+)\s+MB\s+\(([\d.]+)%", next_line)
                if sm:
                    summaries[key] = {
                        "entries": int(sm.group(1)),
                        "size_mb": float(sm.group(2)),
                        "total_mb": float(sm.group(3)),
                        "pct": float(sm.group(4)),
                    }
    return summaries


def parse_obj_list_summary(lines):
    """Extract class-level summary from obj list -resourcesizesort (first section only)."""
    classes = []
    in_section = False
    for line in lines:
        if 'Begin command "obj list -resourcesizesort"' in line:
            in_section = True
            continue
        if 'End command "obj list -resourcesizesort"' in line:
            break
        if not in_section:
            continue
        # Match class summary lines (indented, with class name and stats)
        parts = line.split()
        if len(parts) >= 8:
            try:
                # Try to parse as: ClassName Count NumKB MaxKB ResExcKB ...
                class_name = parts[0]
                count = int(parts[1])
                res_exc_kb = float(parts[4])
                if res_exc_kb > 100:  # only include classes with >100 KB
                    classes.append({
                        "class": class_name,
                        "count": count,
                        "num_kb": float(parts[2]),
                        "max_kb": float(parts[3]),
                        "res_exc_kb": res_exc_kb,
                        "res_exc_mb": round(res_exc_kb / 1024, 2),
                    })
            except (ValueError, IndexError):
                pass
    # Sort by res_exc_kb descending
    classes.sort(key=lambda x: x["res_exc_kb"], reverse=True)
    return classes


def parse_obj_list_class(lines, class_name, limit=None):
    """Parse per-asset obj list for a specific class.

    Looks for section: obj list class=<class_name> -resourcesizesort
    Returns all individual assets sorted by ResExcKB descending.

    UE5 obj list per-class format:
      Individual: <ClassName> <Path>  NumKB  MaxKB  ResExcKB  DedSysKB  DedVidKB  UnkKB  (6 numeric cols)
      Summary:    <ClassName>  Count  NumKB  MaxKB  ResExcKB  DedSysKB  DedVidKB  UnkKB  (7 numeric cols)
    ResExcKB is always the 3rd numeric column from the left (index 2).
    """
    assets = []
    in_section = False
    begin_pattern = f'obj list class={class_name}'

    for line in lines:
        lower = line.lower()
        if not in_section:
            if 'begin command "' in lower and begin_pattern.lower() in lower:
                in_section = True
            continue
        if 'end command "' in lower and begin_pattern.lower() in lower:
            break

        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            # Find numeric columns from the right
            num_cols = []
            for p in reversed(parts):
                try:
                    float(p)
                    num_cols.append(p)
                except ValueError:
                    break
            if len(num_cols) < 4:
                continue
            num_cols.reverse()

            name_parts = parts[:len(parts) - len(num_cols)]
            asset_name = " ".join(name_parts)
            if not asset_name or asset_name.startswith("Class"):
                continue

            # Skip summary line (class name without path, has 7 numeric cols with Count)
            # Summary lines have only the class name, no "/" path
            if "/" not in asset_name:
                continue

            # ResExcKB is always the 3rd numeric column (index 2): NumKB, MaxKB, ResExcKB, ...
            res_exc_kb = float(num_cols[2])
            if res_exc_kb < 1:  # skip tiny assets
                continue
            assets.append({
                "name": asset_name,
                "res_exc_kb": res_exc_kb,
                "res_exc_mb": round(res_exc_kb / 1024, 2),
            })
        except (ValueError, IndexError):
            continue

    assets.sort(key=lambda x: x["res_exc_kb"], reverse=True)
    return assets


def _detect_obj_list_classes(lines):
    """Auto-detect all 'obj list class=X' sections in the memreport."""
    import re
    pattern = re.compile(r'obj list class=(\w+)', re.IGNORECASE)
    classes = set()
    for line in lines:
        if 'obj list class=' in line.lower():
            m = pattern.search(line)
            if m:
                classes.add(m.group(1))
    return {cls: None for cls in sorted(classes)}


def parse_listtextures(lines):
    """Parse listtextures nonvt section for top 100 textures.

    UE5 listtextures format (each line):
    MaxWxH (SizeKB, Bias), CurrentWxH (SizeKB), Format, LODGroup, Path, Streaming, ...

    Example:
    4096x4096 (21888 KB, 0), 4096x4096 (21888 KB), PF_BC5, TEXTUREGROUP_WorldNormalMap, /Game/Tex/T_Foo.T_Foo, YES, ...
    """
    textures = []
    in_section = False

    # Pattern for UE5 listtextures format:
    # MaxWxH (MaxKB, Bias), CurrentWxH (CurrentKB), Format, LODGroup, Path, ...
    pat = re.compile(
        r"(\d+)x(\d+)\s+\((\d+)\s+KB,\s*[-\d?]+\),\s*"   # MaxRes (MaxKB, Bias), bias can be ? or number
        r"(\d+)x(\d+)\s+\((\d+)\s+KB\),\s*"               # CurrentRes (CurrentKB),
        r"(PF_\w+|\w+),\s*"                                 # Format,
        r"(TEXTUREGROUP_\w+),\s*"                            # LODGroup,
        r"(/[^,]+)"                                              # Path
        r"(?:,\s*(YES|NO))?"                                     # Optional Streaming flag
    )

    for line in lines:
        if 'Begin command "listtextures nonvt"' in line or 'Begin command "listtextures"' in line:
            in_section = True
            continue
        if in_section and ('End command "listtextures' in line):
            break
        if not in_section:
            continue

        m = pat.match(line)
        if m:
            current_kb = int(m.group(6))
            streaming_flag = m.group(10)  # YES, NO, or None
            textures.append({
                "name": m.group(9).strip().rstrip(","),
                "width": int(m.group(4)),
                "height": int(m.group(5)),
                "format": m.group(7),
                "lod_group": m.group(8),
                "size_kb": current_kb,
                "size_mb": round(current_kb / 1024, 2),
                "streaming": True if streaming_flag == "YES" else (False if streaming_flag == "NO" else None),
            })

    textures.sort(key=lambda x: x["size_kb"], reverse=True)
    return textures


def parse_rt_pool(lines):
    """Extract render target pool entries."""
    rts = []
    in_section = False
    for line in lines:
        if 'Begin command "r.DumpRenderTargetPoolMemory"' in line:
            in_section = True
            continue
        if 'End command "r.DumpRenderTargetPoolMemory"' in line:
            break
        if not in_section:
            continue
        m = re.match(r"\s+([\d.]+)MB\s+(.+?)(?:\s+Unused frames:\s+(\d+))?$", line)
        if m:
            size = float(m.group(1))
            if size >= 1.0:  # only include >= 1 MB
                rts.append({
                    "size_mb": size,
                    "description": m.group(2).strip(),
                })
        elif "total" in line.lower():
            m2 = re.search(r"([\d.]+)MB\s+total.*?([\d.]+)MB\s+used", line)
            if m2:
                rts.append({
                    "size_mb": float(m2.group(1)),
                    "description": f"RT Pool Total ({m2.group(2)} MB used)",
                    "is_summary": True,
                })
    return rts


def detect_platform(lines):
    """Detect platform from memreport content."""
    text = "\n".join(lines[:50])
    if "AGC" in text or "PS5" in text or "Prospero" in text or "AgcTransientHeaps" in text:
        return "PS5"
    if "D3D12" in text or "DXGI" in text:
        return "PC"
    return "Unknown"


def find_last_snapshot_start(lines):
    """Find the start of the last snapshot in multi-snapshot memreports.

    Memreports with multiple snapshots repeat the header pattern.
    Returns the line index where the last snapshot begins, or 0 if single snapshot.
    """
    snapshot_starts = []
    for i, line in enumerate(lines):
        # Snapshot boundaries are indicated by repeated header patterns
        if line.startswith("Changelist:") and i > 0:
            snapshot_starts.append(i)
    if len(snapshot_starts) > 1:
        return snapshot_starts[-1]
    return 0


def compute_derived(result):
    """Compute derived fields from parsed data."""
    derived = {}
    pm = result.get("platform_memory", {})
    fm = result.get("fmalloc", {})

    # Is dev build?
    config = result.get("header", {}).get("config", "")
    derived["is_dev_build"] = "Development" in config

    # FMalloc unused ratio
    fmalloc_total = fm.get("os_total_mb", 0)
    # Find FMallocUnused from llm_full
    fmalloc_unused = 0
    for tag in result.get("llm_full", []):
        if "FMallocUnused" in tag.get("name", "") or "FMalloc Unused" in tag.get("name", ""):
            fmalloc_unused = tag["value_mb"]
            break
    if fmalloc_total > 0:
        derived["fmalloc_unused_ratio"] = round(fmalloc_unused / fmalloc_total, 4)
        derived["fmalloc_unused_mb"] = round(fmalloc_unused, 1)
    else:
        derived["fmalloc_unused_ratio"] = None

    # Untracked ratio
    llm_total = 0
    untracked = 0
    for tag in result.get("llm_platform", []):
        name = tag.get("name", "")
        val = tag.get("value_mb", 0)
        # Match various names for total: "UsedPhysical", "Total", "Tracked Total"
        if name in ("UsedPhysical", "Total", "Tracked Total") and val > llm_total:
            llm_total = val
        if name == "Untracked" and val > 0:
            untracked = val
    derived["llm_total_mb"] = round(llm_total, 1) if llm_total else None
    derived["untracked_mb"] = round(untracked, 1) if untracked else None
    if llm_total > 0:
        derived["untracked_ratio"] = round(untracked / llm_total, 4)
    else:
        derived["untracked_ratio"] = None

    # Peak vs current gap
    current = pm.get("process_physical_used_mb", 0)
    peak = pm.get("process_physical_peak_mb", 0)
    if current > 0 and peak > 0:
        derived["peak_current_gap_mb"] = round(peak - current, 1)
    else:
        derived["peak_current_gap_mb"] = None

    # OS vs LLM gap
    os_phys = pm.get("process_physical_used_mb", 0)
    if os_phys > 0 and llm_total > 0:
        derived["os_vs_llm_gap_mb"] = round(os_phys - llm_total, 1)
    else:
        derived["os_vs_llm_gap_mb"] = None

    # Test equivalent MB (subtract ~500 from Dev)
    if current > 0:
        derived["test_equivalent_mb"] = round(current - 500, 1) if derived["is_dev_build"] else round(current, 1)
    else:
        derived["test_equivalent_mb"] = None

    # Peak test equivalent MB
    if peak > 0:
        derived["peak_test_equivalent_mb"] = round(peak - 500, 1) if derived["is_dev_build"] else round(peak, 1)
    else:
        derived["peak_test_equivalent_mb"] = None

    return derived


def compute_validation(result):
    """Pre-compute all validation checks."""
    checks = []
    pm = result.get("platform_memory", {})
    fm = result.get("fmalloc", {})
    derived = result.get("derived", {})

    os_phys = pm.get("process_physical_used_mb", 0)
    peak = pm.get("process_physical_peak_mb", 0)
    llm_total = derived.get("llm_total_mb") or 0

    # 1. OS vs LLM Total
    gap = derived.get("os_vs_llm_gap_mb")
    if gap is not None:
        if abs(gap) <= 500:
            status = "pass"
        elif abs(gap) <= 800:
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "name": "OS vs LLM Total",
            "formula": "LLM Total ≈ OS Physical ± 500 MB",
            "actual": f"Gap: {gap:+.1f} MB",
            "status": status,
        })

    # 2. FMalloc equation
    fmalloc_os = fm.get("os_total_mb", 0)
    fmalloc_llm = 0
    for tag in result.get("llm_platform", []):
        if tag.get("name") == "FMalloc":
            fmalloc_llm = tag["value_mb"]
            break
    if fmalloc_os > 0 and fmalloc_llm > 0:
        fmalloc_gap = fmalloc_llm - fmalloc_os
        if abs(fmalloc_gap) <= 600:
            status = "pass"
        elif abs(fmalloc_gap) <= 1000:
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "name": "FMalloc Equation",
            "formula": "FMalloc (Platform) ≈ FMallocBinned2 OS Total ± 600 MB",
            "actual": f"Platform: {fmalloc_llm:.1f} MB, Binned2 OS: {fmalloc_os:.1f} MB, Gap: {fmalloc_gap:+.1f} MB",
            "status": status,
        })

    # 3. FMalloc Unused ratio
    unused_ratio = derived.get("fmalloc_unused_ratio")
    if unused_ratio is not None:
        if unused_ratio <= 0.12:
            status = "pass"
        elif unused_ratio <= 0.15:
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "name": "FMalloc Unused Ratio",
            "formula": "FMalloc Unused / FMalloc OS Total ≤ 12%",
            "actual": f"{unused_ratio * 100:.1f}% ({derived.get('fmalloc_unused_mb', 0):.1f} MB)",
            "status": status,
        })

    # 4. Untracked ratio
    untracked_ratio = derived.get("untracked_ratio")
    if untracked_ratio is not None:
        if untracked_ratio <= 0.05:
            status = "pass"
        elif untracked_ratio <= 0.08:
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "name": "Untracked Ratio",
            "formula": "Untracked / LLM Total < 5%",
            "actual": f"{untracked_ratio * 100:.1f}% ({derived.get('untracked_mb', 0):.1f} MB)",
            "status": status,
        })

    # 5. Peak vs Current gap
    peak_gap = derived.get("peak_current_gap_mb")
    if peak_gap is not None:
        if peak_gap <= 2500:
            status = "pass"
        elif peak_gap <= 3500:
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "name": "Peak vs Current Gap",
            "formula": "Peak − Current ≤ 2,500 MB (streaming double-buffer)",
            "actual": f"{peak_gap:.1f} MB",
            "status": status,
        })

    # 6. Crash threshold check
    if peak > 0:
        if peak <= 11500:
            status = "pass"
        elif peak <= 12000:
            status = "warn"
        else:
            status = "fail"
        test_peak = peak - 500 if derived.get("is_dev_build") else peak
        checks.append({
            "name": "Crash Threshold (Peak)",
            "formula": "Peak Physical ≤ 12,000 MB (crash), target ≤ 11,500 MB (Test)",
            "actual": f"Peak: {peak:.1f} MB (Test equiv: {test_peak:.1f} MB)",
            "status": status,
        })

    # 7. Current budget check
    if os_phys > 0:
        test_equiv = derived.get("test_equivalent_mb", os_phys)
        if test_equiv <= 10500:
            status = "pass"
        elif test_equiv <= 11000:
            status = "warn"
        else:
            status = "fail"
        checks.append({
            "name": "Current Budget (Test 10,500 MB)",
            "formula": "Current (Test equiv) ≤ 10,500 MB",
            "actual": f"Current: {os_phys:.1f} MB (Test equiv: {test_equiv:.1f} MB)",
            "status": status,
        })

    return checks


def build_texture_breakdown(result):
    """Build detailed texture memory breakdown: NonStreaming, RenderTargets, NeverStream, Streaming.

    NonStreaming shows UAV-only RHI texture resources (TSR, VSM, DF, VT, etc.)
    that map to ELLMTag::Textures. RenderTargets shows RT/DS-flagged resources
    (Lumen lighting atlases, SceneColor, etc.) that map to ELLMTag::RenderTargets.

    Returns:
        {
            "nonstreaming": {
                "total_mb": float,        # UAV-only RHI textures → Textures LLM
                "categories": { ... }
            },
            "rendertargets": {
                "total_mb": float,        # RT/DS flagged → RenderTargets LLM
                "categories": { ... }
            },
            "neverstream": { "total_mb", "count", "by_group": {...} },
            "streaming":   { "total_mb", "count", "by_group": {...} }
        }
    """
    breakdown = {
        "nonstreaming": {"total_mb": 0, "categories": {}},
        "rendertargets": {"total_mb": 0, "categories": {}},
        "neverstream": {"total_mb": 0, "count": 0, "by_group": {}},
        "streaming": {"total_mb": 0, "count": 0, "by_group": {}},
    }

    # Known RT resource name prefixes for fallback when flags are unavailable
    KNOWN_RT_PREFIXES = {
        "SceneColor", "SceneDepth", "Translucency", "Subsurface",
    }
    KNOWN_RT_DOT_PREFIXES_PARTIAL = {
        "Lumen.SceneFinalLighting", "Lumen.SceneDirectLighting",
        "Lumen.SceneIndirectLighting", "Lumen.SceneNumFramesAccumulated",
        "Lumen.SceneDirectLighting.DiffuseLightingAndSecondMoment",
        "Lumen.SceneDirectLighting.NumFramesAccumulatedHistory",
    }

    def _is_render_target(resource):
        """Check if a resource is a render target (RT/DS flags or name heuristic)."""
        flags = resource.get("flags", set())
        # Flag-based detection
        if flags:
            for f in flags:
                if "RenderTargetable" in f or "DepthStencilTargetable" in f or f == "RT" or f == "DS":
                    return True
            return False
        # Fallback: name-based heuristic (for older memreports without Flags field)
        name = resource.get("name", "")
        if name in KNOWN_RT_PREFIXES:
            return True
        for prefix in KNOWN_RT_DOT_PREFIXES_PARTIAL:
            if name.startswith(prefix):
                return True
        return False

    # --- NonStreaming: ALL RHI Texture resources, dynamically grouped by name prefix ---
    # Extract prefix from resource name: take everything before the first "."
    # e.g. "TSR.History.Color" → "TSR", "Lumen.SceneFinalLighting" → "Lumen"
    # Names without "." (e.g. "AgcBackBuffer", "SceneColor") use the full name.

    # Build set of known LLM tag names for auto-matching prefix → LLM tag
    llm_tag_names = set()
    for tag in result.get("llm_full", []):
        tag_name = tag.get("name", "")
        if tag_name:
            llm_tag_names.add(tag_name)

    def _find_llm_tag(prefix):
        """Find matching LLM tag for a prefix. Returns tag name or None."""
        if prefix is None or len(prefix) < 3:
            return None
        # Direct match
        if prefix in llm_tag_names:
            return prefix
        # Fuzzy: "VirtualTexture" → "VirtualTextureSystem"
        # Require prefix to cover at least 50% of the tag name length
        for tag in llm_tag_names:
            if tag.startswith(prefix) and len(prefix) >= len(tag) * 0.5:
                return tag
            if prefix.startswith(tag) and len(tag) >= len(prefix) * 0.5:
                return tag
        return None

    def _extract_prefix(name):
        """Extract system prefix from RHI resource name.

        Strategy: use the first segment before "." as the group key.
        For names without "." (e.g. "AgcBackBuffer", "T_MapTest_DaYing_8k"):
          - Try prefix before "_" and check if it matches an LLM tag → use it
          - Otherwise return None (will be grouped as "Other")

        Special case: "VirtualTexture_Physical" / "VirtualTexture_PageTable"
        use "_" but are clearly system resources → handled by the "_" split
        matching "VirtualTextureSystem" LLM tag.
        """
        dot_pos = name.find(".")
        if dot_pos > 0:
            return name[:dot_pos]
        # No dot — try underscore prefix
        uscore_pos = name.find("_")
        if uscore_pos > 0:
            candidate = name[:uscore_pos]
            # Only use underscore prefix if it looks like a system name
            # (matches an LLM tag or a known engine system pattern)
            if _find_llm_tag(candidate):
                return candidate
        # No recognizable system prefix
        return None

    # --- Dedup: build set of listtextures short names to exclude from RHI nonstreaming ---
    # NeverStream/Streaming game textures appear in BOTH rhi.DumpResourceMemory (short name)
    # and listtextures (full path).  They must not be counted twice.  The neverstream/streaming
    # sections below already cover them via listtextures, so we skip them in the RHI loop.
    _listtex_short_names = set()
    for tex in result.get("_all_listtextures", []):
        path = tex.get("name", "")
        if "/" in path:
            short = path.rsplit("/", 1)[-1].split(".")[0]
        else:
            short = path.split(".")[0]
        if short:
            _listtex_short_names.add(short)

    ns_cats = {}   # nonstreaming (UAV-only) categories
    rt_cats = {}   # rendertarget categories
    for r in result.get("rhi_top_resources", []):
        if r.get("name") == "__summary__":
            continue
        if r.get("type") != "Texture":
            continue
        name = r["name"]
        if name.startswith("/"):
            continue
        if "ClusterPageData" in name:
            continue
        # Skip game textures already counted via listtextures (neverstream/streaming sections)
        if name in _listtex_short_names:
            continue

        prefix = _extract_prefix(name)
        group = prefix if prefix else "Other"
        llm_tag = _find_llm_tag(prefix)

        # Route to rendertargets or nonstreaming based on flags/heuristic
        if _is_render_target(r):
            target_cats = rt_cats
        else:
            target_cats = ns_cats

        if group not in target_cats:
            target_cats[group] = {"size_mb": 0, "llm_tag": llm_tag, "items": []}
        target_cats[group]["size_mb"] += r["size_mb"]
        target_cats[group]["items"].append({"name": name, "size_mb": r["size_mb"]})

    # Merge small categories (< 5 MB) into "Other" for both sections
    def _merge_small(cats):
        merged = {}
        other = {"size_mb": 0, "llm_tag": None, "items": []}
        for cat_name, cat_data in cats.items():
            if cat_data["size_mb"] < 5.0:
                other["size_mb"] += cat_data["size_mb"]
                other["items"].extend(cat_data["items"])
            else:
                merged[cat_name] = cat_data
        if other["size_mb"] > 0:
            if "Other" in merged:
                merged["Other"]["size_mb"] += other["size_mb"]
                merged["Other"]["items"].extend(other["items"])
            else:
                merged["Other"] = other
        for cat_data in merged.values():
            cat_data["size_mb"] = round(cat_data["size_mb"], 2)
            cat_data["items"].sort(key=lambda x: x["size_mb"], reverse=True)
        return merged

    ns_cats = _merge_small(ns_cats)
    rt_cats = _merge_small(rt_cats)

    ns_total_mb = round(sum(c["size_mb"] for c in ns_cats.values()), 2)
    breakdown["nonstreaming"]["categories"] = ns_cats
    breakdown["nonstreaming"]["total_mb"] = ns_total_mb

    rt_total_mb = round(sum(c["size_mb"] for c in rt_cats.values()), 2)
    breakdown["rendertargets"]["categories"] = rt_cats
    breakdown["rendertargets"]["total_mb"] = rt_total_mb

    # --- Streaming pool: from listtextures ---
    all_textures = result.get("_all_listtextures", [])
    for tex in all_textures:
        streaming = tex.get("streaming")
        group = tex.get("lod_group", "Unknown")
        size = tex.get("size_mb", 0)

        if streaming is False:  # NeverStream
            section = breakdown["neverstream"]
        elif streaming is True:  # Streaming
            section = breakdown["streaming"]
        else:
            continue  # unknown streaming status

        section["total_mb"] += size
        section["count"] += 1
        if group not in section["by_group"]:
            section["by_group"][group] = {"count": 0, "size_mb": 0}
        section["by_group"][group]["count"] += 1
        section["by_group"][group]["size_mb"] += size

    # Round values
    for key in ["neverstream", "streaming"]:
        breakdown[key]["total_mb"] = round(breakdown[key]["total_mb"], 2)
        for gd in breakdown[key]["by_group"].values():
            gd["size_mb"] = round(gd["size_mb"], 2)

    # NonStreaming and RenderTargets totals are set above from the split RHI textures.

    return breakdown


def build_transient_breakdown(result):
    """Build AgcTransientHeaps informational breakdown.

    Pure transient resources are INVISIBLE in memreport — they do not appear in
    rhi.DumpResourceMemory (which lists "non-transient" only), r.DumpRenderTargetPoolMemory,
    or listtextures. We CANNOT identify individual transient resources from memreport data.

    What we CAN provide:
    - The total committed heap size from the LLM tag
    - Known FastVRAM resource TYPES that are forced-transient on PS5 (informational, no sizes)
    - A note that the heap contents are aliased per-frame RDG resources

    Returns:
        {
            "total_mb": float,
            "note": str,
            "known_fastvram_types": [str, ...],
        }
    """
    breakdown = {
        "total_mb": 0,
        "note": "",
        "known_fastvram_types": [],
    }

    # Get AgcTransientHeaps LLM value
    transient_total = 0
    for tag in result.get("llm_platform", []):
        if "AgcTransientHeaps" in tag.get("name", "") or "Agc Transient Heaps" in tag.get("name", ""):
            transient_total = tag["value_mb"]
            break
    if transient_total <= 0:
        for tag in result.get("llm_full", []):
            if "AgcTransientHeaps" in tag.get("name", "") or "Agc Transient Heaps" in tag.get("name", ""):
                transient_total = tag["value_mb"]
                break
    if transient_total <= 0:
        return breakdown

    breakdown["total_mb"] = round(transient_total, 2)
    breakdown["note"] = (
        "Per-frame RDG transient resources (aliased, not visible in any memreport dump). "
        "Committed via 2MB virtual pages. "
        "Disable with r.RDG.TransientAllocator=0 and compare memory delta to measure."
    )
    breakdown["known_fastvram_types"] = [
        "SceneColor", "SceneDepth", "GBufferB", "HZB",
        "Bloom", "DOF", "MotionBlur", "Tonemap", "Upscale",
        "VolumetricFog", "DistanceField intermediates",
        "PostProcessMaterial", "ScreenSpaceShadowMask",
    ]

    return breakdown


def build_top_assets(result):
    """Build top assets grouped by category.

    Returns a dict: { category_name: [ {name, size_mb, source, type, ...}, ... ] }
    Each category has up to 10 items sorted by size descending.
    """
    categories = {}

    def add_asset(cat, name, size_mb, source, asset_type="", **extra):
        if cat not in categories:
            categories[cat] = {}
        key = name
        if key not in categories[cat] or size_mb > categories[cat][key]["size_mb"]:
            entry = {"name": name, "size_mb": size_mb, "source": source, "type": asset_type}
            entry.update(extra)
            categories[cat][key] = entry

    # Build listtextures short name set to distinguish game textures from engine UAV
    _listtex_names = set()
    for tex in result.get("listtextures", []):
        path = tex.get("name", "")
        if "/" in path:
            short = path.rsplit("/", 1)[-1].split(".")[0]
        else:
            short = path.split(".")[0]
        if short:
            _listtex_names.add(short)

    # Pre-aggregate RHI resources by (name, type) — same-name entries (e.g.
    # VirtualTexture_Physical ×11) are summed into one entry with a count.
    rhi_agg = {}
    for r in result.get("rhi_top_resources", []):
        if r.get("name") == "__summary__":
            continue
        name = r["name"]
        if "ClusterPageData" in name:
            continue
        key = (name, r.get("type", ""))
        if key not in rhi_agg:
            rhi_agg[key] = {"name": name, "size_mb": 0, "type": r.get("type", ""), "count": 0}
        rhi_agg[key]["size_mb"] += r["size_mb"]
        rhi_agg[key]["count"] += 1

    # From aggregated RHI resources — classify by name prefix or type
    for agg in rhi_agg.values():
        name = agg["name"]
        size = round(agg["size_mb"], 2)
        rtype = agg["type"]
        count = agg["count"]
        display_name = f"{name} (×{count})" if count > 1 else name

        # Classify RHI resources into categories by name prefix
        if name.startswith("Nanite."):
            cat = "Nanite"
        elif name.startswith("Lumen."):
            cat = "Lumen"
        elif name.startswith("Shadow."):
            cat = "Shadow"
        elif name.startswith("Hair."):
            cat = "Hair"
        elif name.startswith("DistanceFields."):
            cat = "DistanceFields"
        elif name.startswith("TSR."):
            cat = "TSR"
        elif name.startswith("GPUScene."):
            cat = "GPUScene"
        elif name.startswith("VirtualTexture"):
            cat = "UAV"
        elif rtype == "Texture" and not name.startswith("/"):
            # Game textures (in listtextures) → "Texture"; engine internal → "UAV"
            cat = "Texture" if name in _listtex_names else "UAV"
        elif rtype == "Buffer":
            cat = "Buffer"
        else:
            cat = "Other"
        add_asset(cat, display_name, size, "RHI", rtype)

    # From obj list per-class assets
    for class_name, assets in result.get("obj_list_assets", {}).items():
        for a in assets:
            add_asset(class_name, a["name"], a["res_exc_mb"], f"obj:{class_name}", class_name)

    # From listtextures
    for t in result.get("listtextures", []):
        add_asset("Texture", t["name"], t["size_mb"], "listtextures", "Texture",
                   format=t.get("format"))

    # Convert to sorted lists, all items per category
    result_cats = {}
    for cat, items_dict in categories.items():
        sorted_items = sorted(items_dict.values(), key=lambda x: x["size_mb"], reverse=True)
        result_cats[cat] = sorted_items

    return result_cats


def make_llm_summary(result):
    """Create a compact summary for LLM consumption (~3-5k tokens).

    Contains only what the LLM needs for analysis:
    - header, platform, has_llm_data
    - platform_memory, fmalloc (top-level only, no bins)
    - llm_platform tags (compact: name→value)
    - llm_full tags > 1 MB (compact: name→value)
    - derived, validation, top_assets
    - obj_list_summary top 15 classes
    """
    fm = result.get("fmalloc", {})
    fmalloc_compact = {k: v for k, v in fm.items() if k != "bins"}
    if fm.get("bins"):
        # Only include bins with >10 MB wasted
        big_bins = [b for b in fm["bins"] if b.get("wasted_mb", 0) >= 10]
        if big_bins:
            fmalloc_compact["notable_bins"] = big_bins

    # Compact LLM tags: just name→value_mb for tags > 0
    llm_platform_compact = {t["name"]: t["value_mb"] for t in result.get("llm_platform", []) if t["value_mb"] > 0}
    llm_full_compact = {t["name"]: t["value_mb"] for t in result.get("llm_full", []) if t["value_mb"] >= 1.0}

    return {
        "header": result.get("header", {}),
        "platform": result.get("platform"),
        "has_llm_data": result.get("has_llm_data"),
        "platform_memory": result.get("platform_memory", {}),
        "fmalloc": fmalloc_compact,
        "llm_platform": llm_platform_compact,
        "llm_full": llm_full_compact,
        "derived": result.get("derived", {}),
        "validation": result.get("validation", []),
        "top_assets": {
            cat: items[:10]
            for cat, items in result.get("top_assets", {}).items()
        },
        "obj_list_summary_top15": [
            {"class": c["class"], "count": c["count"], "res_exc_mb": c["res_exc_mb"]}
            for c in result.get("obj_list_summary", [])[:15]
        ],
        "rhi_summaries": result.get("rhi_summaries", {}),
        "texture_breakdown": result.get("texture_breakdown", {}),
        "transient_breakdown": result.get("transient_breakdown", {}),
    }


def main():
    parser = argparse.ArgumentParser(description="Parse UE5 memreport files into structured JSON")
    parser.add_argument("memreport", help="Path to the memreport file")
    parser.add_argument("--output", "-o", help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    path = Path(args.memreport)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    # Read file, try UTF-8 first, fall back to latin-1
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")

    lines = text.splitlines()

    # Multi-snapshot: only parse the last snapshot
    snapshot_start = find_last_snapshot_start(lines)
    if snapshot_start > 0:
        lines = lines[snapshot_start:]

    # Parse all sections
    result = {
        "source_file": str(path),
        "total_lines": len(lines),
        "platform": detect_platform(lines),
        "header": parse_header(lines),
        "platform_memory": parse_platform_memory(lines),
        "fmalloc": parse_fmalloc(lines),
    }

    llm_platform, llm_summary, llm_full = parse_llm_tags(lines)
    result["llm_platform"] = llm_platform
    result["llm_summary"] = llm_summary
    result["llm_full"] = llm_full
    result["has_llm_data"] = (
        any(t["value_mb"] > 0 for t in llm_platform)
        or any(t["value_mb"] > 0 for t in llm_full)
    )
    result["navigation"] = parse_navigation(lines)
    result["sections"] = find_sections(lines)
    result["rhi_dump"] = parse_rhi_dump(lines)
    result["rhi_top_resources"] = parse_rhi_resources(lines)
    result["rhi_summaries"] = parse_rhi_summaries(lines)
    result["obj_list_summary"] = parse_obj_list_summary(lines)
    all_listtextures = parse_listtextures(lines)
    result["listtextures"] = all_listtextures  # all for detail display
    result["_all_listtextures"] = all_listtextures    # all for breakdown (removed before output)
    result["rt_pool"] = parse_rt_pool(lines)

    # Per-asset obj lists — auto-detect all "obj list class=X" sections in the memreport
    obj_list_classes = _detect_obj_list_classes(lines)
    obj_list_assets = {}
    for cls, limit in obj_list_classes.items():
        assets = parse_obj_list_class(lines, cls, limit)
        if assets:
            obj_list_assets[cls] = assets
    result["obj_list_assets"] = obj_list_assets

    # Derived calculations
    result["derived"] = compute_derived(result)

    # Validation checks
    result["validation"] = compute_validation(result)

    # Texture breakdown (NonStreaming / NeverStream / Streaming)
    result["texture_breakdown"] = build_texture_breakdown(result)

    # Remove temporary all_listtextures (not needed in output)
    result.pop("_all_listtextures", None)

    # Transient heap breakdown (PS5)
    result["transient_breakdown"] = build_transient_breakdown(result)

    # Top assets merged list
    result["top_assets"] = build_top_assets(result)

    # Convert flags sets to sorted lists for JSON serialization
    for r in result.get("rhi_top_resources", []):
        if "flags" in r and isinstance(r["flags"], set):
            r["flags"] = sorted(r["flags"])

    # Output full parsed JSON (for render_report.py)
    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output_json, encoding="utf-8")
        print(f"Written to {out_path}", file=sys.stderr)

        # Also write compact LLM summary alongside
        llm_path = out_path.with_stem(out_path.stem + "_llm")
        llm_summary = make_llm_summary(result)
        llm_json = json.dumps(llm_summary, indent=2, ensure_ascii=False)
        llm_path.write_text(llm_json, encoding="utf-8")
        print(f"LLM summary written to {llm_path} ({len(llm_json)} bytes)", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
