"""
PIX GPU Frame Analyzer
Usage: python analyze_frame.py <events_timing.csv> [--top N] [--min-ms X]

Export the CSV first with:
  $pix open-capture frame.wpix save-event-list events_timing.csv `
       "--counters=TOP*" "--counters=EOP*" "--counters=Execution*"

IMPORTANT: pixtool emits "field, \"quoted name\"" with a space before the quote.
           Always use skipinitialspace=True when reading with csv.DictReader.
"""
import csv, sys, argparse
from collections import defaultdict

# ── CLI ─────────────────────────────────────────────────────────────────────
p = argparse.ArgumentParser()
p.add_argument("csv", help="events_timing.csv exported by pixtool")
p.add_argument("--top",    type=int,   default=40,  help="Top N events to list")
p.add_argument("--min-ms", type=float, default=0.05, help="Min ms for pass listing")
args = p.parse_args()

# ── Load ─────────────────────────────────────────────────────────────────────
with open(args.csv, encoding="utf-8-sig", errors="replace") as f:
    reader = csv.DictReader(f, skipinitialspace=True)  # <-- critical
    rows = list(reader)

rows = [{k.strip(): (v.strip() if v else "") for k, v in r.items()} for r in rows]
gid_map = {r["Global ID"]: r for r in rows if r["Global ID"]}

DUR = "TOP to EOP Duration (ns)"

def ms(r):
    try: return float(r.get(DUR, 0) or 0) / 1e6
    except: return 0.0

def chain(gid, depth=3):
    parts, r = [], gid_map.get(gid, {})
    for _ in range(depth):
        if not r: break
        parts.append(f'{r.get("Name","?")}({ms(r):.3f}ms)')
        r = gid_map.get(r.get("Parent", ""), {})
    return " > ".join(parts)

# ── Frame time ───────────────────────────────────────────────────────────────
print("=" * 70)
frame_rows = [r for r in rows if r["Name"].startswith("Frame ")]
for r in frame_rows:
    print(f"  Frame GPU time : {ms(r):.4f} ms   ({r['Name']})")
if not frame_rows:
    print("  (No 'Frame' marker found)")
print("=" * 70)
print()

# ── Pass breakdown (no leaf draws) ──────────────────────────────────────────
LEAF_NAMES = {"DrawIndexedInstanced", "DrawInstanced", "ExecuteIndirect",
              "WriteBufferImmediate", "ResourceBarrier", "ClearDepthStencilView",
              "ClearRenderTargetView", "CopyBufferRegion", "CopyResource",
              "Dispatch", "SetDescriptorHeaps"}

passes = [(r["Name"], r["Global ID"], ms(r)) for r in rows
          if ms(r) >= args.min_ms and r["Name"] not in LEAF_NAMES]
passes.sort(key=lambda x: -x[2])

print(f"=== Passes >= {args.min_ms} ms (excluding leaf commands) ===")
print(f'{"GPU ms":>9}  {"GID":<7}  Name')
print("-" * 75)
for name, gid, t in passes[:60]:
    print(f"{t:9.4f}  {gid:<7}  {name[:65]}")
print()

# ── Top N individual events ───────────────────────────────────────────────
timed = [(r["Name"], r["Global ID"], r["Parent"], ms(r)) for r in rows if ms(r) > 0]
timed.sort(key=lambda x: -x[3])
total_ns = sum(t * 1e6 for _, _, _, t in timed)

print(f"=== Top {args.top} Individual Events (all types) ===")
print(f'{"GPU ms":>9}  {"Cum%":>6}  {"GID":<7}  Name')
print("-" * 90)
accum = 0.0
for name, gid, parent, t in timed[: args.top]:
    pct = 100 * t * 1e6 / total_ns if total_ns else 0
    accum += pct
    print(f"{t:9.4f}  {accum:6.1f}%  {gid:<7}  {name[:65]}")
print()

# ── Wait / GPU stalls ─────────────────────────────────────────────────────
waits = sorted([r for r in rows if r["Name"] == "Wait"], key=ms, reverse=True)
print("=== GPU Wait Stalls ===")
for r in waits:
    if ms(r) > 0.001:
        print(f"  GID {r['Global ID']:<5}  {ms(r):.4f} ms  ctx: {chain(r['Parent'])}")
print()

# ── Lumen ────────────────────────────────────────────────────────────────
LUMEN_KW = ["Lumen", "ScreenProbe", "MeshSDF", "Heightfield",
            "RadianceCache", "DiffuseIndirect"]
lumen = [(r["Name"], ms(r)) for r in rows
         if any(kw in r["Name"] for kw in LUMEN_KW) and ms(r) > 0.01]
lumen.sort(key=lambda x: -x[1])
print("=== Lumen Sub-passes ===")
for name, t in lumen:
    print(f"  {t:7.4f} ms  {name[:70]}")
print()

# ── Bloom ────────────────────────────────────────────────────────────────
bloom = [(r["Name"], ms(r)) for r in rows
         if ("Bloom" in r["Name"] or "GaussianBlur" in r["Name"]) and ms(r) > 0]
bloom.sort(key=lambda x: -x[1])
if bloom:
    total_bloom = sum(t for _, t in bloom)
    print(f"=== Bloom / GaussianBlur  (total {total_bloom:.3f} ms) ===")
    for name, t in bloom:
        print(f"  {t:7.4f} ms  {name[:70]}")
    print()

# ── EnqueueCopy ──────────────────────────────────────────────────────────
ec = sorted([r for r in rows if "EnqueueCopy" in r["Name"]], key=ms, reverse=True)
print("=== EnqueueCopy ===")
for r in ec:
    p = gid_map.get(r["Parent"], {})
    print(f"  {ms(r):.4f} ms  {r['Name']}  (parent: {p.get('Name','?')})")
print()

# ── DrawIndexedInstanced summary ─────────────────────────────────────────
di_rows = sorted([r for r in rows if r["Name"] == "DrawIndexedInstanced"],
                 key=ms, reverse=True)
if di_rows:
    top_ms = ms(di_rows[0])
    print(f"=== DrawIndexedInstanced  ({len(di_rows)} calls, "
          f"top pipeline latency {top_ms:.4f} ms) ===")
    # Group by parent
    by_parent = defaultdict(list)
    for r in di_rows:
        by_parent[r["Parent"]].append(r)
    stats = [(pid, len(v), sum(ms(r) for r in v)) for pid, v in by_parent.items()]
    stats.sort(key=lambda x: -x[2])
    print(f'  {"#Draws":>7}  {"Accum TOP-EOP":>14}  Parent')
    for pid, cnt, total in stats[:10]:
        pname = gid_map.get(pid, {}).get("Name", "?") if pid else "(top-level)"
        print(f"  {cnt:7}  {total:14.4f} ms  {pname[:50]}")
    print()
