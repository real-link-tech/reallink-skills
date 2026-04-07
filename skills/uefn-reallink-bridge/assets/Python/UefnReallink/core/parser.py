"""core/parser.py — World Partition Streaming Generation Log 解析器"""

from __future__ import annotations

import re
from .common import ActorDesc, CellActor, Cell, parse_cell_name

# ─── Regex Patterns ───────────────────────────────────────────────────────────

_RE_ACTOR_DESC = re.compile(
    r'Guid:(\w+)'
    r'(?:.*?BaseClass:(\S+))?'
    r'(?:.*?NativeClass:(\S+))?'
    r'(?:.*?Name:(\S+))?'
    r'(?:.*?Label:(\S+))?'
    r'(?:.*?SpatiallyLoaded:(\w+))?'
    r'(?:.*?HLODRelevant:(\w+))?'
)
_RE_CELL_HEADER = re.compile(r'\[\+\]\s*Content of Cell\s+(\S+)\s+\((\w+)\)')
_RE_ACTOR_COUNT = re.compile(r'Actor Count:\s*(\d+)')
_RE_ALWAYS_LOADED = re.compile(r'Always Loaded:\s*(\w+)')
_RE_SPATIALLY_LOADED = re.compile(r'Spatially Loaded:\s*(\w+)')
_RE_IS_2D = re.compile(r'Is 2D:\s*(\w+)')
_RE_BOUNDS = re.compile(
    r'Min=\(X=([\d.\-]+)\s+Y=([\d.\-]+)\s+Z=([\d.\-]+)\),\s*'
    r'Max=\(X=([\d.\-]+)\s+Y=([\d.\-]+)\s+Z=([\d.\-]+)\)'
)
_RE_CELL_ACTOR = re.compile(r'\[\+\]\s*(/\S+:PersistentLevel\.(\S+))')
_RE_INSTANCE_GUID = re.compile(r'Instance Guid:\s*(\w+)')
_RE_PACKAGE = re.compile(r'Package:\s*(\S+)')

_RE_PERSISTENT_HEADER = re.compile(r'\[\+\]\s*Content of\s+(\S+)\s+Persistent Level')
_RE_PERSISTENT_COUNT = re.compile(r'Always loaded Actor Count:\s*(\d+)')
_RE_PERSISTENT_ACTOR_PATH = re.compile(r'Actor Path:\s*(/\S+:PersistentLevel\.(\S+))')
_RE_PERSISTENT_ACTOR_PKG = re.compile(r'Actor Package:\s*(\S+)')

MIN_ACTOR_BOUND_EXTENT = 10.0
MAX_ACTOR_BOUND_EXTENT = 10000.0


# ─── Helpers ──────────────────────────────────────────────────────────────────

def parse_bounds(text):
    m = _RE_BOUNDS.search(text)
    if m:
        return (
            (float(m.group(1)), float(m.group(2)), float(m.group(3))),
            (float(m.group(4)), float(m.group(5)), float(m.group(6))),
        )
    return None


def _clamp_bounds(bmin, bmax):
    cx = (bmin[0] + bmax[0]) / 2
    cy = (bmin[1] + bmax[1]) / 2
    cz = (bmin[2] + bmax[2]) / 2
    ex = max(MIN_ACTOR_BOUND_EXTENT, min(MAX_ACTOR_BOUND_EXTENT, (bmax[0] - bmin[0]) / 2))
    ey = max(MIN_ACTOR_BOUND_EXTENT, min(MAX_ACTOR_BOUND_EXTENT, (bmax[1] - bmin[1]) / 2))
    ez = max(MIN_ACTOR_BOUND_EXTENT, min(MAX_ACTOR_BOUND_EXTENT, (bmax[2] - bmin[2]) / 2))
    return (cx - ex, cy - ey, cz - ez), (cx + ex, cy + ey, cz + ez)


# ─── Always-Loaded Bounds ─────────────────────────────────────────────────────

_always_loaded_actor_cache: list[ActorDesc] = []


def _compute_always_loaded_bounds(persistent_cell: Cell, cells: list[Cell]):
    if not _always_loaded_actor_cache:
        return
    xs = [a.bounds_min[0] for a in _always_loaded_actor_cache] + \
         [a.bounds_max[0] for a in _always_loaded_actor_cache]
    ys = [a.bounds_min[1] for a in _always_loaded_actor_cache] + \
         [a.bounds_max[1] for a in _always_loaded_actor_cache]
    zs = [a.bounds_min[2] for a in _always_loaded_actor_cache] + \
         [a.bounds_max[2] for a in _always_loaded_actor_cache]
    if xs:
        persistent_cell.content_bounds_min = (min(xs), min(ys), min(zs))
        persistent_cell.content_bounds_max = (max(xs), max(ys), max(zs))
        persistent_cell.cell_bounds_min = persistent_cell.content_bounds_min
        persistent_cell.cell_bounds_max = persistent_cell.content_bounds_max


# ─── Main Parser ──────────────────────────────────────────────────────────────

def parse_log(log_path: str) -> tuple[dict[str, ActorDesc], list[Cell]]:
    actors: dict[str, ActorDesc] = {}
    cells: list[Cell] = []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    current_cell: Cell | None = None
    persistent_cell: Cell | None = None
    in_persistent = False

    for line in lines:
        # ── Actor Descriptors (no state machine — match any line with Guid:) ──
        m = _RE_ACTOR_DESC.search(line)
        if m and "Guid:" in line and ("NativeClass:" in line or "BaseClass:" in line):
            guid = m.group(1) or ""
            ad = ActorDesc(
                guid=guid, base_class=m.group(2) or "", native_class=m.group(3) or "",
                name=m.group(4) or "", label=m.group(5) or "",
                spatially_loaded=(m.group(6) or "true").lower() == "true",
                hlod_relevant=(m.group(7) or "false").lower() == "true",
            )
            if "RuntimeBounds:" in line:
                b = parse_bounds(line[line.index("RuntimeBounds:"):])
                if b:
                    ad.bounds_min, ad.bounds_max = _clamp_bounds(*b)
            rg = re.search(r'RuntimeGrid:(\S+)', line)
            if rg:
                ad.runtime_grid = rg.group(1)
            actors[guid] = ad

        # ── Persistent Level section ──
        pm = _RE_PERSISTENT_HEADER.search(line)
        if pm:
            map_name = pm.group(1)
            persistent_cell = Cell(
                name=f"{map_name}_AlwaysLoaded_L0_X0_Y0",
                short_id="ALWAYS_LOADED",
                always_loaded=True,
                spatially_loaded=False,
                grid_name=f"{map_name}_AlwaysLoaded",
                level=0, grid_x=0, grid_y=0,
            )
            in_persistent = True
            current_cell = None
            continue

        if in_persistent:
            pcm = _RE_PERSISTENT_COUNT.search(line)
            if pcm:
                persistent_cell.actor_count = int(pcm.group(1))
                continue
            pam = _RE_PERSISTENT_ACTOR_PATH.search(line)
            if pam:
                ca = CellActor(path=pam.group(1), label=pam.group(2))
                persistent_cell.actors.append(ca)
                continue
            ppk = _RE_PERSISTENT_ACTOR_PKG.search(line)
            if ppk and persistent_cell.actors:
                persistent_cell.actors[-1].package = ppk.group(1)
                continue
            if "Runtime Hash Set" in line or _RE_CELL_HEADER.search(line):
                in_persistent = False
                if persistent_cell and persistent_cell.actors:
                    _always_loaded_actor_cache.clear()
                    _always_loaded_actor_cache.extend(actors.values())
                    _compute_always_loaded_bounds(persistent_cell, cells)
                    cells.insert(0, persistent_cell)
                    persistent_cell = None

        # ── Cell sections ──
        cm = _RE_CELL_HEADER.search(line)
        if cm:
            current_cell = Cell(name=cm.group(1), short_id=cm.group(2))
            grid_name, level, gx, gy, _ = parse_cell_name(cm.group(1))
            current_cell.grid_name = grid_name
            current_cell.level = level
            current_cell.grid_x = gx
            current_cell.grid_y = gy
            cells.append(current_cell)
            continue

        if current_cell is not None:
            am = _RE_ACTOR_COUNT.search(line)
            if am: current_cell.actor_count = int(am.group(1)); continue
            alm = _RE_ALWAYS_LOADED.search(line)
            if alm: current_cell.always_loaded = alm.group(1).lower() == "true"; continue
            slm = _RE_SPATIALLY_LOADED.search(line)
            if slm: current_cell.spatially_loaded = slm.group(1).lower() == "true"; continue
            d2m = _RE_IS_2D.search(line)
            if d2m: current_cell.is_2d = d2m.group(1).lower() == "true"; continue
            if "Content Bounds:" in line:
                b = parse_bounds(line)
                if b:
                    current_cell.content_bounds_min, current_cell.content_bounds_max = b
                continue
            if "Cell Bounds:" in line:
                b = parse_bounds(line)
                if b:
                    current_cell.cell_bounds_min, current_cell.cell_bounds_max = b
                continue
            cam = _RE_CELL_ACTOR.search(line)
            if cam:
                current_cell.actors.append(CellActor(path=cam.group(1), label=cam.group(2))); continue
            igm = _RE_INSTANCE_GUID.search(line)
            if igm and current_cell.actors:
                current_cell.actors[-1].instance_guid = igm.group(1); continue
            pkm = _RE_PACKAGE.search(line)
            if pkm and current_cell.actors:
                current_cell.actors[-1].package = pkm.group(1); continue

    if persistent_cell and persistent_cell.actors and persistent_cell not in cells:
        _always_loaded_actor_cache.clear()
        _always_loaded_actor_cache.extend(actors.values())
        _compute_always_loaded_bounds(persistent_cell, cells)
        cells.insert(0, persistent_cell)

    return actors, cells
