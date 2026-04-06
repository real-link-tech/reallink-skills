"""wp_bridge.py — UefnReallink 桥接 + 内存采集 + Grid 参数获取"""

import os
import json
import math
from urllib.request import Request, urlopen
from urllib.error import URLError

from wp_common import Cell

# ─── UefnReallink HTTP Bridge ────────────────────────────────────────────────

UEFN_HOST = os.environ.get("UEFN_HOST", "127.0.0.1")
UEFN_PORT = int(os.environ.get("UEFN_PORT", "9877"))
UEFN_URL = f"http://{UEFN_HOST}:{UEFN_PORT}/execute"


def uefn_execute(code: str) -> dict:
    req = Request(UEFN_URL, data=code.encode("utf-8"), method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        return {"success": False, "error": f"Cannot connect to UefnReallink: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Editor Commands ─────────────────────────────────────────────────────────

def trigger_dump():
    return uefn_execute(
        'import unreal\n'
        'unreal.SystemLibrary.execute_console_command(None, "wp.Editor.DumpStreamingGenerationLog")\n'
        'result = "dump triggered"'
    )


def find_latest_log() -> str | None:
    resp = uefn_execute(
        'import glob, os\n'
        'log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), '
        '"UnrealEditorFortnite", "Saved", "Logs", "WorldPartition")\n'
        'files = sorted(glob.glob(os.path.join(log_dir, "StreamingGeneration-*.log")), '
        'key=os.path.getmtime, reverse=True)\n'
        'result = files[0] if files else None'
    )
    if resp.get("success") and resp.get("result"):
        return resp["result"]
    return None


def select_and_focus(actor_name: str):
    safe = actor_name.replace('"', '\\"')
    uefn_execute(
        'import unreal\n'
        'actors = unreal.EditorLevelLibrary.get_all_level_actors()\n'
        f'target = next((a for a in actors if a.get_name() == "{safe}"), None)\n'
        'if target:\n'
        '    unreal.EditorLevelLibrary.set_selected_level_actors([target])\n'
        '    unreal.SystemLibrary.execute_console_command(None, "CAMERA ALIGN ACTIVEVIEWPORT")\n'
        '    result = "Selected: " + target.get_name()\n'
        'else:\n'
        f'    result = "Not found: {safe}"'
    )
    try:
        import ctypes, ctypes.wintypes
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        hwnd = None
        def _cb(h, _):
            nonlocal hwnd
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                if "Unreal Editor" in buf.value:
                    hwnd = h
                    return False
            return True
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        if hwnd:
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def browse_to_asset(asset_path: str):
    """Select asset in Content Browser by loading it and syncing with full object path."""
    safe = asset_path.replace("'", "\\'")
    resp = uefn_execute(
        'import unreal\n'
        f"asset = unreal.EditorAssetLibrary.load_asset('{safe}')\n"
        'if asset:\n'
        '    full = asset.get_path_name()\n'
        '    unreal.EditorAssetLibrary.sync_browser_to_objects([full])\n'
        '    result = "Browsed: " + full\n'
        'else:\n'
        f'    result = "Not found: {safe}"'
    )
    print(f"[browse_to_asset] {asset_path} -> {resp.get('result', resp.get('error', '?'))}")


def open_asset_editor(asset_path: str):
    """Open asset in its editor (Material Editor, Static Mesh Editor, etc.)."""
    pkg = asset_path.split(".")[0] if "." in asset_path else asset_path
    safe = pkg.replace("'", "\\'")
    resp = uefn_execute(
        'import unreal\n'
        f"asset = unreal.EditorAssetLibrary.load_asset('{safe}')\n"
        'if asset:\n'
        '    subsys = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)\n'
        '    subsys.open_editor_for_assets([asset])\n'
        '    result = "Opened: " + asset.get_path_name()\n'
        'else:\n'
        f'    result = "Not found: {safe}"'
    )
    print(f"[open_asset_editor] {asset_path} -> {resp.get('result', resp.get('error', '?'))}")


# ─── Camera ──────────────────────────────────────────────────────────────────

def fetch_camera_info() -> dict | None:
    """Return {"x", "y", "z", "yaw"} or None on failure."""
    resp = uefn_execute(
        'loc, rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()\n'
        'result = {"x": loc.x, "y": loc.y, "z": loc.z, "yaw": rot.yaw}'
    )
    if resp.get("success") and resp.get("result"):
        return resp["result"]
    return None


# ─── Grid Parameters ─────────────────────────────────────────────────────────

def fetch_grid_params() -> dict:
    """Fetch per-grid CellSize and LoadingRange via reflection."""
    code = '''
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
ws = world.get_world_settings()
wp = ws.get_editor_property('world_partition')
wp_path = wp.get_path_name()

grid_params = {}
try:
    hash_set = None
    for obj in unreal.ObjectIterator(unreal.Object):
        try:
            if obj is None:
                continue
            cls = obj.get_class()
            if cls is None:
                continue
            cn = cls.get_name()
            if cn == 'WorldPartitionRuntimeHashSet' and wp_path in obj.get_path_name():
                hash_set = obj
                break
        except Exception:
            continue

    if hash_set:
        partitions = hash_set.get_editor_property('RuntimePartitions')
        for p in partitions:
            name = str(p.get_editor_property('Name'))
            ml = p.get_editor_property('MainLayer')
            if ml:
                cs = int(ml.get_editor_property('CellSize'))
                lr = int(ml.get_editor_property('LoadingRange'))
                grid_params[name] = {"cell_size": cs, "loading_range": lr}
except Exception as e:
    grid_params["_error"] = str(e)

result = grid_params
'''
    resp = uefn_execute(code)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return {}


def infer_grid_params_from_cells(cells: list[Cell]) -> dict:
    """Fallback: infer grid params from cell bounds when reflection fails."""
    grid_params = {}
    for c in cells:
        if c.always_loaded or not c.spatially_loaded or c.level != 0:
            continue
        w = abs(c.cell_bounds_max[0] - c.cell_bounds_min[0])
        if w > 0 and c.grid_name not in grid_params:
            grid_params[c.grid_name] = {"cell_size": int(w), "loading_range": int(w)}
    return grid_params


def fetch_grid_params_with_fallback(cells: list[Cell]) -> dict:
    """Try reflection first, fall back to cell bounds inference."""
    gp = fetch_grid_params()
    valid = {k: v for k, v in gp.items() if isinstance(v, dict) and k != "_error"}
    if valid:
        return valid
    return infer_grid_params_from_cells(cells)


# ─── Memory Data Collection (cached, multi-stage) ────────────────────────────

import tempfile
from collections import deque

_CACHE_DIR = os.path.join(tempfile.gettempdir(), "wp_memory_cache")

# ── UEFN code: fetch actor direct refs via AssetRegistry deps on actor package ──
_ACTOR_REFS_CODE = '''
import unreal
LABELS = REQUESTED_LABELS
actors = unreal.EditorLevelLibrary.get_all_level_actors()
amap = {}
for a in actors:
    n = a.get_name()
    if n in LABELS:
        amap[n] = a

ar = unreal.AssetRegistryHelpers.get_asset_registry()
dep_opts = unreal.AssetRegistryDependencyOptions()
dep_opts.include_hard_package_references = True
dep_opts.include_soft_package_references = False
dep_opts.include_searchable_names = False
dep_opts.include_hard_management_references = False
dep_opts.include_soft_management_references = False

actor_refs = {}
for label in LABELS:
    actor = amap.get(label)
    if not actor:
        continue
    pkg = actor.get_outermost().get_path_name()
    raw = ar.get_dependencies(pkg, dep_opts)
    if raw:
        actor_refs[label] = [str(d) for d in raw if not str(d).startswith('/Script/')]
    else:
        actor_refs[label] = []
result = actor_refs
'''

# ── UEFN code: batch query deps + sizes for a list of packages ──
_DEPS_SIZES_CODE = '''
import ctypes
import unreal

ENGINE_DLL = "UnrealEditorFortnite-Engine-Win64-Shipping.dll"
SIZEOF_RES = 248
VTABLE_SLOT = 69

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetModuleHandleW.restype = ctypes.c_uint64
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
k32.GetProcAddress.restype = ctypes.c_uint64
k32.GetProcAddress.argtypes = [ctypes.c_uint64, ctypes.c_char_p]

h = k32.GetModuleHandleW(ENGINE_DLL)
ctor_a = k32.GetProcAddress(h, b"??0FResourceSizeEx@@QEAA@W4Type@EResourceSizeMode@@@Z")
gt_a = k32.GetProcAddress(h, b"?GetTotalMemoryBytes@FResourceSizeEx@@QEBA_KXZ")
base_a = k32.GetProcAddress(h, b"?GetResourceSizeEx@UObject@@UEAAXAEAUFResourceSizeEx@@@Z")

Ctor = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int32)(ctor_a)
GetTotal = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint64)(gt_a)
VCall = ctypes.CFUNCTYPE(None, ctypes.c_uint64, ctypes.c_uint64)

cdo = unreal.Object.static_class().get_default_object()
cdo_ptr = ctypes.c_uint64.from_address(id(cdo) + 16).value
vtable = ctypes.c_uint64.from_address(cdo_ptr).value
SLOT = -1
for _i in range(200):
    if ctypes.c_uint64.from_address(vtable + _i * 8).value == base_a:
        SLOT = _i
        break
if SLOT < 0:
    SLOT = VTABLE_SLOT

buf = (ctypes.c_uint8 * SIZEOF_RES)()
ba = ctypes.addressof(buf)

def _mem(obj):
    try:
        p = ctypes.c_uint64.from_address(id(obj) + 16).value
        vt = ctypes.c_uint64.from_address(p).value
        vf = ctypes.c_uint64.from_address(vt + SLOT * 8).value
        Ctor(ba, 0)
        VCall(vf)(p, ba)
        return int(GetTotal(ba))
    except Exception:
        return 0

ar = unreal.AssetRegistryHelpers.get_asset_registry()
dep_opts = unreal.AssetRegistryDependencyOptions()
dep_opts.include_hard_package_references = True
dep_opts.include_soft_package_references = False
dep_opts.include_searchable_names = False
dep_opts.include_hard_management_references = False
dep_opts.include_soft_management_references = False

PKG_LIST = REQUESTED_PACKAGES
entries = {}
for pkg in PKG_LIST:
    deps = []
    try:
        raw = ar.get_dependencies(pkg, dep_opts)
        if raw:
            deps = [str(d) for d in raw if not str(d).startswith('/Script/')]
    except Exception:
        pass
    mem = 0
    cls = ""
    tex_info = None
    try:
        asset = unreal.EditorAssetLibrary.load_asset(pkg)
        if asset:
            mem = _mem(asset)
            cls = asset.get_class().get_name()
            if cls in ("Texture2D", "TextureCube", "TextureRenderTarget2D",
                       "LightMapTexture2D", "ShadowMapTexture2D",
                       "LightMapVirtualTexture2D"):
                try:
                    sx = asset.blueprint_get_size_x()
                    sy = asset.blueprint_get_size_y()
                    ns = bool(asset.get_editor_property("NeverStream"))
                    lod_bias = 0
                    try:
                        lod_bias = int(asset.get_editor_property("LODBias"))
                    except Exception:
                        pass
                    num_mips = max(1, int(
                        __import__('math').log2(max(sx, sy))) + 1)
                    tex_info = {"sx": sx, "sy": sy, "mips": num_mips,
                                "never_stream": ns, "lod_bias": lod_bias}
                except Exception:
                    pass
    except Exception:
        pass
    entry = {"deps": deps, "memory": mem, "class": cls}
    if tex_info:
        entry["tex"] = tex_info
    entries[pkg] = entry

result = entries
'''

BATCH_SIZE = 150


class DepCache:
    """Local JSON cache for asset dependency graph + memory sizes."""

    def __init__(self, project_name: str = ""):
        self.project = project_name
        self.entries: dict[str, dict] = {}
        self._path = ""
        if project_name:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            safe = project_name.replace(" ", "_").replace("/", "_")
            self._path = os.path.join(_CACHE_DIR, f"{safe}_dep_cache.json")
            self._load()

    def _load(self):
        if self._path and os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("project") == self.project:
                    self.entries = data.get("entries", {})
            except Exception:
                self.entries = {}

    def save(self):
        if not self._path:
            return
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"project": self.project, "entries": self.entries},
                          f, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass

    def has(self, pkg: str) -> bool:
        return pkg in self.entries

    def get_deps(self, pkg: str) -> list[str]:
        e = self.entries.get(pkg)
        return e["deps"] if e else []

    def get_memory(self, pkg: str) -> int:
        e = self.entries.get(pkg)
        return e["memory"] if e else 0

    def get_class(self, pkg: str) -> str:
        e = self.entries.get(pkg)
        return e.get("class", "") if e else ""

    def merge(self, new_entries: dict[str, dict]):
        self.entries.update(new_entries)

    _MAX_DEPS_PER_ENTRY = 2000

    def build_dep_graph(self) -> dict[str, list[str]]:
        return {pkg: e["deps"] for pkg, e in self.entries.items()
                if "deps" in e and len(e["deps"]) <= self._MAX_DEPS_PER_ENTRY}

    def build_asset_memory(self) -> dict[str, int]:
        return {pkg: e["memory"] for pkg, e in self.entries.items() if "memory" in e}

    def build_asset_class(self) -> dict[str, str]:
        return {pkg: e.get("class", "") for pkg, e in self.entries.items()}

    def build_tex_info(self) -> dict[str, dict]:
        """Return {pkg: {"sx","sy","mips","never_stream","lod_bias"}} for streamable textures."""
        return {pkg: e["tex"] for pkg, e in self.entries.items()
                if "tex" in e and isinstance(e["tex"], dict)}


# ─── Texture Streaming Memory Estimation ─────────────────────────────────────

_STREAMING_TEX_CLASSES = frozenset({
    "Texture2D", "TextureCube", "LightMapTexture2D",
    "ShadowMapTexture2D", "LightMapVirtualTexture2D",
})

# Assumed screen height for streaming calc (1080p)
_SCREEN_H = 1080.0


def _tex_mip_memory(full_memory: int, num_mips: int, wanted_mip: int) -> int:
    """Estimate memory at a given mip level.

    Mip 0 = full resolution. Each mip halves width & height → 1/4 memory.
    The smallest resident mip (tail) is always ~1 KB so we clamp.
    """
    if wanted_mip <= 0:
        return full_memory
    if wanted_mip >= num_mips:
        return max(full_memory >> (2 * (num_mips - 1)), 1024)
    return max(full_memory >> (2 * wanted_mip), 1024)


def estimate_tex_streaming_mip(tex_info: dict, distance: float,
                                bounds_radius: float) -> int:
    """Estimate the mip level that would be loaded at the given distance.

    Uses a simplified UE Texture Streaming model:
      screen_size_ratio = bounds_radius / (distance * tan(fov/2))
      wanted_texels = screen_size_ratio * screen_height
      wanted_mip = num_mips - 1 - floor(log2(wanted_texels))

    Returns mip index (0 = highest res).
    """
    num_mips = tex_info.get("mips", 1)
    never_stream = tex_info.get("never_stream", False)
    lod_bias = tex_info.get("lod_bias", 0)

    if never_stream or num_mips <= 1:
        return 0

    max_dim = max(tex_info.get("sx", 1), tex_info.get("sy", 1))
    if max_dim <= 1:
        return 0

    if distance < 1.0:
        return max(0, lod_bias)

    # tan(45°) ≈ 1.0 for 90° FOV; use 0.5 screen as reference
    screen_ratio = bounds_radius / distance
    wanted_texels = screen_ratio * _SCREEN_H

    if wanted_texels <= 0:
        return num_mips - 1

    # How many mips can we drop from full res?
    # If wanted_texels >= max_dim → mip 0 (full res)
    # If wanted_texels = max_dim/2 → mip 1, etc.
    mip_drop = max(0, int(math.log2(max_dim / wanted_texels)))
    wanted_mip = min(mip_drop + lod_bias, num_mips - 1)
    return max(0, wanted_mip)


def estimate_streaming_memory(
    asset_paths: set[str],
    asset_memory: dict[str, int],
    asset_class: dict[str, str],
    tex_info_db: dict[str, dict],
    sample_x: float,
    sample_y: float,
    actor_bounds: dict[str, tuple],
    asset_to_actors: dict[str, set[str]] | None = None,
) -> tuple[int, dict[str, int]]:
    """Estimate total memory with texture streaming applied.

    For non-texture assets, uses full memory.
    For streamable textures, estimates the mip level based on the distance
    from sample point to the nearest actor that references the texture.

    actor_bounds: {actor_label: (min_x, min_y, max_x, max_y, radius)}
    asset_to_actors: {asset_path: {actor_labels...}} — optional reverse map

    Returns (total_bytes, per_asset_dict).
    """
    result: dict[str, int] = {}
    total = 0

    for path in asset_paths:
        full_mem = asset_memory.get(path, 0)
        cls = asset_class.get(path, "")
        tex = tex_info_db.get(path)

        if tex and cls in _STREAMING_TEX_CLASSES and not tex.get("never_stream", False):
            # Find nearest actor that uses this texture
            min_dist = float('inf')
            best_radius = 100.0
            actors = asset_to_actors.get(path, set()) if asset_to_actors else set()
            for actor_label in actors:
                ab = actor_bounds.get(actor_label)
                if not ab:
                    continue
                bmin_x, bmin_y, bmax_x, bmax_y, radius = ab
                dx = max(bmin_x - sample_x, 0.0, sample_x - bmax_x)
                dy = max(bmin_y - sample_y, 0.0, sample_y - bmax_y)
                d = math.hypot(dx, dy)
                if d < min_dist:
                    min_dist = d
                    best_radius = radius

            if min_dist == float('inf'):
                mem = full_mem
            else:
                mip = estimate_tex_streaming_mip(tex, min_dist, best_radius)
                mem = _tex_mip_memory(full_mem, tex.get("mips", 1), mip)
        else:
            mem = full_mem

        result[path] = mem
        total += mem

    return total, result


def build_actor_bounds(actors_db: dict, all_cells: list) -> dict[str, tuple]:
    """Build {actor_label: (min_x, min_y, max_x, max_y, radius)} from ActorDesc DB."""
    bounds: dict[str, tuple] = {}
    for ad in actors_db.values():
        key = ad.label or ad.name
        if not key:
            continue
        bmin, bmax = ad.bounds_min, ad.bounds_max
        w = abs(bmax[0] - bmin[0])
        h = abs(bmax[1] - bmin[1])
        z = abs(bmax[2] - bmin[2])
        radius = max(math.hypot(w, h, z) * 0.5, 50.0)
        bounds[key] = (bmin[0], bmin[1], bmax[0], bmax[1], radius)
    return bounds


def build_asset_to_actors(actor_resolved: dict[str, set[str]]) -> dict[str, set[str]]:
    """Invert actor_resolved → {asset_path: {actor_labels...}}."""
    result: dict[str, set[str]] = {}
    for label, assets in actor_resolved.items():
        for path in assets:
            if path not in result:
                result[path] = set()
            result[path].add(label)
    return result


_WORLD_MAP_CLASSES = frozenset({"World", "MapBuildDataRegistry", "WorldPartitionRuntimeHashSet"})

def _resolve_all_deps(direct_refs, dep_graph, asset_class=None) -> set[str]:
    """BFS dependency resolution, skipping World/Map packages."""
    visited: set[str] = set()
    queue = deque(direct_refs)
    while queue:
        p = queue.popleft()
        if p in visited:
            continue
        if asset_class and asset_class.get(p, "") in _WORLD_MAP_CLASSES:
            continue
        visited.add(p)
        for d in dep_graph.get(p, []):
            if d not in visited:
                queue.append(d)
    return visited


def _fetch_actor_refs(actor_labels: list[str]) -> dict[str, list[str]]:
    code = _ACTOR_REFS_CODE.replace("REQUESTED_LABELS", repr(set(actor_labels)))
    resp = uefn_execute(code)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return {}


def _fetch_deps_and_sizes(pkg_list: list[str]) -> dict[str, dict]:
    code = _DEPS_SIZES_CODE.replace("REQUESTED_PACKAGES", repr(pkg_list))
    resp = uefn_execute(code)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return {}


def fetch_memory_data(actor_labels: list[str], cache: DepCache,
                      progress_cb=None) -> dict[str, list[str]]:
    """Multi-stage memory data collection with caching.

    Returns actor_refs dict. Updates cache in-place with dep_graph/memory/class.
    progress_cb(stage, detail) is called on the calling thread for UI updates.
    """
    import time
    t_start = time.perf_counter()

    if progress_cb:
        progress_cb("refs", f"Fetching refs for {len(actor_labels)} actors...")

    t0 = time.perf_counter()
    actor_refs = _fetch_actor_refs(actor_labels)
    t_refs = time.perf_counter() - t0
    print(f"[perf] fetch_actor_refs: {len(actor_refs)} actors, {t_refs*1000:.0f}ms")

    all_direct = set()
    for refs in actor_refs.values():
        all_direct.update(refs)
    print(f"[perf] direct asset packages: {len(all_direct)}, cached: {len(cache.entries)}")

    queried_all = set()
    frontier = set(all_direct)
    iteration = 0
    total_queried = 0

    while True:
        uncached = {p for p in frontier if not cache.has(p)} - queried_all
        if not uncached:
            break
        iteration += 1
        batch_list = sorted(uncached)

        for i in range(0, len(batch_list), BATCH_SIZE):
            batch = batch_list[i:i + BATCH_SIZE]
            if progress_cb:
                progress_cb("deps",
                            f"Querying {i + len(batch)}/{len(batch_list)} assets "
                            f"(round {iteration})...")
            t0 = time.perf_counter()
            new_entries = _fetch_deps_and_sizes(batch)
            dt = time.perf_counter() - t0
            cache.merge(new_entries)
            queried_all.update(batch)
            total_queried += len(batch)
            print(f"[perf] batch {len(batch)} assets in {dt*1000:.0f}ms (round {iteration})")

        new_frontier = set()
        for pkg in uncached:
            for dep in cache.get_deps(pkg):
                if not cache.has(dep) and dep not in queried_all:
                    new_frontier.add(dep)
        frontier = new_frontier

    t0 = time.perf_counter()
    cache.save()
    t_save = time.perf_counter() - t0

    total_time = time.perf_counter() - t_start
    print(f"[perf] fetch_memory_data total: {total_time*1000:.0f}ms "
          f"(queried {total_queried} new, cache {len(cache.entries)}, save {t_save*1000:.0f}ms)")

    if progress_cb:
        progress_cb("done", f"Cache: {len(cache.entries)} assets")

    return actor_refs


# ─── Cell Loading Check ──────────────────────────────────────────────────────

def _point_to_aabb_dist(px: float, py: float,
                        bmin: tuple, bmax: tuple) -> float:
    """Shortest distance from point (px,py) to 2D AABB [bmin, bmax]."""
    dx = max(bmin[0] - px, 0.0, px - bmax[0])
    dy = max(bmin[1] - py, 0.0, py - bmax[1])
    return math.hypot(dx, dy)


def move_camera_to(x: float, y: float, z: float = 5000.0):
    """Move the editor viewport camera to the given world position, preserving current rotation."""
    uefn_execute(
        'import unreal\n'
        'cur_loc, cur_rot = unreal.EditorLevelLibrary.get_level_viewport_camera_info()\n'
        f'loc = unreal.Vector({x}, {y}, {z})\n'
        'rot = unreal.Rotator(cur_rot.pitch, cur_rot.yaw, 0)\n'
        'unreal.EditorLevelLibrary.set_level_viewport_camera_info(loc, rot)\n'
        'result = "OK"'
    )
    try:
        import ctypes, ctypes.wintypes
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        hwnd = None
        def _cb(h, _):
            nonlocal hwnd
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                if "Unreal Editor" in buf.value:
                    hwnd = h
                    return False
            return True
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        if hwnd:
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def is_cell_loaded(cell: Cell, cam_x: float, cam_y: float, grid_params: dict) -> bool:
    if cell.always_loaded:
        return True
    if not cell.spatially_loaded:
        return False
    gp = grid_params.get(cell.grid_name)
    if not gp:
        for k, v in grid_params.items():
            if cell.grid_name.endswith(k) or k in cell.grid_name:
                gp = v
                break
    lr = gp.get("loading_range", 25600) if isinstance(gp, dict) else 25600
    dist = _point_to_aabb_dist(cam_x, cam_y, cell.cell_bounds_min, cell.cell_bounds_max)
    return dist <= lr
