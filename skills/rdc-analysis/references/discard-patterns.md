# DISCARD Overlay Patterns Reference

RenderDoc fills **discarded** resource regions with visible 64×8 pixel text overlays during replay. These are debugging visualizations, not actual render content.

## When DISCARD Overlays Appear

| API | Mechanism | Pattern Name |
|-----|-----------|-------------|
| D3D12 | `DiscardResource()` | DiscardCall |
| D3D12 | Layout `UNDEFINED` transition | UndefinedTransition |
| Vulkan | `VK_ATTACHMENT_LOAD_OP_DONT_CARE` | RenderPassLoad |
| Vulkan | `VK_ATTACHMENT_STORE_OP_DONT_CARE` | RenderPassStore |
| Vulkan | Transition from `VK_IMAGE_LAYOUT_UNDEFINED` | UndefinedTransition |
| OpenGL | `glInvalidateFramebuffer()` | InvalidateCall |

## Why Masking Is Required

DISCARD pixels are extreme values (0 or 255) that skew statistics, create false diffs, and contain no render information. **Exclude them before any pixel-level analysis** (diffs, stats, histograms).

## Recommended Tool

Use `scripts/image_diff.py` (bundled in this skill) for all image comparison and stats tasks — it handles DISCARD masking automatically. See SKILL.md for usage.

## Pattern Specifications

All 5 patterns are **64×8 binary bitmaps**. `#` = white, `.` = black. Patterns tile from top-left, aligned to 64×8 grid. May appear normal or inverted.

### RenderPassLoad

```
..#.....##...##..##....##....##..#..#.####..###..##..###..####..
..#....#..#.#..#.#.#...#.#..#..#.##.#..#...#....#..#.#..#.#....
..#....#..#.#..#.#..#..#..#.#..#.##.#..#...#....#..#.#..#.###..
..#....#..#.####.#..#..#..#.#..#.#.##..#...#....####.###..#....
..#....#..#.#..#.#.#...#.#..#..#.#.##..#...#....#..#.#..#.#....
..####..##..#..#.##....##....##..#..#..#....###.#..#.#..#.####..
................................................................
................................................................
```

### RenderPassStore

```
...###.####..##..###...##....##..#..#.####..###..##..###..####..
..#.....#...#..#.#..#..#.#..#..#.##.#..#...#....#..#.#..#.#....
...#....#...#..#.#..#..#..#.#..#.##.#..#...#....#..#.#..#.###..
....#...#...#..#.###...#..#.#..#.#.##..#...#....####.###..#....
.....#..#...#..#.#..#..#.#..#..#.#.##..#...#....#..#.#..#.#....
..###...#....##..#..#..##....##..#..#..#....###.#..#.#..#.####..
................................................................
................................................................
```

### UndefinedTransition

```
..#..#.#..#.##...####.####.####.#..#.####.##....####.#..#..###..
..#..#.##.#.#.#..#....#.....#...##.#.#....#.#....#...####.#....
..#..#.##.#.#..#.###..###...#...##.#.###..#..#...#...##.#.#....
..#..#.#.##.#..#.#....#.....#...#.##.#....#..#...#...#..#.#.##.
..#..#.#.##.#.#..#....#.....#...#.##.#....#.#....#...#..#.#..#.
...##..#..#.##...####.#....####.#..#.####.##....####.#..#..##..
................................................................
................................................................
```

### DiscardCall

```
..##...####..###..###...#...###..##...####.##...####.#..#..###..
..#.#...#...#....#.....#.#..#..#.#.#..#....#.#...#...####.#....
..#..#..#....#...#.....#.#..#..#.#..#.###..#..#..#...##.#.#....
..#..#..#.....#..#....#####.###..#..#.#....#..#..#...#..#.#.##.
..#.#...#......#.#....#...#.#..#.#.#..#....#.#...#...#..#.#..#.
..##...####.###...###.#...#.#..#.##...####.##...####.#..#..##..
................................................................
................................................................
```

### InvalidateCall

```
...####.#..#.#...#...#...#....####.##.....#...#####.####.##.....
....#...##.#.#...#..#.#..#.....#...#.#...#.#....#...#....#.#....
....#...##.#.#...#..#.#..#.....#...#..#..#.#....#...###..#..#...
....#...#.##..#.#..#####.#.....#...#..#.#####...#...#....#..#...
....#...#.##..#.#..#...#.#.....#...#.#..#...#...#...#....#.#....
...####.#..#...#...#...#.####.####.##...#...#...#...####.##.....
................................................................
................................................................
```

## Detection Algorithm

1. Convert PNG to grayscale → binarize (threshold > 128)
2. For each 64×8 aligned block, compare against all 5 patterns (normal + inverted)
3. Match ≥ 85% → mark block as discarded
4. Supplement: RGBA extreme values `(0,0,0,0)`, `(255,255,255,255)`, `(0,0,0,255)`, `(255,255,255,0)` adjacent to masked blocks

For the full implementation, see `scripts/image_diff.py` → `build_discard_mask()`.

## Edge Cases

- **Inverted patterns**: Some formats produce dark-on-bright. Always check both normal and inverted.
- **RGBA images**: Convert to grayscale before matching (pattern fills all channels uniformly).
- **Partial discard**: Only matched 64×8 blocks are flagged; remaining pixels are valid.
- **False positives**: 85% threshold minimizes them. Increase to 0.90 for noisy textures.
- **Tiling**: Always starts at (0,0), tiles in exact 64×8 steps.
