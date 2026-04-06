"""wp_common.py — 常量 + 数据结构 + 工具函数"""

import re
import colorsys
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass, field

# ─── UI Constants ─────────────────────────────────────────────────────────────

BG = "#1e1e1e"
BG2 = "#2b2b2b"
FG = "#d4d4d4"
ACCENT = "#264f78"
SEL_FILL = "#ffffff40"
GRID_LINE = "#444444"
CROSSHAIR = "#ffffff80"

# ─── Resource Type Color Mapping ──────────────────────────────────────────────

RESOURCE_TYPE_COLORS = {
    "Texture2D": "#4a90d9",
    "TextureCube": "#5a9ae9",
    "TextureRenderTarget2D": "#3a80c9",
    "StaticMesh": "#4db870",
    "SkeletalMesh": "#3da860",
    "Material": "#d98c4a",
    "MaterialInstanceConstant": "#c97c3a",
    "MaterialInstanceDynamic": "#b96c2a",
    "MaterialFunction": "#e9a060",
    "SoundWave": "#9b59b6",
    "SoundCue": "#8b49a6",
    "NiagaraSystem": "#e74c3c",
    "NiagaraEmitter": "#c0392b",
    "AnimSequence": "#1abc9c",
    "AnimMontage": "#16a085",
    "ParticleSystem": "#f39c12",
    "Blueprint": "#2ecc71",
    "PhysicsAsset": "#7f8c8d",
}
_RESOURCE_TYPE_PREFIX_COLORS = [
    ("Texture", "#4a90d9"),
    ("Material", "#d98c4a"),
    ("Sound", "#9b59b6"),
    ("Anim", "#1abc9c"),
    ("Niagara", "#e74c3c"),
    ("Skeletal", "#3da860"),
    ("Static", "#4db870"),
    ("Particle", "#f39c12"),
]
RESOURCE_TYPE_COLOR_DEFAULT = "#888888"


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class ActorDesc:
    guid: str = ""
    name: str = ""
    label: str = ""
    native_class: str = ""
    base_class: str = ""
    spatially_loaded: bool = True
    hlod_relevant: bool = False
    bounds_min: tuple = (0, 0, 0)
    bounds_max: tuple = (0, 0, 0)
    runtime_grid: str = "None"


@dataclass
class CellActor:
    path: str = ""
    label: str = ""
    instance_guid: str = ""
    package: str = ""


@dataclass
class Cell:
    name: str = ""
    short_id: str = ""
    actor_count: int = 0
    always_loaded: bool = False
    spatially_loaded: bool = True
    content_bounds_min: tuple = (0, 0, 0)
    content_bounds_max: tuple = (0, 0, 0)
    cell_bounds_min: tuple = (0, 0, 0)
    cell_bounds_max: tuple = (0, 0, 0)
    is_2d: bool = True
    actors: list = field(default_factory=list)
    grid_name: str = ""
    level: int = 0
    grid_x: int = 0
    grid_y: int = 0
    data_layer: str = ""


_RE_CELL_NAME = re.compile(r'^(.+?)_L(\d+)_X(-?\d+)_Y(-?\d+)(?:_(d[0-9A-Fa-f]+))?$')


def parse_cell_name(cell: Cell):
    m = _RE_CELL_NAME.match(cell.name)
    if m:
        cell.grid_name = m.group(1)
        cell.level = int(m.group(2))
        cell.grid_x = int(m.group(3))
        cell.grid_y = int(m.group(4))
        cell.data_layer = m.group(5) or ""


def cell_short_label(cell: Cell) -> str:
    s = f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}"
    if cell.data_layer:
        s += f"_{cell.data_layer}"
    return s


# ─── Utility Functions ────────────────────────────────────────────────────────

def heatmap_color(ratio: float) -> str:
    r = max(0.0, min(1.0, ratio))
    if r < 0.01:
        return "#1a1a1a"
    h = 0.08 - r * 0.08
    s = 0.3 + r * 0.6
    v = 0.2 + r * 0.5
    rgb = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}"


def make_sortable(tree: ttk.Treeview):
    """Bind column heading clicks to sort rows. Supports numeric and string."""
    _sort_state: dict[str, bool] = {}

    def _sort(col):
        ascending = not _sort_state.get(col, False)
        _sort_state[col] = ascending

        data = [(tree.set(iid, col), iid) for iid in tree.get_children("")]

        def sort_key(item):
            val = item[0]
            try:
                return (0, float(val))
            except (ValueError, TypeError):
                return (1, str(val).lower())

        data.sort(key=sort_key, reverse=not ascending)
        for idx, (_, iid) in enumerate(data):
            tree.move(iid, "", idx)

        for c in tree["columns"]:
            text = tree.heading(c, "text").rstrip(" \u25b2\u25bc")
            if c == col:
                text += " \u25b2" if ascending else " \u25bc"
            tree.heading(c, text=text)

    for col in tree["columns"]:
        tree.heading(col, command=lambda c=col: _sort(c))


def classify_resource(path: str) -> str:
    """Infer resource type from asset path."""
    p = path.lower()
    if "staticmesh" in p or "/sm_" in p or "/s_" in p:
        return "StaticMesh"
    if "skeletalmesh" in p or "/sk_" in p:
        return "SkeletalMesh"
    if "material" in p:
        if "instance" in p or "/mi_" in p:
            return "MaterialInstance"
        return "Material"
    if "texture" in p or "/t_" in p:
        return "Texture2D"
    if "sound" in p:
        if "cue" in p:
            return "SoundCue"
        return "SoundWave"
    if "niagara" in p or "/ns_" in p or "/ne_" in p:
        return "Niagara"
    if "animation" in p or "/a_" in p or "montage" in p:
        return "Animation"
    if "particle" in p or "/p_" in p:
        return "Particle"
    if "blueprint" in p or "/bp_" in p:
        return "Blueprint"
    return "Other"


def resource_type_color(rtype: str) -> str:
    if rtype in RESOURCE_TYPE_COLORS:
        return RESOURCE_TYPE_COLORS[rtype]
    for prefix, color in _RESOURCE_TYPE_PREFIX_COLORS:
        if rtype.startswith(prefix):
            return color
    return RESOURCE_TYPE_COLOR_DEFAULT
