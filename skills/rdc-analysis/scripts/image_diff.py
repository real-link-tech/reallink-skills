#!/usr/bin/env python3
"""
RDC Image Diff - Compare RenderDoc-exported images with DISCARD overlay masking.

Computes per-channel brightness statistics and pixel differences between two
exported PNG images, automatically detecting and excluding RenderDoc's DISCARD
overlay regions from all computations.

Requirements: Python 3.6+, Pillow (pip install Pillow)

Usage:
    # Compare two images (full report)
    python image_diff.py <image_a.png> <image_b.png>

    # Single image statistics
    python image_diff.py --stats <image.png>

    # Compare with diff heatmap output
    python image_diff.py <image_a.png> <image_b.png> --save-diff diff.png

    # Compare with mask visualization output
    python image_diff.py <image_a.png> <image_b.png> --save-mask mask.png

    # JSON output (for scripting)
    python image_diff.py <image_a.png> <image_b.png> --json
"""

from __future__ import print_function

import argparse
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# DISCARD pattern definitions (64x8 binary bitmaps from RenderDoc source)
# '#' = white/max-value pixel, '.' = black/min-value pixel
# See references/discard-patterns.md for detailed documentation.
# ---------------------------------------------------------------------------

PATTERN_W, PATTERN_H = 64, 8

_DISCARD_PATTERN_STRINGS = [
    # RenderPassLoad
    "..#.....##...##..##....##....##..#..#.####..###..##..###..####.."
    "..#....#..#.#..#.#.#...#.#..#..#.##.#..#...#....#..#.#..#.#....."
    "..#....#..#.#..#.#..#..#..#.#..#.##.#..#...#....#..#.#..#.###..."
    "..#....#..#.####.#..#..#..#.#..#.#.##..#...#....####.###..#....."
    "..#....#..#.#..#.#.#...#.#..#..#.#.##..#...#....#..#.#..#.#....."
    "..####..##..#..#.##....##....##..#..#..#....###.#..#.#..#.####.."
    "................................................................"
    "................................................................",
    # RenderPassStore
    "...###.####..##..###...##....##..#..#.####..###..##..###..####.."
    "..#.....#...#..#.#..#..#.#..#..#.##.#..#...#....#..#.#..#.#....."
    "...#....#...#..#.#..#..#..#.#..#.##.#..#...#....#..#.#..#.###..."
    "....#...#...#..#.###...#..#.#..#.#.##..#...#....####.###..#....."
    ".....#..#...#..#.#..#..#.#..#..#.#.##..#...#....#..#.#..#.#....."
    "..###...#....##..#..#..##....##..#..#..#....###.#..#.#..#.####.."
    "................................................................"
    "................................................................",
    # UndefinedTransition
    "..#..#.#..#.##...####.####.####.#..#.####.##....####.#..#..###.."
    "..#..#.##.#.#.#..#....#.....#...##.#.#....#.#....#...####.#....."
    "..#..#.##.#.#..#.###..###...#...##.#.###..#..#...#...##.#.#....."
    "..#..#.#.##.#..#.#....#.....#...#.##.#....#..#...#...#..#.#.##.."
    "..#..#.#.##.#.#..#....#.....#...#.##.#....#.#....#...#..#.#..#.."
    "...##..#..#.##...####.#....####.#..#.####.##....####.#..#..##..."
    "................................................................"
    "................................................................",
    # DiscardCall
    "..##...####..###..###...#...###..##...####.##...####.#..#..###.."
    "..#.#...#...#....#.....#.#..#..#.#.#..#....#.#...#...####.#....."
    "..#..#..#....#...#.....#.#..#..#.#..#.###..#..#..#...##.#.#....."
    "..#..#..#.....#..#....#####.###..#..#.#....#..#..#...#..#.#.##.."
    "..#.#...#......#.#....#...#.#..#.#.#..#....#.#...#...#..#.#..#.."
    "..##...####.###...###.#...#.#..#.##...####.##...####.#..#..##..."
    "................................................................"
    "................................................................",
    # InvalidateCall
    "...####.#..#.#...#...#...#....####.##.....#...#####.####.##....."
    "....#...##.#.#...#..#.#..#.....#...#.#...#.#....#...#....#.#...."
    "....#...##.#.#...#..#.#..#.....#...#..#..#.#....#...###..#..#..."
    "....#...#.##..#.#..#####.#.....#...#..#.#####...#...#....#..#..."
    "....#...#.##..#.#..#...#.#.....#...#.#..#...#...#...#....#.#...."
    "...####.#..#...#...#...#.####.####.##...#...#...#...####.##....."
    "................................................................"
    "................................................................",
]

_PATTERN_NAMES = [
    "RenderPassLoad", "RenderPassStore", "UndefinedTransition",
    "DiscardCall", "InvalidateCall",
]

# RGBA extreme values known to appear in DISCARD overlays.
# Derived from practical analysis of RDC-exported PNGs
# (see: water surface reflection brightness analysis experience).
_DISCARD_RGBA_EXTREMES = {
    (0, 0, 0, 0),
    (255, 255, 255, 255),
    (0, 0, 0, 255),
    (255, 255, 255, 0),
}


# ---------------------------------------------------------------------------
# DISCARD mask construction
# ---------------------------------------------------------------------------

def _build_pattern_refs():
    """Build 64x8 boolean reference arrays from pattern strings."""
    refs = []
    for s in _DISCARD_PATTERN_STRINGS:
        ref = []
        for y in range(PATTERN_H):
            row = []
            for x in range(PATTERN_W):
                row.append(s[y * PATTERN_W + x] == '#')
            ref.append(row)
        refs.append(ref)
    return refs


def build_discard_mask(image_path, match_threshold=0.85):
    """
    Detect DISCARD overlay regions in an exported RenderDoc PNG.

    Uses two complementary strategies:
      1. 64x8 tile pattern matching against all 5 known discard patterns
         (both normal and inverted). This is the primary, most robust method.
      2. RGBA extreme-value detection as a supplement for pixels within
         matched tiles that the grayscale binarization might miss.

    Args:
        image_path: Path to the PNG image.
        match_threshold: Min fraction of pixels matching a pattern for a
                         64x8 block to be flagged. Default 0.85.

    Returns:
        (mask, discard_type)
        - mask: list of lists [h][w], True = discarded pixel
        - discard_type: matched pattern name (str) or None
    """
    img_gray = Image.open(image_path).convert('L')
    w, h = img_gray.size
    gray_px = img_gray.load()
    refs = _build_pattern_refs()

    # Also load RGBA for extreme-value supplement
    img_rgba = Image.open(image_path).convert('RGBA')
    rgba_px = img_rgba.load()

    mask = [[False] * w for _ in range(h)]
    matched_type = None

    # Phase 1: 64x8 tile pattern matching
    for by in range(0, h, PATTERN_H):
        for bx in range(0, w, PATTERN_W):
            bh = min(PATTERN_H, h - by)
            bw = min(PATTERN_W, w - bx)
            total = bh * bw
            if total == 0:
                continue

            # Binarize block
            block = []
            for y in range(bh):
                row = []
                for x in range(bw):
                    row.append(gray_px[bx + x, by + y] > 128)
                block.append(row)

            best_rate = 0.0
            best_idx = -1

            for ri, ref in enumerate(refs):
                match = 0
                inv_match = 0
                for y in range(bh):
                    for x in range(bw):
                        if block[y][x] == ref[y][x]:
                            match += 1
                        else:
                            inv_match += 1
                rate = match / total
                inv_rate = inv_match / total
                best_local = max(rate, inv_rate)
                if best_local > best_rate:
                    best_rate = best_local
                    best_idx = ri

            if best_rate >= match_threshold:
                for y in range(bh):
                    for x in range(bw):
                        mask[by + y][bx + x] = True
                if matched_type is None and best_idx >= 0:
                    matched_type = _PATTERN_NAMES[best_idx]

    # Phase 2: RGBA extreme-value supplement
    # Flag isolated extreme-value pixels adjacent to already-masked regions.
    # This catches edge pixels that tile matching might miss due to
    # partial blocks at image boundaries.
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                continue
            rgba = rgba_px[x, y]
            if rgba in _DISCARD_RGBA_EXTREMES:
                # Check if any neighbor (4-connected) is already masked
                has_masked_neighbor = False
                for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny][nx]:
                        has_masked_neighbor = True
                        break
                if has_masked_neighbor:
                    mask[y][x] = True

    return mask, matched_type


# ---------------------------------------------------------------------------
# Per-channel statistics
# ---------------------------------------------------------------------------

def _channel_stats(pixels, mask, w, h, ch_index):
    """Compute stats for a single channel, excluding masked pixels."""
    total = 0
    val_sum = 0.0
    val_min = 255
    val_max = 0
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                continue
            v = pixels[x, y][ch_index]
            val_sum += v
            if v < val_min:
                val_min = v
            if v > val_max:
                val_max = v
            total += 1
    mean = (val_sum / total) if total > 0 else 0.0
    return {
        'count': total,
        'sum': val_sum,
        'mean': mean,
        'min': val_min if total > 0 else 0,
        'max': val_max if total > 0 else 0,
        # Normalized to [0, 1]
        'mean_norm': mean / 255.0,
    }


def image_stats(image_path, mask=None):
    """
    Compute per-channel and luminance statistics for an image,
    excluding masked (DISCARD) pixels.

    Args:
        image_path: Path to PNG image.
        mask: Pre-computed discard mask (list[h][w] of bool).
              If None, auto-detects via build_discard_mask().

    Returns:
        dict with per-channel stats and overall luminance.
    """
    img = Image.open(image_path).convert('RGBA')
    w, h = img.size
    pixels = img.load()

    if mask is None:
        mask, discard_type = build_discard_mask(image_path)
    else:
        discard_type = None

    total_px = w * h
    discarded = sum(1 for y in range(h) for x in range(w) if mask[y][x])
    valid = total_px - discarded

    ch_names = ['R', 'G', 'B', 'A']
    channels = {}
    for i, name in enumerate(ch_names):
        channels[name] = _channel_stats(pixels, mask, w, h, i)

    # Compute luminance: 0.2126*R + 0.7152*G + 0.0722*B (Rec.709)
    lum_sum = 0.0
    lum_min = 1.0
    lum_max = 0.0
    lum_count = 0
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                continue
            r, g, b, a = pixels[x, y]
            lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
            lum_sum += lum
            if lum < lum_min:
                lum_min = lum
            if lum > lum_max:
                lum_max = lum
            lum_count += 1

    lum_mean = (lum_sum / lum_count) if lum_count > 0 else 0.0

    return {
        'path': image_path,
        'width': w,
        'height': h,
        'total_pixels': total_px,
        'valid_pixels': valid,
        'discarded_pixels': discarded,
        'discard_ratio': discarded / total_px if total_px > 0 else 0.0,
        'discard_type': discard_type,
        'channels': channels,
        'luminance': {
            'mean': lum_mean,
            'min': lum_min if lum_count > 0 else 0.0,
            'max': lum_max if lum_count > 0 else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Image diff
# ---------------------------------------------------------------------------

def image_diff(path_a, path_b, save_diff=None, save_mask=None):
    """
    Compare two RDC-exported images with DISCARD masking.

    Detects DISCARD overlay in both images, computes per-channel and
    luminance differences on valid (non-discarded) pixels only.

    Args:
        path_a: Path to first image.
        path_b: Path to second image.
        save_diff: If set, save absolute diff heatmap PNG to this path.
        save_mask: If set, save combined discard mask PNG to this path.

    Returns:
        dict with comprehensive comparison results.
    """
    img_a = Image.open(path_a).convert('RGBA')
    img_b = Image.open(path_b).convert('RGBA')

    if img_a.size != img_b.size:
        return {
            'error': 'Image dimensions differ: %dx%d vs %dx%d' % (
                img_a.size[0], img_a.size[1], img_b.size[0], img_b.size[1]),
        }

    w, h = img_a.size
    px_a = img_a.load()
    px_b = img_b.load()

    # Build masks
    mask_a, type_a = build_discard_mask(path_a)
    mask_b, type_b = build_discard_mask(path_b)

    # Combined mask (either image discarded -> exclude)
    combined_mask = [[mask_a[y][x] or mask_b[y][x] for x in range(w)] for y in range(h)]

    total_px = w * h
    discarded_a = sum(1 for y in range(h) for x in range(w) if mask_a[y][x])
    discarded_b = sum(1 for y in range(h) for x in range(w) if mask_b[y][x])
    discarded_union = sum(1 for y in range(h) for x in range(w) if combined_mask[y][x])
    valid = total_px - discarded_union

    # Per-channel diff stats
    ch_names = ['R', 'G', 'B', 'A']
    ch_diff = {}
    for ci, cn in enumerate(ch_names):
        d_sum = 0.0
        d_max = 0
        d_nonzero = 0
        a_sum = 0.0
        b_sum = 0.0
        cnt = 0
        for y in range(h):
            for x in range(w):
                if combined_mask[y][x]:
                    continue
                va = px_a[x, y][ci]
                vb = px_b[x, y][ci]
                a_sum += va
                b_sum += vb
                d = abs(va - vb)
                d_sum += d
                if d > d_max:
                    d_max = d
                if d > 0:
                    d_nonzero += 1
                cnt += 1
        a_mean = (a_sum / cnt) if cnt > 0 else 0.0
        b_mean = (b_sum / cnt) if cnt > 0 else 0.0
        d_mean = (d_sum / cnt) if cnt > 0 else 0.0
        ch_diff[cn] = {
            'mean_a': a_mean,
            'mean_b': b_mean,
            'mean_a_norm': a_mean / 255.0,
            'mean_b_norm': b_mean / 255.0,
            'delta': b_mean - a_mean,
            'delta_norm': (b_mean - a_mean) / 255.0,
            'delta_pct': ((b_mean - a_mean) / a_mean * 100.0) if a_mean > 0 else 0.0,
            'abs_diff_mean': d_mean,
            'abs_diff_max': d_max,
            'nonzero_diff_count': d_nonzero,
        }

    # Luminance diff
    lum_a_sum = 0.0
    lum_b_sum = 0.0
    lum_d_sum = 0.0
    lum_d_max = 0.0
    lum_cnt = 0
    for y in range(h):
        for x in range(w):
            if combined_mask[y][x]:
                continue
            ra, ga, ba, _ = px_a[x, y]
            rb, gb, bb, _ = px_b[x, y]
            la = (0.2126 * ra + 0.7152 * ga + 0.0722 * ba) / 255.0
            lb = (0.2126 * rb + 0.7152 * gb + 0.0722 * bb) / 255.0
            lum_a_sum += la
            lum_b_sum += lb
            ld = abs(la - lb)
            lum_d_sum += ld
            if ld > lum_d_max:
                lum_d_max = ld
            lum_cnt += 1

    lum_a_mean = (lum_a_sum / lum_cnt) if lum_cnt > 0 else 0.0
    lum_b_mean = (lum_b_sum / lum_cnt) if lum_cnt > 0 else 0.0
    lum_d_mean = (lum_d_sum / lum_cnt) if lum_cnt > 0 else 0.0
    lum_delta = lum_b_mean - lum_a_mean
    lum_delta_pct = (lum_delta / lum_a_mean * 100.0) if lum_a_mean > 0 else 0.0

    # Save diff heatmap
    if save_diff:
        diff_img = Image.new('RGB', (w, h), (0, 0, 0))
        diff_px = diff_img.load()
        for y in range(h):
            for x in range(w):
                if combined_mask[y][x]:
                    diff_px[x, y] = (64, 0, 64)  # purple = discarded
                    continue
                ra, ga, ba, _ = px_a[x, y]
                rb, gb, bb, _ = px_b[x, y]
                dr = abs(rb - ra)
                dg = abs(gb - ga)
                db = abs(bb - ba)
                # Amplify differences for visibility (4x)
                diff_px[x, y] = (min(dr * 4, 255), min(dg * 4, 255), min(db * 4, 255))
        diff_img.save(save_diff)

    # Save mask visualization
    if save_mask:
        mask_img = Image.new('RGB', (w, h), (0, 128, 0))  # green = valid
        mask_px = mask_img.load()
        for y in range(h):
            for x in range(w):
                if mask_a[y][x] and mask_b[y][x]:
                    mask_px[x, y] = (255, 0, 0)    # red = both discarded
                elif mask_a[y][x]:
                    mask_px[x, y] = (255, 128, 0)  # orange = A discarded
                elif mask_b[y][x]:
                    mask_px[x, y] = (255, 255, 0)  # yellow = B discarded
                # else: green = both valid
        mask_img.save(save_mask)

    return {
        'image_a': path_a,
        'image_b': path_b,
        'dimensions': '%dx%d' % (w, h),
        'total_pixels': total_px,
        'valid_pixels': valid,
        'discarded_a': discarded_a,
        'discarded_b': discarded_b,
        'discarded_union': discarded_union,
        'discard_type_a': type_a,
        'discard_type_b': type_b,
        'channels': ch_diff,
        'luminance': {
            'mean_a': lum_a_mean,
            'mean_b': lum_b_mean,
            'delta': lum_delta,
            'delta_pct': lum_delta_pct,
            'abs_diff_mean': lum_d_mean,
            'abs_diff_max': lum_d_max,
        },
    }


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_stats_report(stats):
    """Format single-image stats as a human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append("Image Statistics (DISCARD-aware)")
    lines.append("=" * 60)
    lines.append("  File: %s" % stats['path'])
    lines.append("  Size: %dx%d (%d pixels)" % (
        stats['width'], stats['height'], stats['total_pixels']))
    lines.append("  Valid pixels: %d (%.1f%%)" % (
        stats['valid_pixels'],
        stats['valid_pixels'] / stats['total_pixels'] * 100 if stats['total_pixels'] else 0))
    lines.append("  Discarded pixels: %d (%.1f%%)" % (
        stats['discarded_pixels'],
        stats['discard_ratio'] * 100))
    if stats['discard_type']:
        lines.append("  Discard type: %s" % stats['discard_type'])
    lines.append("")
    lines.append("  Per-channel brightness (normalized 0-1):")
    for ch in ['R', 'G', 'B', 'A']:
        s = stats['channels'][ch]
        lines.append("    %s: mean=%.6f  min=%d  max=%d" % (
            ch, s['mean_norm'], s['min'], s['max']))
    lines.append("")
    lum = stats['luminance']
    lines.append("  Luminance (Rec.709): mean=%.6f  min=%.6f  max=%.6f" % (
        lum['mean'], lum['min'], lum['max']))
    return "\n".join(lines)


def _format_diff_report(result):
    """Format diff result as a human-readable report."""
    if 'error' in result:
        return "ERROR: %s" % result['error']

    lines = []
    lines.append("=" * 70)
    lines.append("Image Comparison Report (DISCARD-aware)")
    lines.append("=" * 70)
    lines.append("")
    lines.append("  Image A: %s" % result['image_a'])
    lines.append("  Image B: %s" % result['image_b'])
    lines.append("  Dimensions: %s" % result['dimensions'])
    lines.append("")

    lines.append("--- Pixel Coverage ---")
    lines.append("  Total pixels: %d" % result['total_pixels'])
    lines.append("  Valid pixels (both non-discarded): %d (%.1f%%)" % (
        result['valid_pixels'],
        result['valid_pixels'] / result['total_pixels'] * 100
        if result['total_pixels'] else 0))
    if result['discarded_a'] > 0:
        lines.append("  Discarded in A: %d  [%s]" % (
            result['discarded_a'],
            result['discard_type_a'] or 'unknown'))
    if result['discarded_b'] > 0:
        lines.append("  Discarded in B: %d  [%s]" % (
            result['discarded_b'],
            result['discard_type_b'] or 'unknown'))
    if result['discarded_union'] > 0:
        lines.append("  Excluded (union): %d" % result['discarded_union'])
    lines.append("")

    lines.append("--- Per-Channel Brightness (normalized 0-1) ---")
    lines.append("  %-4s  %-12s  %-12s  %-12s  %-8s" % (
        "Ch", "Mean A", "Mean B", "Delta", "Delta%"))
    lines.append("  " + "-" * 54)
    for ch in ['R', 'G', 'B', 'A']:
        d = result['channels'][ch]
        lines.append("  %-4s  %-12.6f  %-12.6f  %+.6f  %+.1f%%" % (
            ch, d['mean_a_norm'], d['mean_b_norm'],
            d['delta_norm'], d['delta_pct']))
    lines.append("")

    lum = result['luminance']
    lines.append("--- Luminance (Rec.709) ---")
    lines.append("  Mean A:     %.6f" % lum['mean_a'])
    lines.append("  Mean B:     %.6f" % lum['mean_b'])
    lines.append("  Delta:      %+.6f (%+.1f%%)" % (lum['delta'], lum['delta_pct']))
    lines.append("  Abs diff:   mean=%.6f  max=%.6f" % (
        lum['abs_diff_mean'], lum['abs_diff_max']))

    # Summary verdict
    lines.append("")
    lines.append("--- Summary ---")
    if abs(lum['delta_pct']) < 0.1:
        lines.append("  Result: Images are effectively IDENTICAL (luminance delta < 0.1%)")
    elif abs(lum['delta_pct']) < 1.0:
        lines.append("  Result: MINOR difference (luminance delta < 1%%)")
    elif abs(lum['delta_pct']) < 5.0:
        lines.append("  Result: NOTICEABLE difference (luminance delta %.1f%%)" %
                      lum['delta_pct'])
    else:
        direction = "BRIGHTER" if lum['delta'] > 0 else "DARKER"
        lines.append("  Result: SIGNIFICANT difference - B is %s (luminance %+.1f%%)" % (
            direction, lum['delta_pct']))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare RenderDoc-exported images with DISCARD overlay masking.")
    parser.add_argument('images', nargs='+', metavar='IMAGE',
                        help='One or two PNG image paths')
    parser.add_argument('--stats', action='store_true',
                        help='Single image statistics mode')
    parser.add_argument('--save-diff', metavar='PATH',
                        help='Save diff heatmap PNG (comparison mode)')
    parser.add_argument('--save-mask', metavar='PATH',
                        help='Save discard mask visualization PNG')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON')
    parser.add_argument('--threshold', type=float, default=0.85,
                        help='DISCARD pattern match threshold (default: 0.85)')
    args = parser.parse_args()

    if args.stats or len(args.images) == 1:
        # Single image stats mode
        for path in args.images:
            if not os.path.isfile(path):
                print("ERROR: File not found: %s" % path, file=sys.stderr)
                sys.exit(1)
            stats = image_stats(path)
            if args.json:
                # Remove non-serializable fields
                print(json.dumps(stats, indent=2, ensure_ascii=False))
            else:
                print(_format_stats_report(stats))
                print()
    elif len(args.images) == 2:
        # Comparison mode
        for path in args.images:
            if not os.path.isfile(path):
                print("ERROR: File not found: %s" % path, file=sys.stderr)
                sys.exit(1)
        result = image_diff(
            args.images[0], args.images[1],
            save_diff=args.save_diff,
            save_mask=args.save_mask)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(_format_diff_report(result))
            if args.save_diff:
                print("\n  Diff heatmap saved: %s" % args.save_diff)
            if args.save_mask:
                print("  Mask visualization saved: %s" % args.save_mask)
    else:
        parser.error("Provide 1 image (for --stats) or 2 images (for comparison)")


if __name__ == '__main__':
    main()
