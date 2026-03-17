---
name: memreport-analyze
description: Analyze UE5 memreport files using platform-specific knowledge bases. Produces a tree-structured memory breakdown from OS Process Physical down to individual assets, sorted by size, with optimization suggestions. Use this skill when the user mentions memreport, .memreport files, UE5 memory analysis, memory breakdown, memory budget, "分析内存", "内存报告", "内存优化", PS5 memory usage, OOM investigation, LLM tags, FMallocBinned2, or asks to understand where memory is going in an Unreal Engine build. DO NOT use for general memory profiling outside UE5, Valgrind/AddressSanitizer output, or non-UE memory dumps.
---

# Memreport Memory Analysis

## Preconditions
- A memreport text file is available (local path or pasted content).
- A platform knowledge base exists under this skill's `knowledge/` directory. Currently supported: **PS5**. For unsupported platforms, warn the user and proceed with best-effort analysis.

## Architecture

The analysis pipeline splits work between deterministic scripts and LLM reasoning:

```
memreport.txt
    │
    ▼
parse_memreport.py  ──►  parsed.json  (structured data, ~3-5k tokens)
                              │
                              ▼
                         LLM reads parsed.json, outputs analysis.json
                         (health summary + optimization suggestions only)
                              │
                              ▼
render_report.py  ◄── parsed.json + analysis.json  ──►  report.html
```

**Scripts handle**: data extraction, HTML generation, memory tree with budget bars, per-category asset tables.
**LLM handles only**: interpreting data patterns and writing optimization suggestions.

## Steps

Follow this procedure **in order**.

### Step 1 — Parse the memreport

Run the parsing script to extract structured data:

```bash
python .claude/skills/memreport-analyze/scripts/parse_memreport.py <memreport_file> -o parsed.json
```

The script outputs two files:
- `parsed.json` — full data for render_report.py (~115 KB)
- `parsed_llm.json` — compact summary for LLM (~8 KB)

**Read `parsed_llm.json`** (NOT parsed.json) to analyze the data. Key fields to check:

- `has_llm_data` — if `false`, the game was launched without `-llm`. Analysis will be limited.
- `platform` — confirms PS5/PC/Unknown
- `derived` — pre-computed ratios and flags (is_dev_build, test_equivalent_mb, peak_test_equivalent_mb, etc.)
- `top_assets` — per-category dict of top assets (each category has up to 10 items)

The script handles:
- Multi-snapshot detection (parses only the last snapshot)
- listtextures parsing (top 100 textures)
- Per-asset obj lists for SkeletalMesh (50), StaticMesh (30), Texture2D (50), GroomAsset (20)
- All derived calculations
- Per-category asset grouping (filters out Nanite.StreamingManager.ClusterPageData VA reservation)

### Step 2 — Analyze and output analysis.json

Read `parsed_llm.json` and produce `analysis.json` with **only** this schema:

```json
{
  "health_summary": "1-2 sentence overall memory health assessment",
  "scene_type": "open_world | boss_fight | town | menu",
  "suggestions": [
    {
      "priority": "P0",
      "finding": "What the data shows (with specific values)",
      "potential_saving_mb": 200,
      "action": "Specific change to make",
      "risk": "What might break or degrade",
      "tags": ["Textures"]
    }
  ],
  "notes": ["Additional observations"]
}
```

**Priority levels**: P0 (>200 MB saving) / P1 (50-200 MB) / P2 (<50 MB)

**When to load the knowledge base**: Only load `knowledge/ue5-ps5-memory-knowledge-v3.md` if you need to:
- Explain a tag's meaning or source code path
- Understand why values differ between data sources
- Investigate a specific anomaly

Most analyses can be completed from parsed_llm.json alone. The knowledge base is reference material, not a required read.

**Guidance for analysis**:

1. Check `derived.peak_test_equivalent_mb` — if it exceeds 12,000 MB (crash threshold), use peak values for all budget assessments. The health_summary should lead with peak risk.
2. Check `derived.test_equivalent_mb` against the 10,500 MB target — but when peak exceeds crash threshold, peak test-equivalent is the more critical number.
3. Check `derived.is_dev_build` — Dev builds are ~500 MB heavier than Test. The test-equivalent formula applies to both current and peak values.
4. Scan `top_assets` per category for abnormally large individual items
5. Compare tag values against budget references (built into the render script)
6. Use `llm_full` tags (not `llm_summary` — Summary has a known engine bug)

**CRITICAL**: `STATGROUP_LLM` (Summary) values are wrong due to a known engine bug. Always use `STATGROUP_LLMFULL` values silently — do NOT mention the Summary Bug in the report.

**CRITICAL**: `Nanite.StreamingManager.ClusterPageData` in RHI is a Virtual Address reservation (~4 GB), NOT physical memory. The parse script filters it out of top_assets. Always use the LLM Nanite tag value for physical commit. Do NOT report 4 GB Nanite usage.

Write the analysis.json using the Write tool.

### Step 3 — Generate the HTML report

Run the render script:

```bash
python .claude/skills/memreport-analyze/scripts/render_report.py parsed.json analysis.json -o <report.html> --lang zh
```

Use `--lang zh` for Chinese users (default), `--lang en` for English.

The output HTML file should be saved in the same directory as the memreport file, with the same filename but `.html` extension.

The render script deterministically generates:
- Overview cards (OS Physical, Peak, LLM Total, Available) with peak test-equivalent display
- Memory Tree with inline budget bars (colored bar + budget marker for each tag that has a budget)
  - Over-budget items highlighted in red/yellow
  - Textures expanded with sub-tags (TextureMetaData, VirtualTextureSystem) and top 8 textures from listtextures
- Per-category top assets tables (collapsible, sorted by total size)
- Data gaps detection
- Missing `-llm` warning banner (if applicable)
- LLM health summary and optimization suggestions (from analysis.json)

**Report characteristics:**
- Dark theme, inline CSS, single standalone HTML file
- HTML-based memory tree with flexbox rows and CSS bar charts
- Right-aligned numeric values, red for over-budget, green for normal
- Chinese/English labels based on `--lang`

## Memory budget (PS5 reference)

**Target: 10,500 MB total (Test) / 11,500 MB peak (Test)**

**CRASH THRESHOLD: 12,000 MB**. If Peak Physical exceeds 12 GB, the process will crash (OOM kill). When Peak exceeds 12 GB, base all budget assessments on Peak test-equivalent values.

Dev builds consume ~500 MB more than Test. Subtract ~500 MB from Dev memreport values to get the Test-equivalent value. This applies to **both** current and peak values:
- `test_equivalent_mb = current - 500` (Dev)
- `peak_test_equivalent_mb = peak - 500` (Dev)

Budget tiers (details hardcoded in render_report.py BUDGET_MAP):
- **Tier 1 Fixed (~1,650 MB)**: ProgramSize, LLMOverhead, OOMBackupPool, Shaders, AssetRegistry, ConfigSystem, calibration gap
- **Tier 2 Semi-fixed (~2,200 MB)**: AgcTransientHeaps, FMallocUnused, RHIMisc, SceneRender, Untracked
- **Tier 3 Floating pool (~6,650 MB)**: Textures, Meshes, Physics, UObject, Nanite, Audio, Animation, Navigation, Hair/Groom, UI, Lumen, DistanceFields, StreamingManager, etc.

The sum of all floating items must never exceed 6,650 MB. Individual tags can borrow from each other within the pool.

## Multi-report comparison mode

When the user provides two memreport files for comparison, follow this workflow:

### Step 1 — Parse both memreports

Run `parse_memreport.py` on each file:

```bash
python .claude/skills/memreport-analyze/scripts/parse_memreport.py <older.memreport> -o parsed_a.json
python .claude/skills/memreport-analyze/scripts/parse_memreport.py <newer.memreport> -o parsed_b.json
```

### Step 2 — Analyze comparison and output analysis.json

Read both `*_llm.json` files. Determine comparison type from metadata (CL number, Config, scene location). Write a single `analysis.json` that covers the comparison — focus the health_summary on the delta between the two reports, and list suggestions that address regressions or continued problem areas.

### Step 3 — Generate individual HTML reports (optional)

If the user wants per-report detail, render each using `render_report.py` with the shared analysis.json.

### Step 4 — Generate comparison HTML

Run the comparison render script:

```bash
python .claude/skills/memreport-analyze/scripts/render_comparison.py <parsed_a_llm.json> <parsed_b_llm.json> -o comparison.html [--lang zh|en]
```

The first argument should be the **older** report, the second the **newer** one. The script uses `--lang zh` by default.

Save the output HTML in the same directory as the memreport files.

The comparison report includes:
- **Overview cards**: OS Physical, Peak, Test-equiv, LLM Total, FMalloc metrics — side-by-side with colored deltas
- **Budget status table**: Current/Peak target pass/fail for both CLs
- **Top movers chart**: Tags with |delta| ≥ 5 MB, sorted by savings, with horizontal bar visualization
- **LLM Full tag detail table**: All tags with parent/child grouping (Textures→sub-tags, Meshes→sub-tags, Physics→Chaos sub-tags, UI→sub-tags), delta values and percentages, footer rows for FMalloc Unused / Untracked / Tracked Total / Total
- **Collapsible sections**: Texture group breakdown (NeverStream/Streaming with per-TEXTUREGROUP counts), Obj List class comparison (ResExcKB + counts), RHI category comparison

### Step 5 — Clean up

Remove intermediate files (parsed*.json, analysis.json) unless the user wants to keep them.

## Notes

- When the memreport has multiple snapshots, the parser automatically uses the last one
- If the user provides scene context (e.g., "battle scene"), use it to calibrate expectations
- For Nanite: always use LLM tag value (physical commit), NOT RHI VA reservation (misleading 4 GB). The parser filters ClusterPageData from top_assets automatically.
- Clean up intermediate files (parsed.json, analysis.json) after generating the HTML report unless the user wants to keep them
- **obj list parsing**: Individual asset lines have 6 numeric columns (NumKB, MaxKB, ResExcKB, DedSys, DedVid, Unk); class summary lines have 7 (extra Count). ResExcKB is always the 3rd numeric column (index 2). Distinguish by: individual lines contain "/" (asset path), summary lines do not.
- **SoundWave ResExcKB ≈ 0 is expected**: Wwise allocates audio memory through its own manager, not UObject resources. The Audio LLM tag captures the real memory. Do not expect SoundWave obj list to match Audio LLM values.
