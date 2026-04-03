---
name: quick-analyze-gpuprofile
description: >
 Use when the user has Unreal Engine ProfileGPU or profViz files and wants a quick standalone
 analysis, searchable HTML tree view, or JSON/CSV export without opening UE.
---

# Quick Analyze GPUProfile

## Overview

Use the bundled `profviz_tool.exe` to parse Unreal `*.profViz` files into:
- a searchable tree-based HTML report
- a full JSON hierarchy
- a flat CSV export

This skill is for quick local inspection when opening Unreal Editor is unnecessary or too heavy.

## Trigger

Use this skill when the user mentions:
- `profilegpu`
- `profViz`
- `*.profViz`
- "quick analyze GPU profile"
- "不用开 UE 看 profilegpu"
- "导出 GPU profile 的 html/json/csv"

Do NOT use for:
- Razor GPU / `.rzrgpu`
- PIX / `.wpix`
- RenderDoc / `.rdc`
- Requests that need engine instrumentation changes rather than file analysis

## Bundled Tool

Bundled executable:

`C:\Users\L\.claude\skills\quick-analyze-gpuprofile\scripts\profviz_tool.exe`

## Quick Workflow

Single file to explicit output directory:

```powershell
& "C:\Users\L\.claude\skills\quick-analyze-gpuprofile\scripts\profviz_tool.exe" parse "X:\path\capture.profViz" --output-dir "X:\path\out"
```

Batch a directory:

```powershell
& "C:\Users\L\.claude\skills\quick-analyze-gpuprofile\scripts\profviz_tool.exe" batch "X:\path\profileViz" --output-dir "X:\path\out"
```

Quick inspect with default sibling output directory:

```powershell
& "C:\Users\L\.claude\skills\quick-analyze-gpuprofile\scripts\profviz_tool.exe" "X:\path\capture.profViz"
```

This writes outputs into a sibling `profviz_output` directory and opens the HTML report.

## What to Return

When using this skill, report back:
- the generated HTML path
- the generated JSON/CSV paths when relevant
- the hottest obvious events if the user asked for analysis
