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
obj = unreal.load_asset({path!r})
if obj:
    unreal.EditorAssetLibrary.sync_browser_to_objects([obj.get_path_name()])
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
        self.actor_refs: dict[str, list[str]] = {}    # key = package path
        self.label_to_pkg: dict[str, str] = {}         # label → package path
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
                    self.actor_refs = data.get("actor_refs", {})
                    self.label_to_pkg = data.get("label_to_pkg", {})
                    print(f"[dep_cache] Loaded {len(self.entries)} entries, "
                          f"{len(self.actor_refs)} actor_refs")
            except Exception:
                self.entries = {}
                self.actor_refs = {}
                self.label_to_pkg = {}

    def save(self):
        if not self._path:
            return
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"project": self.project,
                           "entries": self.entries,
                           "actor_refs": self.actor_refs,
                           "label_to_pkg": self.label_to_pkg},
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
                verts = int(mesh.get("verts", 0) or 0)
                lods = int(mesh.get("lods", 0) or 0)
                bones = int(mesh.get("bones", 0) or 0)
                if cls == "SkeletalMesh":
                    parts = []
                    if verts >= 1000:
                        parts.append(f"{verts / 1000:.1f}K verts")
                    elif verts > 0:
                        parts.append(f"{verts} verts")
                    if bones > 0:
                        parts.append(f"{bones} bones")
                    if lods > 0:
                        parts.append(f"{lods} LODs")
                    details[k] = " | ".join(parts) if parts else ""
                else:
                    if tris >= 1000:
                        base = f"{tris / 1000:.1f}K tris"
                    else:
                        base = f"{tris} tris"
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
    deps = [str(d) for d in raw if not str(d).startswith('/Script/')] if raw else []
    actor_refs[label] = {"pkg": pkg, "deps": deps}
result = actor_refs
'''

_LANDSCAPE_COMPONENT_BOUNDS_CODE = '''
LABELS = REQUESTED_LABELS
actors = unreal.EditorLevelLibrary.get_all_level_actors()
amap = {}
for a in actors:
    try:
        n = a.get_name()
    except Exception:
        continue
    if n in LABELS:
        amap[n] = a

result = {}
for label in LABELS:
    actor = amap.get(label)
    if not actor:
        continue

    try:
        cls = actor.get_class()
        cls_name = cls.get_name() if cls else ""
    except Exception:
        cls_name = ""
    if "Landscape" not in cls_name:
        continue

    try:
        comps = actor.get_components_by_class(unreal.PrimitiveComponent)
    except Exception:
        comps = []

    entries = []
    for comp in comps or []:
        try:
            ccls = comp.get_class()
            ccls_name = ccls.get_name() if ccls else ""
        except Exception:
            ccls_name = ""
        if "LandscapeComponent" not in ccls_name:
            continue

        try:
            try:
                origin, extent, sphere_radius = unreal.SystemLibrary.get_component_bounds(comp)
            except Exception:
                origin, extent = comp.get_component_bounds()
                sphere_radius = (extent.x * extent.x + extent.y * extent.y + extent.z * extent.z) ** 0.5
            ex = float(extent.x)
            ey = float(extent.y)
            ez = float(extent.z)
            radius = max(float(sphere_radius), 50.0)
            extent_xy = max(ex * 2.0, ey * 2.0, 1.0)
            entries.append((
                float(origin.x - ex), float(origin.y - ey), float(origin.z - ez),
                float(origin.x + ex), float(origin.y + ey), float(origin.z + ez),
                radius, True, extent_xy,
            ))
        except Exception:
            continue

    if entries:
        result[label] = entries
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
                lod_num = 0
                bones = 0
                try:
                    lod_info = asset.get_editor_property("lod_info")
                    lod_num = len(lod_info) if lod_info else 0
                except Exception:
                    try:
                        lod_num = unreal.EditorSkeletalMeshLibrary.get_lod_count(asset)
                    except Exception:
                        lod_num = 1
                try:
                    verts = int(unreal.EditorSkeletalMeshLibrary.get_num_verts(asset, 0))
                except Exception:
                    pass
                try:
                    sk = asset.get_editor_property("skeleton")
                    if sk:
                        bone_names = sk.get_editor_property("bone_tree")
                        if bone_names:
                            bones = len(bone_names)
                except Exception:
                    try:
                        sk = asset.skeleton
                        if sk:
                            bones = len(sk.get_bone_names()) if hasattr(sk, 'get_bone_names') else 0
                    except Exception:
                        pass
                mesh_info = {"verts": verts, "lods": lod_num, "bones": bones}
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

def _fetch_actor_refs(labels: list[str]) -> dict[str, dict]:
    """Returns {label: {"pkg": str, "deps": [str, ...]}}."""
    code = _ACTOR_REFS_CODE.replace("REQUESTED_LABELS", repr(set(labels)))
    resp = uefn_cmd(code)
    if resp.get("success") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return {}


def fetch_landscape_component_bounds(labels: list[str]) -> dict[str, tuple]:
    """Fetch per-landscape-component bounds for the given actor labels.

    Returns {label: ((bmin_x, bmin_y, bmin_z, bmax_x, bmax_y, bmax_z,
                      radius, True, extent_xy), ...)}.
    Non-landscape actors are omitted.
    """
    if not labels:
        return {}
    code = _LANDSCAPE_COMPONENT_BOUNDS_CODE.replace("REQUESTED_LABELS", repr(set(labels)))
    resp = uefn_cmd(code)
    if not (resp.get("success") and isinstance(resp.get("result"), dict)):
        return {}

    result: dict[str, tuple] = {}
    for label, items in resp["result"].items():
        if not isinstance(items, list):
            continue
        normalized = []
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) != 9:
                continue
            normalized.append(tuple(float(v) if i != 7 else bool(v)
                                    for i, v in enumerate(item)))
        if normalized:
            result[label] = tuple(normalized)
    return result


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
                                bounds_radius: float,
                                is_landscape: bool = False,
                                bounds_extent_xy: float = 0.0) -> int:
    """Estimate the mip level that would be loaded at the given distance.

    For normal meshes (UE Texture Streaming heuristic):
      screen_size ≈ bounds_radius / (distance * tan(fov/2))
      wanted_mip  = log2(tex_height / (screen_size * screen_height))

    For landscape components (texel-factor based):
      texel_factor = tex_resolution / component_world_size
      wanted_mip   = log2(tex_height / (texel_factor / distance * screen_height))
    """
    sx = tex_info.get("w", 0) or tex_info.get("sx", 0)
    sy = tex_info.get("h", 0) or tex_info.get("sy", 0)
    num_mips = tex_info.get("mips", 1)
    lod_bias = tex_info.get("lod_bias", 0)
    if sx <= 0 or sy <= 0 or num_mips <= 1:
        return 0

    if distance <= 1.0:
        return max(0, lod_bias)

    tex_res = max(sx, sy)

    if is_landscape and bounds_extent_xy > 0:
        # Landscape: texel factor = texture resolution / component world size
        # UE 不用 bounds sphere 推 screen size，而是直接用 UV 密度
        texel_factor = tex_res / bounds_extent_xy
        desired_screen_texels = (texel_factor / distance) * _SCREEN_H
    else:
        # Normal mesh: screen_size from bounds sphere
        fov_factor = 1.0
        screen_size = max(bounds_radius / (distance * fov_factor), 0.001)
        desired_screen_texels = screen_size * _SCREEN_H

    if desired_screen_texels <= 0:
        return num_mips - 1

    mip = max(0, int(math.log2(tex_res / desired_screen_texels)))
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
    _precomputed: dict | None = None,
    component_bounds_by_actor: dict[str, tuple] | None = None,
) -> tuple[int, dict[str, int]]:
    """Estimate streaming memory — hot path, fully inlined for speed.

    _precomputed: optional pre-built dict from precompute_tex_bounds().
    When provided, skips per-actor iteration entirely.
    """
    total = 0
    result: dict[str, int] = {}
    _sqrt = math.sqrt
    _log2 = math.log2
    _max = max
    _SCREEN = _SCREEN_H
    _CLASSES = _STREAMING_TEX_CLASSES
    _am_get = asset_memory.get
    _ac_get = asset_class.get
    _ti_get = tex_info_db.get
    _pc_get = _precomputed.get if _precomputed else None
    _cb_get = component_bounds_by_actor.get if component_bounds_by_actor else None

    for path in asset_paths:
        full_mem = _am_get(path, 0)
        cls = _ac_get(path, "")
        tex = _ti_get(path)

        if tex and cls in _CLASSES and not tex.get("never_stream", False):
            sx = tex.get("w", 0) or tex.get("sx", 0)
            sy = tex.get("h", 0) or tex.get("sy", 0)
            num_mips = tex.get("mips", 1)
            lod_bias = tex.get("lod_bias", 0)
            if sx <= 0 or sy <= 0 or num_mips <= 1:
                result[path] = full_mem
                total += full_mem
                continue

            tex_res = _max(sx, sy)

            # ── 用预计算的 bounds 或 fallback 到逐 actor 遍历 ──
            pc = _pc_get(path) if _pc_get else None
            if pc:
                # precomputed: tuple of (bmin_x, bmin_y, bmax_x, bmax_y, radius, is_lsc, ext_xy)
                min_dist = 1e30
                best_radius = 100.0
                best_is_lsc = False
                best_ext_xy = 0.0
                for ab in pc:
                    dx = _max(ab[0] - sample_x, 0.0, sample_x - ab[2])
                    dy = _max(ab[1] - sample_y, 0.0, sample_y - ab[3])
                    d = dx * dx + dy * dy
                    if d < min_dist:
                        min_dist = d
                        best_radius = ab[4]
                        best_is_lsc = ab[5]
                        best_ext_xy = ab[6]
                min_dist = _sqrt(min_dist)
                found = True
            else:
                _ab_get = actor_bounds.get
                _a2a_get = asset_to_actors.get if asset_to_actors else None
                actors = _a2a_get(path, None) if _a2a_get else None
                if not actors:
                    result[path] = full_mem
                    total += full_mem
                    continue
                min_dist = 1e30
                best_radius = 100.0
                best_is_lsc = False
                best_ext_xy = 0.0
                found = False
                for actor_label in actors:
                    # Try component bounds first for landscape actors
                    comp_entries = _cb_get(actor_label, None) if _cb_get else None
                    if comp_entries:
                        for cb in comp_entries:
                            dx = _max(cb[0] - sample_x, 0.0, sample_x - cb[3])
                            dy = _max(cb[1] - sample_y, 0.0, sample_y - cb[4])
                            d = _sqrt(dx * dx + dy * dy)
                            if d < min_dist:
                                min_dist = d
                                best_radius = cb[6]
                                best_is_lsc = cb[7] if len(cb) > 7 else True
                                best_ext_xy = cb[8] if len(cb) > 8 else 0.0
                                found = True
                    else:
                        ab = _ab_get(actor_label)
                        if not ab:
                            continue
                        dx = _max(ab[0] - sample_x, 0.0, sample_x - ab[3])
                        dy = _max(ab[1] - sample_y, 0.0, sample_y - ab[4])
                        d = _sqrt(dx * dx + dy * dy)
                        if d < min_dist:
                            min_dist = d
                            best_radius = ab[6]
                            best_is_lsc = ab[7]
                            best_ext_xy = ab[8]
                            found = True

            if not found or min_dist >= 1e30:
                result[path] = full_mem
                total += full_mem
                continue

            # ── 内联：estimate mip ──
            if min_dist <= 1.0:
                mip = _max(0, lod_bias)
            else:
                if best_is_lsc and best_ext_xy > 0:
                    dst = (tex_res / best_ext_xy / min_dist) * _SCREEN
                else:
                    dst = _max(best_radius / min_dist, 0.001) * _SCREEN

                if dst <= 0:
                    mip = num_mips - 1
                else:
                    mip = _max(0, int(_log2(tex_res / dst)))
                    mip = min(mip + lod_bias, num_mips - 1)
                    mip = _max(mip, 0)

            # ── 内联：_tex_mip_memory ──
            if mip <= 0:
                mem = full_mem
            elif mip >= num_mips:
                mem = _max(full_mem >> (2 * (num_mips - 1)), 1024)
            else:
                mem = _max(full_mem >> (2 * mip), 1024)
        else:
            mem = full_mem

        result[path] = mem
        total += mem

    return total, result


def precompute_tex_bounds(
    tex_info_db: dict[str, dict],
    asset_class: dict[str, str],
    asset_to_actors: dict[str, set[str]],
    actor_bounds: dict[str, tuple],
    component_bounds_by_actor: dict[str, tuple] | None = None,
) -> dict[str, tuple]:
    """Pre-build a flat actor-bounds tuple per streaming texture.

    Returns {tex_path: ((bmin_x,bmin_y,bmax_x,bmax_y,radius,is_lsc,ext_xy), ...)}
    Each entry is a tuple of per-actor bound tuples (XY only + metadata).
    This eliminates dict lookups in the hot loop — just iterate a flat tuple.

    When component_bounds_by_actor is provided, landscape actors are expanded
    into per-component entries for finer-grained distance estimation.
    """
    result: dict[str, tuple] = {}
    _ab_get = actor_bounds.get
    _cb_get = component_bounds_by_actor.get if component_bounds_by_actor else None

    for path, actors in asset_to_actors.items():
        cls = asset_class.get(path, "")
        tex = tex_info_db.get(path)
        if not (tex and cls in _STREAMING_TEX_CLASSES and not tex.get("never_stream", False)):
            continue
        if not actors:
            continue

        bounds_list = []
        for actor_label in actors:
            comp_entries = _cb_get(actor_label, None) if _cb_get else None
            if comp_entries:
                for cb in comp_entries:
                    # cb = (bmin_x, bmin_y, bmin_z, bmax_x, bmax_y, bmax_z, radius, is_lsc, ext_xy)
                    bounds_list.append((cb[0], cb[1], cb[3], cb[4], cb[6],
                                        cb[7] if len(cb) > 7 else True,
                                        cb[8] if len(cb) > 8 else 0.0))
            else:
                ab = _ab_get(actor_label)
                if not ab:
                    continue
                # (bmin_x, bmin_y, bmax_x, bmax_y, radius, is_landscape, extent_xy)
                bounds_list.append((ab[0], ab[1], ab[3], ab[4], ab[6], ab[7], ab[8]))

        if bounds_list:
            result[path] = tuple(bounds_list)

    return result


# ─── Actor Bounds / Asset-to-Actor Mapping ───────────────────────────────────

_LANDSCAPE_CLASS_KEYWORDS = ("Landscape", "landscape")


def build_actor_bounds(actors_db: dict[str, ActorDesc],
                       cells: list[Cell]) -> dict[str, tuple]:
    """Build actor bounds keyed by both internal name and label.

    actor_resolved / asset_to_actors 这条链路用的是 CellActor.label，
    它通常对应内部 actor name；
    UI 展示和某些日志里又会出现 ActorDesc.label。
    两者任意一个对不上，TextureStreaming 就会退回 full memory。
    所以这里同时登记 name 和 label，保证都能命中。

    Returns dict[str, tuple]:
        (bmin_x, bmin_y, bmin_z, bmax_x, bmax_y, bmax_z,
         radius, is_landscape, extent_xy)
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

        # 识别 Landscape 类型 actor
        cls_str = ad.native_class or ad.base_class or ""
        is_landscape = any(kw in cls_str for kw in _LANDSCAPE_CLASS_KEYWORDS)
        # Landscape 用 XY extent 的较大值作为 component 世界尺寸
        extent_xy = max(w, h) if is_landscape else 0.0

        value = (bmin[0], bmin[1], bmin[2], bmax[0], bmax[1], bmax[2],
                 radius, is_landscape, extent_xy)
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

    # ── Phase 1: Actor refs (用 package path 做缓存 key) ──
    # cache.actor_refs: {package_path: [dep_paths...]}
    # 返回值 actor_refs: {label: [dep_paths...]}（下游接口不变）
    ACTOR_BATCH = 200
    actor_refs: dict[str, list[str]] = {}

    # 先收集所有 cell actor 的 label→package 映射（来自 parser 的 CellActor.package）
    # 但这里只有 labels，没有 package 信息，所以需要通过 UEFN 查询
    # 策略：先查哪些 label 需要请求，查完后用 pkg 做缓存 key
    uncached_labels: list[str] = []
    label_to_pkg: dict[str, str] = {}

    # 检查 cache 里是否有 label→pkg 的映射
    for l in actor_labels:
        pkg = cache.label_to_pkg.get(l)
        if pkg and pkg in cache.actor_refs:
            actor_refs[l] = cache.actor_refs[pkg]
            label_to_pkg[l] = pkg
        else:
            uncached_labels.append(l)

    cached_count = len(actor_refs)

    for i in range(0, len(uncached_labels), ACTOR_BATCH):
        batch = uncached_labels[i:i + ACTOR_BATCH]
        if progress_cb:
            done = cached_count + i + len(batch)
            progress_cb("actors", f"Actor refs {done}/{len(actor_labels)} "
                        f"(cached {cached_count})...")
        fetched = _fetch_actor_refs(batch)
        for label, info in fetched.items():
            if isinstance(info, dict):
                pkg = info.get("pkg", "")
                deps = info.get("deps", [])
            else:
                # 兼容旧格式 (list)
                pkg = ""
                deps = info if isinstance(info, list) else []
            actor_refs[label] = deps
            if pkg:
                cache.actor_refs[pkg] = deps
                cache.label_to_pkg[label] = pkg
                label_to_pkg[label] = pkg

    if uncached_labels:
        print(f"[perf] actor_refs: {cached_count} cached, "
              f"{len(uncached_labels)} fetched")
    else:
        print(f"[perf] actor_refs: all {cached_count} cached")

    all_direct: set[str] = set()
    for refs in actor_refs.values():
        all_direct.update(refs)
    print(f"[perf] direct asset packages: {len(all_direct)}, cached: {len(cache.entries)}")

    to_query = [p for p in all_direct if p not in cache.entries]
    queried_set: set[str] = set(to_query)   # O(1) 查重
    queue = list(to_query)
    queried_total = 0

    DEP_BATCH = 100
    while queue:
        batch = queue[:DEP_BATCH]
        queue = queue[DEP_BATCH:]
        if progress_cb:
            progress_cb("deps", f"Deps+sizes {queried_total + len(batch)}/{len(queried_set)}...")
        result = _fetch_deps_and_sizes(batch)
        cache.merge(result)
        for pkg, info in result.items():
            for d in info.get("deps", []):
                if d not in cache.entries and d not in queried_set:
                    queue.append(d)
                    queried_set.add(d)
        queried_total += len(batch)

    t_save = time.perf_counter()
    cache.save()
    t_end = time.perf_counter()
    print(f"[perf] fetch_memory_data total: {(t_end - t_start)*1000:.0f}ms "
          f"(queried {queried_total} new, cache {len(cache.entries)}, "
          f"save {(t_end - t_save)*1000:.0f}ms)")

    return actor_refs
