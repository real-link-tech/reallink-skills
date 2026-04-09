"""
ue_capture_query.py — Universal query tool for UE5 PIX event-list CSVs.

Usage:
    python ue_capture_query.py <events.csv> <command> [args...]

Commands:
    frames                      List all Frame N events and whether each has SceneRender
    passes                      List named render passes inside the SceneRender frame
    children <QID>              List named children of a given Queue ID
    trace <GID>                 Trace the parent chain of a given Global ID
    last-draw <QID>             Find the last Draw/Dispatch GID inside a pass (by Queue ID)
    last-draw-all               Find last Draw GID for all named passes in SceneRender
    present                     Find all Present events and their frame ancestry
    gids-around <GID> [N=20]    Show N events with GIDs surrounding a given GID

Examples:
    python ue_capture_query.py B_events.csv frames
    python ue_capture_query.py B_events.csv passes
    python ue_capture_query.py B_events.csv last-draw 146938
    python ue_capture_query.py B_events.csv trace 27792
    python ue_capture_query.py B_events.csv gids-around 27792 10
    python ue_capture_query.py B_events.csv last-draw-all
"""

import csv
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load(csv_path):
    rows = list(csv.DictReader(
        open(csv_path, encoding="utf-8-sig"), skipinitialspace=True
    ))
    by_qid = {r["Queue ID"].strip(): r for r in rows}
    by_gid  = {r["Global ID"].strip(): r for r in rows if r["Global ID"].strip()}
    with_gid = sorted(
        [(int(r["Global ID"].strip()), r["Queue ID"].strip(), r["Name"])
         for r in rows if r["Global ID"].strip()]
    )
    return rows, by_qid, by_gid, with_gid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API_CALLS = {
    "ResourceBarrier", "DrawIndexedInstanced", "DrawInstanced", "Dispatch",
    "CopyBufferRegion", "CopyTextureRegion", "WriteBufferImmediate",
    "SetPipelineState", "SetDescriptorHeaps", "SetGraphicsRootSignature",
    "SetComputeRootSignature", "SetGraphicsRoot32BitConstants",
    "SetComputeRoot32BitConstants", "EndQuery", "BeginQuery", "Close",
    "Reset", "Signal", "Wait", "ResolveQueryData", "IASetVertexBuffers",
    "IASetIndexBuffer", "RSSetViewports", "RSSetScissorRects",
    "OMSetRenderTargets", "ClearRenderTargetView", "ClearDepthStencilView",
    "SetComputeRootDescriptorTable", "SetGraphicsRootDescriptorTable",
    "SetComputeRootConstantBufferView", "DispatchRays",
    "FRDGBuilder::SubmitBufferUploads", "DiscardResource",
    "ClearUnorderedAccessViewUint",
}


def named_children(rows, parent_qid):
    return [r for r in rows
            if r["Parent"].strip() == parent_qid
            and r["Name"] not in API_CALLS]


def all_descendant_draws(rows, qid):
    """Return sorted list of (GID, name) for all Draw/Dispatch descendants."""
    result = []
    for r in rows:
        if r["Parent"].strip() == qid:
            gid = r["Global ID"].strip()
            if gid and ("Draw" in r["Name"] or "Dispatch" in r["Name"]):
                result.append((int(gid), r["Name"]))
            result.extend(all_descendant_draws(rows, r["Queue ID"].strip()))
    return result


def trace_chain(by_qid, qid, depth=0):
    r = by_qid.get(qid)
    if not r:
        return
    indent = "  " * depth
    print(f"{indent}QID={r['Queue ID']:>8}  GID={r['Global ID']:>8}  {r['Name']}")
    p = r["Parent"].strip()
    if p and p != "-1" and depth < 12:
        trace_chain(by_qid, p, depth + 1)


def find_scene_render_qid(rows):
    """Return QID of SceneRender - ViewFamilies inside the frame that HAS SceneRender."""
    for r in rows:
        if r["Name"] == "SceneRender - ViewFamilies":
            # Confirm it is inside a Frame that also has high queue IDs (Frame N+1)
            return r["Queue ID"].strip()
    return None


def find_scene_pass_qid(rows, scene_render_qid):
    """Return QID of RenderGraphExecute → Scene inside SceneRender."""
    rge = next(
        (r for r in rows
         if r["Parent"].strip() == scene_render_qid
         and "RenderGraphExecute" in r["Name"]),
        None
    )
    if not rge:
        return None
    scene = next(
        (r for r in rows
         if r["Parent"].strip() == rge["Queue ID"].strip()
         and r["Name"] == "Scene"),
        None
    )
    return scene["Queue ID"].strip() if scene else None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_frames(rows, by_qid, **_):
    frames = [r for r in rows if r["Name"].startswith("Frame ")]
    print(f"Found {len(frames)} frame(s):")
    for f in frames:
        fqid = f["Queue ID"].strip()
        children = [r for r in rows if r["Parent"].strip() == fqid]
        has_scene = any("SceneRender" in c["Name"] for c in children)
        has_present = any("Present" in c["Name"] for c in children)
        flag = ""
        if has_scene:
            flag += " [3D SceneRender ← use this for pass analysis]"
        if has_present:
            flag += " [has Present]"
        print(f"  {f['Name']:20s}  QID={fqid}{flag}")


def cmd_passes(rows, by_qid, **_):
    sr_qid = find_scene_render_qid(rows)
    if not sr_qid:
        print("SceneRender - ViewFamilies not found.")
        return
    scene_qid = find_scene_pass_qid(rows, sr_qid)
    if not scene_qid:
        print(f"Scene pass not found under SceneRender QID={sr_qid}")
        return
    print(f"SceneRender QID={sr_qid}  →  Scene QID={scene_qid}")
    print("Named passes inside Scene:")
    for c in named_children(rows, scene_qid):
        draws = all_descendant_draws(rows, c["Queue ID"].strip())
        draws.sort()
        last = draws[-1][0] if draws else "-"
        print(f"  QID={c['Queue ID']:>8}  last_draw_GID={str(last):>8}  {c['Name']}")


def cmd_children(rows, by_qid, args, **_):
    if not args:
        print("Usage: children <QID>")
        return
    qid = args[0]
    kids = named_children(rows, qid)
    print(f"Named children of QID={qid}  ({len(kids)}):")
    for c in kids:
        print(f"  QID={c['Queue ID']:>8}  GID={c['Global ID']:>8}  {c['Name']}")


def cmd_trace(rows, by_qid, by_gid, args, **_):
    if not args:
        print("Usage: trace <GID>")
        return
    gid = args[0]
    e = by_gid.get(gid)
    if not e:
        print(f"GID {gid} not found.")
        return
    print(f"Parent chain for GID={gid}  ({e['Name']}):")
    trace_chain(by_qid, e["Queue ID"].strip())


def cmd_last_draw(rows, by_qid, args, **_):
    if not args:
        print("Usage: last-draw <QID>")
        return
    qid = args[0]
    r = by_qid.get(qid)
    name = r["Name"] if r else "?"
    draws = all_descendant_draws(rows, qid)
    if not draws:
        print(f"No Draw/Dispatch descendants under QID={qid} ({name})")
        return
    draws.sort()
    print(f"Pass: {name}  (QID={qid})")
    print(f"  Total draws: {len(draws)}")
    print(f"  Last 5 GIDs: {[g for g,_ in draws[-5:]]}")
    print(f"  → Last draw GID = {draws[-1][0]}  ({draws[-1][1]})")


def cmd_last_draw_all(rows, by_qid, **_):
    sr_qid = find_scene_render_qid(rows)
    scene_qid = find_scene_pass_qid(rows, sr_qid) if sr_qid else None
    if not scene_qid:
        print("Could not find Scene pass. Run 'frames' and 'passes' first.")
        return
    print(f"Last Draw GID per pass (Scene QID={scene_qid}):")
    for c in named_children(rows, scene_qid):
        draws = all_descendant_draws(rows, c["Queue ID"].strip())
        if draws:
            draws.sort()
            print(f"  {draws[-1][0]:>8}  {c['Name']}")
        else:
            print(f"  {'–':>8}  {c['Name']}")


def cmd_present(rows, by_qid, with_gid, **_):
    presents = [(gid, qid, n) for gid, qid, n in with_gid if "Present" in n]
    print(f"Present events ({len(presents)}):")
    for gid, qid, n in presents:
        r = by_qid.get(qid)
        chain = []
        cur = r
        for _ in range(8):
            if not cur:
                break
            chain.append(cur["Name"])
            p = cur["Parent"].strip()
            if not p or p == "-1":
                break
            cur = by_qid.get(p)
        print(f"  GID={gid}  path: {' / '.join(reversed(chain))}")


def cmd_gids_around(with_gid, args, **_):
    if not args:
        print("Usage: gids-around <GID> [N=20]")
        return
    target = int(args[0])
    n = int(args[1]) if len(args) > 1 else 20
    idx = next((i for i, (g, _, _) in enumerate(with_gid) if g == target), None)
    if idx is None:
        print(f"GID {target} not found.")
        return
    lo = max(0, idx - n // 2)
    hi = min(len(with_gid), idx + n // 2 + 1)
    for gid, qid, name in with_gid[lo:hi]:
        marker = " ←" if gid == target else ""
        print(f"  GID={gid:>8}  {name}{marker}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMANDS = {
    "frames":        cmd_frames,
    "passes":        cmd_passes,
    "children":      cmd_children,
    "trace":         cmd_trace,
    "last-draw":     cmd_last_draw,
    "last-draw-all": cmd_last_draw_all,
    "present":       cmd_present,
    "gids-around":   cmd_gids_around,
}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)

    csv_path = sys.argv[1]
    command  = sys.argv[2]
    args     = sys.argv[3:]

    if not Path(csv_path).exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print("Available:", ", ".join(COMMANDS))
        sys.exit(1)

    rows, by_qid, by_gid, with_gid = load(csv_path)
    COMMANDS[command](rows=rows, by_qid=by_qid, by_gid=by_gid,
                      with_gid=with_gid, args=args)
