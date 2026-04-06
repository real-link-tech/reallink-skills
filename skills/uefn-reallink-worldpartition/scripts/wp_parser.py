"""wp_parser.py — World Partition Streaming Generation Log 解析器"""

import re
from wp_common import ActorDesc, CellActor, Cell, parse_cell_name

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
    return (0, 0, 0), (0, 0, 0)


_always_loaded_actor_cache: list[ActorDesc] = []


def _compute_always_loaded_bounds(cell: Cell, other_cells: list[Cell]):
    """Compute AlwaysLoaded cell bounds from its actors' RuntimeBounds,
    clamped per-actor to [10cm, 100m]."""
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    has_valid = False

    for ca in cell.actors:
        ad = None
        for a_db in _always_loaded_actor_cache:
            if a_db.name == ca.label or a_db.label == ca.label:
                ad = a_db
                break
        if not ad:
            continue
        bmin, bmax = ad.bounds_min, ad.bounds_max
        if bmin == (0, 0, 0) and bmax == (0, 0, 0):
            continue
        cx = (bmin[0] + bmax[0]) / 2
        cy = (bmin[1] + bmax[1]) / 2
        cz = (bmin[2] + bmax[2]) / 2
        raw_ex = abs(bmax[0] - bmin[0]) / 2
        raw_ey = abs(bmax[1] - bmin[1]) / 2
        raw_ez = abs(bmax[2] - bmin[2]) / 2
        ex = max(MIN_ACTOR_BOUND_EXTENT, min(raw_ex, MAX_ACTOR_BOUND_EXTENT))
        ey = max(MIN_ACTOR_BOUND_EXTENT, min(raw_ey, MAX_ACTOR_BOUND_EXTENT))
        ez = max(MIN_ACTOR_BOUND_EXTENT, min(raw_ez, MAX_ACTOR_BOUND_EXTENT))
        min_x = min(min_x, cx - ex)
        min_y = min(min_y, cy - ey)
        min_z = min(min_z, cz - ez)
        max_x = max(max_x, cx + ex)
        max_y = max(max_y, cy + ey)
        max_z = max(max_z, cz + ez)
        has_valid = True

    if not has_valid and other_cells:
        for c in other_cells:
            if c.cell_bounds_min != (0, 0, 0) or c.cell_bounds_max != (0, 0, 0):
                min_x = min(min_x, c.cell_bounds_min[0])
                min_y = min(min_y, c.cell_bounds_min[1])
                min_z = min(min_z, c.cell_bounds_min[2])
                max_x = max(max_x, c.cell_bounds_max[0])
                max_y = max(max_y, c.cell_bounds_max[1])
                max_z = max(max_z, c.cell_bounds_max[2])
                has_valid = True

    if has_valid:
        cell.cell_bounds_min = (min_x, min_y, min_z)
        cell.cell_bounds_max = (max_x, max_y, max_z)
        cell.content_bounds_min = (min_x, min_y, min_z)
        cell.content_bounds_max = (max_x, max_y, max_z)


# ─── Main Parser ─────────────────────────────────────────────────────────────

def parse_log(path: str) -> tuple[dict[str, ActorDesc], list[Cell]]:
    actors: dict[str, ActorDesc] = {}
    cells: list[Cell] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    current_cell: Cell | None = None
    persistent_cell: Cell | None = None
    in_persistent = False

    for line in lines:
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
                bmin, bmax = parse_bounds(line[line.index("RuntimeBounds:"):])
                ad.bounds_min, ad.bounds_max = bmin, bmax
            rg = re.search(r'RuntimeGrid:(\S+)', line)
            if rg:
                ad.runtime_grid = rg.group(1)
            actors[guid] = ad

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

        cm = _RE_CELL_HEADER.search(line)
        if cm:
            current_cell = Cell(name=cm.group(1), short_id=cm.group(2))
            parse_cell_name(current_cell)
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
                bmin, bmax = parse_bounds(line)
                current_cell.content_bounds_min, current_cell.content_bounds_max = bmin, bmax; continue
            if "Cell Bounds:" in line:
                bmin, bmax = parse_bounds(line)
                current_cell.cell_bounds_min, current_cell.cell_bounds_max = bmin, bmax; continue
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
