"""core/bridge.py — UefnReallink HTTP 桥接 + ConnectionManager + 编辑器命令 + 内存采集"""

from __future__ import annotations

import os
import json
import math
import time
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError

from .common import Cell, ActorDesc

# ─── Connection Config ────────────────────────────────────────────────────────

UEFN_HOST = os.environ.get("UEFN_HOST", "127.0.0.1")
UEFN_PORT = int(os.environ.get("UEFN_PORT", "19877"))
_EXECUTE_URL = f"http://{UEFN_HOST}:{UEFN_PORT}/execute"
_PING_URL = f"http://{UEFN_HOST}:{UEFN_PORT}/"


# ─── ConnectionManager ────────────────────────────────────────────────────────

class ConnectionManager:
    """后台线程每 3 秒 ping 编辑器，维护 connected 状态，通知订阅者。"""

    def __init__(self, interval: float = 3.0):
        self.connected = False
        self._interval = interval
        self._callbacks: list = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def subscribe(self, cb):
        self._callbacks.append(cb)

    def _loop(self):
        while not self._stop.is_set():
            try:
                with urlopen(_PING_URL, timeout=2) as r:
                    ok = r.status == 200
            except Exception:
                ok = False
            if ok != self.connected:
                self.connected = ok
                for cb in self._callbacks:
                    try:
                        cb(ok)
                    except Exception:
                        pass
            self._stop.wait(self._interval)


# 全局单例
connection = ConnectionManager()


# ─── HTTP Execute ─────────────────────────────────────────────────────────────

def uefn_execute(code: str) -> dict:
    req = Request(_EXECUTE_URL, data=code.encode("utf-8"), method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        return {"success": False, "error": f"Cannot connect to UefnReallink: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Activate UEFN Window ─────────────────────────────────────────────────────


def _activate_uefn_window() -> None:
    """Bring the visible UEFN window to foreground from the client process.

    旧版这里不是在编辑器内调用 SetForegroundWindow，
    而是在外部 GUI 进程里枚举窗口后激活，这样成功率更高。
    同时通过模拟一次 Alt 键来绕过 Windows 前台切换限制。
    """
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL,
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPARAM,
        )
        hwnd = None

        def _cb(h, _):
            nonlocal hwnd
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                title = buf.value
                if "Unreal Editor" in title or "Unreal Editor for Fortnite" in title:
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


def uefn_cmd(code: str, *, activate: bool = False) -> dict:
    """Execute Python code in UEFN and optionally activate the editor window.

    The code is auto-prefixed with ``import unreal``.
    If *activate* is True the UEFN window is brought to the foreground
    after execution so the editor UI refreshes immediately.
    """
    full = "import unreal\n" + code
    resp = uefn_execute(full)
    if activate:
        _activate_uefn_window()
    return resp


# ─── Editor Commands ──────────────────────────────────────────────────────────

def select_and_focus(label: str):
    return uefn_cmd(f"""
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_name() == {label!r}:
        unreal.EditorLevelLibrary.set_selected_level_actors([a])
        unreal.SystemLibrary.execute_console_command(
            None, "CAMERA ALIGN ACTIVEVIEWPORT")
        result = 'ok'
        break
else:
    result = 'not found'
""", activate=True)


# ─── Camera ──────────────────────────────────────────────────────────────────

_CAMERA_CODE = '''
loc = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
if loc:
    pos, rot = loc
    result = {"x": pos.x, "y": pos.y, "z": pos.z,
              "pitch": rot.pitch, "yaw": rot.yaw, "roll": rot.roll}
else:
    result = None
'''


def fetch_camera_info() -> dict | None:
    resp = uefn_cmd(_CAMERA_CODE)
    if resp.get("success") and resp.get("result"):
        return resp["result"]
    return None


def move_camera_to(x: float, y: float, z: float):
    return uefn_cmd(f"""
loc = unreal.EditorLevelLibrary.get_level_viewport_camera_info()
if loc:
    _, rot = loc
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(
        unreal.Vector({x}, {y}, {z}), rot)
else:
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(
        unreal.Vector({x}, {y}, {z}),
        unreal.Rotator(-30, 0, 0))
result = 'ok'
""", activate=True)


# ─── Grid Params ─────────────────────────────────────────────────────────────

_GRID_PARAMS_CODE = '''
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


def fetch_grid_params_with_fallback(cells: list[Cell]) -> dict:
    resp = uefn_cmd(_GRID_PARAMS_CODE)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        gp = resp["result"]
        if gp:
            return gp
    return infer_grid_params_from_cells(cells)


def infer_grid_params_from_cells(cells: list[Cell]) -> dict:
    grids: dict[str, list[float]] = {}
    for c in cells:
        if c.always_loaded or c.level != 0:
            continue
        w = abs(c.cell_bounds_max[0] - c.cell_bounds_min[0])
        h = abs(c.cell_bounds_max[1] - c.cell_bounds_min[1])
        cs = max(w, h)
        if cs > 100:
            grids.setdefault(c.grid_name, []).append(cs)
    result = {}
    for name, sizes in grids.items():
        avg = sum(sizes) / len(sizes) if sizes else 25600
        result[name] = {"cell_size": avg, "loading_range": avg}
    return result


# ─── Cell Loading Check ──────────────────────────────────────────────────────

def _point_to_aabb_dist(px, py, bmin, bmax):
    dx = max(bmin[0] - px, 0, px - bmax[0])
    dy = max(bmin[1] - py, 0, py - bmax[1])
    return math.sqrt(dx * dx + dy * dy)


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


# ─── Asset Browser ───────────────────────────────────────────────────────────

def browse_to_asset(path: str):
    return uefn_cmd(f"""
ar = unreal.AssetRegistryHelpers.get_asset_registry()
ad = ar.get_asset_by_object_path({path!r})
if ad.is_valid():
    unreal.AssetToolsHelpers.get_asset_tools().sync_browser_to_objects([ad.get_full_name()])
else:
    obj = unreal.load_asset({path!r})
    if obj:
        unreal.AssetToolsHelpers.get_asset_tools().sync_browser_to_objects([obj.get_path_name()])
result = 'ok'
""", activate=True)


def open_asset_editor(path: str):
    return uefn_cmd(f"""
obj = unreal.load_asset({path!r})
if obj:
    unreal.AssetToolsHelpers.get_asset_tools().open_editor_for_assets([obj])
result = 'ok'
""", activate=True)


# ─── Trigger Dump ────────────────────────────────────────────────────────────

_TRIGGER_DUMP_CODE = '''
unreal.SystemLibrary.execute_console_command(None, "wp.Editor.DumpStreamingGenerationLog")
result = "dump triggered"
'''


def trigger_dump() -> dict:
    return uefn_cmd(_TRIGGER_DUMP_CODE)


def find_latest_log() -> str | None:
    resp = uefn_cmd(
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


# ─── Dep Cache ───────────────────────────────────────────────────────────────

import tempfile

_CACHE_DIR = os.path.join(tempfile.gettempdir(), "wp_memory_cache")
_MAX_DEPS_PER_ENTRY = 500


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
                    print(f"[dep_cache] Loaded {len(self.entries)} entries")
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

    def build_dep_graph(self) -> dict[str, list[str]]:
        return {k: v.get("deps", []) for k, v in self.entries.items()}

    def build_asset_memory(self) -> dict[str, int]:
        return {k: v.get("memory", 0) for k, v in self.entries.items()}

    def build_asset_class(self) -> dict[str, str]:
        return {k: v.get("class", "") for k, v in self.entries.items()}

    def build_tex_info(self) -> dict[str, dict]:
        return {k: v["tex"] for k, v in self.entries.items()
                if "tex" in v and isinstance(v["tex"], dict)}

    def build_mesh_info(self) -> dict[str, dict]:
        return {k: v["mesh"] for k, v in self.entries.items()
                if "mesh" in v and isinstance(v["mesh"], dict)}

    def build_asset_detail(self) -> dict[str, str]:
        """Build a human-readable detail string per asset for the Resource table."""
        details: dict[str, str] = {}
        for k, v in self.entries.items():
            cls = v.get("class", "")
            tex = v.get("tex")
            mesh = v.get("mesh")
            if tex and isinstance(tex, dict):
                sx = tex.get("sx", "?")
                sy = tex.get("sy", "?")
                mips = tex.get("mips", 0)
                vt = bool(tex.get("vt", False))
                parts = [f"{sx}x{sy}"]
                if mips:
                    parts.append(f"{mips} mips")
                parts.append("VT" if vt else "NonVT")
                details[k] = " | ".join(parts)
            elif mesh and isinstance(mesh, dict):
                tris = int(mesh.get("tris", 0) or 0)
                lods = int(mesh.get("lods", 0) or 0)
                if tris >= 1000:
                    base = f"{tris / 1000:.1f}K tris"
                else:
                    base = f"{tris} tris"
                if cls == "SkeletalMesh" and lods > 0:
                    details[k] = f"{base} | {lods} LODs"
                else:
                    details[k] = base
            else:
                details[k] = ""
        return details


# ─── UEFN Code Templates ────────────────────────────────────────────────────

_ACTOR_REFS_CODE = '''
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
                    try:
                        vt = bool(asset.get_editor_property("VirtualTextureStreaming"))
                    except Exception:
                        try:
                            vt = bool(asset.get_editor_property("virtual_texture_streaming"))
                        except Exception:
                            vt = False
                    tex_info["vt"] = vt
                    try:
                        cs = str(asset.get_editor_property("CompressionSettings"))
                        if "." in cs:
                            cs = cs.split(".")[-1]
                        if cs.startswith("TC_"):
                            cs = cs[3:]
                        tex_info["fmt"] = cs
                    except Exception:
                        pass
                except Exception:
                    pass
        mesh_info = None
        if cls in ("StaticMesh",):
            try:
                tris = asset.get_num_triangles(0)
                verts = asset.get_num_vertices(0)
                mesh_info = {"tris": tris, "verts": verts}
            except Exception:
                pass
        elif cls in ("SkeletalMesh",):
            try:
                tris = 0
                verts = 0
                try:
                    lod_num = int(asset.get_lod_num())
                except Exception:
                    lod_num = 1
                try:
                    tris = int(asset.get_num_triangles(0))
                except Exception:
                    pass
                try:
                    verts = int(asset.get_num_vertices(0))
                except Exception:
                    pass
                mesh_info = {"tris": tris, "verts": verts, "lods": lod_num}
            except Exception:
                pass
    except Exception:
        pass
    entry = {"deps": deps, "memory": mem, "class": cls}
    if tex_info:
        entry["tex"] = tex_info
    if mesh_info:
        entry["mesh"] = mesh_info
    entries[pkg] = entry
result = entries
'''


# ─── Fetch Functions ─────────────────────────────────────────────────────────

def _fetch_actor_refs(labels: list[str]) -> dict[str, list[str]]:
    code = _ACTOR_REFS_CODE.replace("REQUESTED_LABELS", repr(set(labels)))
    resp = uefn_cmd(code)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return {}


def _fetch_deps_and_sizes(packages: list[str]) -> dict[str, dict]:
    code = _DEPS_SIZES_CODE.replace("REQUESTED_PACKAGES", repr(packages))
    resp = uefn_execute(code)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return {}


def _resolve_all_deps(direct: list[str], dep_graph: dict[str, list[str]],
                      asset_class: dict[str, str] = None) -> set[str]:
    """BFS dependency resolution, skipping World/Map packages."""
    from collections import deque
    _WORLD_MAP_CLASSES = frozenset({"World", "MapBuildDataRegistry", "WorldPartitionRuntimeHashSet"})
    visited: set[str] = set()
    queue = deque(direct)
    while queue:
        p = queue.popleft()
        if p in visited:
            continue
        if asset_class and asset_class.get(p, "") in _WORLD_MAP_CLASSES:
            continue
        visited.add(p)
        for dep in dep_graph.get(p, []):
            if dep not in visited:
                queue.append(dep)
    return visited


# ─── Texture Streaming Memory Estimation ────────────────────────────────────

_STREAMING_TEX_CLASSES = frozenset({
    "Texture2D", "TextureCube", "LightMapTexture2D",
    "ShadowMapTexture2D", "LightMapVirtualTexture2D",
})

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

    Uses a simplified UE Texture Streaming heuristic:
      screen_size ≈ bounds_radius / (distance * tan(fov/2))
      wanted_mip  = log2(tex_height / (screen_size * screen_height))
    """
    sx = tex_info.get("w", 0) or tex_info.get("sx", 0)
    sy = tex_info.get("h", 0) or tex_info.get("sy", 0)
    num_mips = tex_info.get("mips", 1)
    lod_bias = tex_info.get("lod_bias", 0)
    if sx <= 0 or sy <= 0 or num_mips <= 1:
        return 0

    if distance <= 1.0:
        return max(0, lod_bias)

    fov_factor = 1.0
    screen_size = max(bounds_radius / (distance * fov_factor), 0.001)
    desired_screen_texels = screen_size * _SCREEN_H
    if desired_screen_texels <= 0:
        return num_mips - 1

    mip = max(0, int(math.log2(max(sx, sy) / desired_screen_texels)))
    mip = min(mip + lod_bias, num_mips - 1)
    return max(mip, 0)


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
    sample_z = 0.0
    total = 0
    result: dict[str, int] = {}

    for path in asset_paths:
        full_mem = asset_memory.get(path, 0)
        cls = asset_class.get(path, "")
        tex = tex_info_db.get(path)

        if tex and cls in _STREAMING_TEX_CLASSES and not tex.get("never_stream", False):
            min_dist = float('inf')
            best_radius = 100.0
            actors = asset_to_actors.get(path, set()) if asset_to_actors else set()
            for actor_label in actors:
                ab = actor_bounds.get(actor_label)
                if not ab:
                    continue
                bmin_x, bmin_y, bmin_z, bmax_x, bmax_y, bmax_z, radius = ab
                dx = max(bmin_x - sample_x, 0.0, sample_x - bmax_x)
                dy = max(bmin_y - sample_y, 0.0, sample_y - bmax_y)
                dz = max(bmin_z - sample_z, 0.0, sample_z - bmax_z)
                d = math.sqrt(dx * dx + dy * dy + dz * dz)
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


# ─── Actor Bounds / Asset-to-Actor Mapping ───────────────────────────────────

def build_actor_bounds(actors_db: dict[str, ActorDesc],
                       cells: list[Cell]) -> dict[str, tuple]:
    """Build actor bounds keyed by both internal name and label.

    actor_resolved / asset_to_actors 这条链路用的是 CellActor.label，
    它通常对应内部 actor name；
    UI 展示和某些日志里又会出现 ActorDesc.label。
    两者任意一个对不上，TextureStreaming 就会退回 full memory。
    所以这里同时登记 name 和 label，保证都能命中。
    """
    bounds: dict[str, tuple] = {}
    for ad in actors_db.values():
        if not ad.name and not ad.label:
            continue
        bmin, bmax = ad.bounds_min, ad.bounds_max
        w = abs(bmax[0] - bmin[0])
        h = abs(bmax[1] - bmin[1])
        z = abs(bmax[2] - bmin[2])
        radius = max(math.hypot(w, h, z) * 0.5, 50.0)
        value = (bmin[0], bmin[1], bmin[2], bmax[0], bmax[1], bmax[2], radius)
        if ad.name:
            bounds[ad.name] = value
        if ad.label:
            bounds[ad.label] = value
    return bounds


def build_asset_to_actors(
    actor_resolved: dict[str, set[str]]
) -> dict[str, set[str]]:
    """Invert actor_resolved → {asset_path: {actor_labels...}}."""
    result: dict[str, set[str]] = {}
    for label, assets in actor_resolved.items():
        for path in assets:
            if path not in result:
                result[path] = set()
            result[path].add(label)
    return result


# ─── Memory Data Fetch ───────────────────────────────────────────────────────

def fetch_memory_data(
    actor_labels: list[str],
    cache: DepCache,
    progress_cb=None,
) -> dict[str, list[str]]:
    t_start = time.perf_counter()

    if progress_cb:
        progress_cb("actors", f"Fetching actor refs for {len(actor_labels)} actors...")

    ACTOR_BATCH = 200
    actor_refs: dict[str, list[str]] = {}
    for i in range(0, len(actor_labels), ACTOR_BATCH):
        batch = actor_labels[i:i + ACTOR_BATCH]
        if progress_cb:
            progress_cb("actors", f"Actor refs {i + len(batch)}/{len(actor_labels)}...")
        actor_refs.update(_fetch_actor_refs(batch))

    all_direct: set[str] = set()
    for refs in actor_refs.values():
        all_direct.update(refs)
    print(f"[perf] direct asset packages: {len(all_direct)}, cached: {len(cache.entries)}")

    to_query = [p for p in all_direct if p not in cache.entries]
    queue = list(to_query)
    queried_total = 0

    DEP_BATCH = 100
    while queue:
        batch = queue[:DEP_BATCH]
        queue = queue[DEP_BATCH:]
        if progress_cb:
            progress_cb("deps", f"Deps+sizes {queried_total + len(batch)}/{len(to_query) + queried_total}...")
        result = _fetch_deps_and_sizes(batch)
        cache.merge(result)
        for pkg, info in result.items():
            for d in info.get("deps", []):
                if d not in cache.entries and d not in to_query:
                    queue.append(d)
                    to_query.append(d)
        queried_total += len(batch)

    t_save = time.perf_counter()
    cache.save()
    t_end = time.perf_counter()
    print(f"[perf] fetch_memory_data total: {(t_end - t_start)*1000:.0f}ms "
          f"(queried {queried_total} new, cache {len(cache.entries)}, "
          f"save {(t_end - t_save)*1000:.0f}ms)")

    return actor_refs
