# Rendering Issue Diagnosis Patterns

Quick-reference for diagnosing common rendering problems using rdc_export output.

## Pattern 1: Black Screen / No Output

**Check**: RT After images in `events/EID_*.md` — are they all black?

1. Verify shaders are bound (VS + PS must be present)
2. Check Pipeline: indices > 0, instances > 0
3. Check VB/IB: non-zero data bound
4. Check Viewport in PSO: width/height > 0
5. If RT Before shows DISCARD overlay — expected (don't-care load), focus on After image

**Common causes**: Missing shader, zero vertex count, 0×0 viewport, depth test rejecting all fragments.

## Pattern 2: Wrong Colors / Material Issues

**Check**: Textures section — correct textures on correct SRV slots?

1. Open texture Before images — do they contain expected content?
2. Cross-reference SRV register names with shader expectations
3. Open CB buffer files — verify material parameters (color, roughness, matrices)

**Common causes**: Wrong texture on SRV slot, CB not updated, texture format mismatch.

## Pattern 3: Geometry Issues (Missing/Distorted)

**Check**: VB/IB data and CB transform matrices.

1. VB stride matches expected vertex format
2. IB index values in valid range
3. World/View/Projection matrices — look for identity, NaN, infinity
4. Viewport MinDepth/MaxDepth (typically 0.0/1.0), Width/Height matching RT dimensions

**Common causes**: Wrong transform matrix, VB stride mismatch, IB out-of-range, incorrect viewport.

## Pattern 4: Depth / Z-Fighting

**Check**: Depth target Before vs After, PSO depth stencil state.

1. Is depth cleared before the pass?
2. DepthEnable = True, DepthFunc = Less/LessEqual, DepthWriteMask = All
3. Near/far plane values reasonable (projection matrix [2][2] and [3][2])
4. If Depth Before shows DISCARD overlay — mask before computing depth diffs

**Common causes**: Depth test disabled, wrong comparison function, near plane too close, depth not cleared.

## Pattern 5: Alpha / Transparency

**Check**: PSO BlendState parameters.

1. BlendEnable = True for transparent objects
2. SrcBlend / DestBlend / BlendOp values correct
3. Transparency pass draws back-to-front (check EID ordering)
4. Shader outputs alpha (check disassembly)

**Common causes**: Blend disabled, wrong blend factors, incorrect render order, shader not writing alpha.

## Pattern 6: Compute Shader Issues

**Check**: UAV Before/After in `events/EID_*.md`.

1. Dispatch dimensions correct (total threads = groups × thread group size)
2. UAV output bound, SRV input bound, CB parameters correct
3. Check UAV buffer before/after — did compute write expected data?

**Common causes**: Wrong dispatch dimensions, UAV not bound, input not ready, thread group mismatch.

## Pattern 7: Render Pass Organization

Use `event_list.md` to understand frame structure:

1. Marker hierarchy (`--` indentation) shows major passes (Shadow, GBuffer, Lighting, PostProcess, UI)
2. Count draw calls per pass to identify heavy passes
3. Look for duplicate passes, excessive draw counts, missing expected passes

## Pattern 8: Resource State Tracking

Trace a specific resource across the frame:

1. Search for resource ID across `events/EID_*.md` files
2. Check Before/After at each event, note Usage (SRV, UAV, RT)
3. Build timeline: first written → then read → check for missing barriers
4. If Before shows DISCARD overlay — resource was intentionally invalidated at that point

**DISCARD overlay handling**: When any exported image shows DISCARD patterns, mask those pixels before pixel analysis. See [discard-patterns.md](discard-patterns.md).

## Quick Reference

| Issue | Primary Check | Secondary Check |
|-------|--------------|-----------------|
| Black screen | RT After images | Shader bindings, viewport |
| Wrong color | Texture SRV content | CB material values |
| Missing geometry | VB/IB data | Transform matrices in CB |
| Z-fighting | Depth Before/After | PSO depth stencil state |
| Transparency | PSO blend state | Render order in event_list |
| Compute wrong | UAV Before/After | Dispatch dimensions, CB params |
| Performance | Draw count per pass | Instance count, index count |
| DISCARD overlay | Mask before analysis | See [discard-patterns.md](discard-patterns.md) |
