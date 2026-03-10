# RDC Export Output Format Reference

## Directory Structure

```
<capture_name>/
  event_list.md                       # Frame event hierarchy (start here)
  version.md                          # Script SHA1 hash (cache key)
  events/EID_<eid>.md                 # Per-drawcall/dispatch page
  pso/<Name>_<rid>_PSO.md            # Pipeline State Objects
  shaders/<Name>_<rid>_<stage>.md    # Shader disassembly (VS/PS/CS/HS/DS/GS)
  textures/EID_<eid>_TEX_<rid>_{before,after}.png
  render_targets/EID_<eid>_{RT<slot>,Depth}[_before].png
  buffers/<Name>_<rid>.md            # Full buffer (CB/VB/IB/UAV)
  buffers/EID_<eid>_BUF_<rid>_O<off>_L<len>_{before,after}.md
```

## Naming Conventions

- Resource IDs: integer strings (e.g., `42`, `12345`)
- Debug names sanitized: spaces/special chars → `_`
- Format: `<DebugName>_<ResourceID><Suffix>.<ext>` (no debug name → `<ResourceID><Suffix>.<ext>`)
- Shader stages: `_VS`, `_PS`, `_CS`, `_HS`, `_DS`, `_GS`; PSO: `_PSO`
- All cross-references use relative markdown links

## event_list.md

| Column | Description |
|--------|-------------|
| EID | Event ID |
| Name | `--` prefix = hierarchy depth; Drawcall/Dispatch rows link to `events/EID_*.md` |
| Type | **Drawcall**, **Dispatch**, Clear, Copy, Resolve, Present, Marker |
| Details | indices/instances for draws, groups for dispatches |

## events/EID_*.md

Sections in order:

1. **Pipeline** — PSO link, draw/dispatch parameters (Pre-Event, Indices, Instances)
2. **Shaders** — Stage / Resource ID / File link table
3. **\<Stage\> Bindings** — Per-stage register/name/type tables (SRV, UAV, CB)
4. **Render Targets** — Slot / Resource ID / Name / Format / Before / After PNG links
5. **Textures** — Resource ID / Name / Usage / Format / Before / After PNG links
6. **Buffers** — Resource ID / Name / Usage / Size / Bind Offset / Bind Length / Before / After links

## pso/*.md

Pipeline State Object configuration:

- Shader list with links
- Full creation parameters table: BlendState, RasterizerState, DepthStencilState, etc.

## shaders/*.md

- Entry point, disassembly target
- Resource bindings table (Register / Name / Type)
- Disassembly code block (HLSL/DXBC)

## buffers/*.md

Format depends on content:

| Type | Format |
|------|--------|
| Constant Buffer | Structured table: Name / Offset / Type / Value (from shader reflection) |
| Index Buffer | Table: Index / Offset / Value |
| Vertex Buffer | Per-vertex stride-aligned hex rows |
| Fallback | Full hex dump |

Per-event snapshots (`EID_*_BUF_*_{before,after}.md`) contain the bound range at a specific event with Phase (before/after), Bound Offset, and Bound Length metadata.
