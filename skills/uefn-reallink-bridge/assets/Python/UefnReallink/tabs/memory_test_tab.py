"""tabs/memory_test_tab.py — Memory Test Tab (原 wp_memory_tab.py)"""

from __future__ import annotations

import json
import math
import os
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from collections import deque

from ..core.common import (
    ActorDesc, Cell, cell_short_label,
    heatmap_color, make_sortable, classify_resource, resource_type_color,
)
from ..core.theme import theme
from ..core.bridge import (
    connection,
    fetch_camera_info, fetch_grid_params_with_fallback,
    infer_grid_params_from_cells,
    fetch_memory_data, is_cell_loaded, move_camera_to,
    browse_to_asset, open_asset_editor, select_and_focus,
    DepCache, _resolve_all_deps,
    estimate_streaming_memory, build_actor_bounds, build_asset_to_actors,
    _STREAMING_TEX_CLASSES,
)

DEFAULT_GRID_SIZE = 50000
_MAX_ACTOR_EXTENT = 50000


# ─── Grid Scan Canvas ─────────────────────────────────────────────────────────

class GridScanCanvas:
    """Variable-size grid heatmap showing per-grid memory from a full scan."""

    def __init__(self, parent, all_cells: list[Cell], on_click, on_dblclick,
                 grid_size: int = DEFAULT_GRID_SIZE):
        self.on_click = on_click
        self.on_dblclick = on_dblclick
        self.grid_size = grid_size
        self.grid_memory: dict[tuple[int, int], float] = {}
        self.selected: tuple[int, int] | None = None
        self._max_memory = 1.0

        self.origin_x, self.origin_y = 0.0, 0.0
        self.grid_nx, self.grid_ny = 0, 0
        self._world_bounds = self._compute_world_bounds(all_cells)
        self._recompute_grid()

        self.scale = 1.0
        self.tx = 0.0
        self.ty = 0.0
        self._base_scale = 1.0
        self._panning = False
        self._pan_last = (0, 0)

        frame = tk.Frame(parent, bg=theme.bg_primary)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        top_bar = tk.Frame(frame, bg=theme.bg_primary)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        self.coord_label = tk.Label(top_bar, text="", bg=theme.bg_primary, fg=theme.fg_secondary,
                                    font=theme.font("sm"), anchor=tk.W)
        self.coord_label.pack(side=tk.LEFT, padx=4)
        fit_btn = tk.Button(top_bar, text="Fit", bg=theme.ctrl_bg, fg=theme.fg_primary,
                            font=theme.font("sm"), relief=tk.FLAT, padx=6, pady=1,
                            command=self.fit_view)
        fit_btn.pack(side=tk.RIGHT, padx=4)

        self.canvas = tk.Canvas(frame, bg=theme.bg_primary, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.bottom_label = tk.Label(frame, text="Click Scan All", bg=theme.bg_primary, fg=theme.fg_secondary,
                                     font=theme.font("sm"), anchor=tk.W)
        self.bottom_label.pack(fill=tk.X, padx=4)

        self.canvas.bind("<Configure>", lambda e: self.fit_view())
        self.canvas.bind("<ButtonPress-1>", self._on_left_click)
        self.canvas.bind("<Double-1>", self._on_double_click)
        self.canvas.bind("<ButtonPress-3>", self._on_right_down)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", lambda e: setattr(self, '_panning', False))
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.canvas.bind("<Motion>", self._on_motion)

    @staticmethod
    def _compute_world_bounds(all_cells: list[Cell]):
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        has_valid = False
        for c in all_cells:
            if c.always_loaded or not c.spatially_loaded:
                continue
            bmin, bmax = c.cell_bounds_min, c.cell_bounds_max
            if bmin == (0, 0, 0) and bmax == (0, 0, 0):
                continue
            if abs(bmax[0] - bmin[0]) > 100000 or abs(bmax[1] - bmin[1]) > 100000:
                continue
            min_x = min(min_x, bmin[0])
            max_x = max(max_x, bmax[0])
            min_y = min(min_y, bmin[1])
            max_y = max(max_y, bmax[1])
            has_valid = True
        if not has_valid:
            return (0.0, 0.0, 1.0, 1.0)
        return (min_x, min_y, max_x, max_y)

    def _recompute_grid(self):
        min_x, min_y, max_x, max_y = self._world_bounds
        gs = self.grid_size
        self.origin_x = math.floor(min_x / gs) * gs
        self.origin_y = math.floor(min_y / gs) * gs
        self.grid_nx = max(1, math.ceil((max_x - self.origin_x) / gs))
        self.grid_ny = max(1, math.ceil((max_y - self.origin_y) / gs))

    def set_grid_size(self, grid_size: int):
        self.grid_size = max(1000, grid_size)
        self._recompute_grid()
        self.grid_memory.clear()
        self.selected = None
        self.bottom_label.configure(text="Click Scan All")
        self._redraw()

    def grid_center(self, gx: int, gy: int) -> tuple[float, float]:
        gs = self.grid_size
        return (self.origin_x + gx * gs + gs / 2,
                self.origin_y + gy * gs + gs / 2)

    def set_grid_data(self, grid_memory: dict[tuple[int, int], float]):
        self.grid_memory = grid_memory
        vals = [v for v in grid_memory.values() if v > 0]
        self._max_memory = max(vals) if vals else 1.0
        avg = (sum(vals) / len(vals)) if vals else 0
        self.bottom_label.configure(
            text=f"Max: {self._max_memory / (1024*1024):.1f} MB | "
                 f"Avg: {avg / (1024*1024):.1f} MB | "
                 f"{len(vals)}/{self.grid_nx * self.grid_ny} grids")
        self.fit_view()

    def update_row(self, gy: int):
        self._redraw()

    def fit_view(self):
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        gs = self.grid_size
        if self.grid_memory:
            gxs = [g[0] for g in self.grid_memory]
            gys = [g[1] for g in self.grid_memory]
            fit_x0 = self.origin_x + min(gxs) * gs
            fit_y0 = self.origin_y + min(gys) * gs
            fit_x1 = self.origin_x + (max(gxs) + 1) * gs
            fit_y1 = self.origin_y + (max(gys) + 1) * gs
        else:
            fit_x0 = self.origin_x
            fit_y0 = self.origin_y
            fit_x1 = self.origin_x + self.grid_nx * gs
            fit_y1 = self.origin_y + self.grid_ny * gs
        ww = max(fit_x1 - fit_x0, 1)
        wh = max(fit_y1 - fit_y0, 1)
        self._base_scale = min(cw / ww, ch / wh) * 0.85
        self.scale = 1.0
        cx = fit_x0 + ww / 2
        cy = fit_y0 + wh / 2
        self.tx = -cx
        self.ty = -cy
        self._redraw()

    def _w2s(self, wx, wy):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        s = self._base_scale * self.scale
        sx = (wx + self.tx) * s + cw / 2
        sy = ch / 2 - (wy + self.ty) * s
        return sx, sy

    def _s2w(self, sx, sy):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        s = self._base_scale * self.scale
        if s < 1e-9:
            return 0, 0
        wx = (sx - cw / 2) / s - self.tx
        wy = -(sy - ch / 2) / s - self.ty
        return wx, wy

    def _grid_at(self, sx, sy) -> tuple[int, int] | None:
        wx, wy = self._s2w(sx, sy)
        gs = self.grid_size
        gx = int((wx - self.origin_x) / gs)
        gy = int((wy - self.origin_y) / gs)
        if 0 <= gx < self.grid_nx and 0 <= gy < self.grid_ny:
            return (gx, gy)
        return None

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        max_mem = self._max_memory if self._max_memory > 0 else 1.0
        gs = self.grid_size

        for (gx, gy), mem in self.grid_memory.items():
            if mem <= 0:
                continue
            wx0 = self.origin_x + gx * gs
            wy0 = self.origin_y + gy * gs
            wx1 = wx0 + gs
            wy1 = wy0 + gs

            sx0, sy0 = self._w2s(wx0, wy0)
            sx1, sy1 = self._w2s(wx1, wy1)
            sx_min, sx_max = min(sx0, sx1), max(sx0, sx1)
            sy_min, sy_max = min(sy0, sy1), max(sy0, sy1)

            ratio = mem / max_mem
            fill = heatmap_color(ratio)
            outline = theme.grid_line
            width = 1
            if self.selected == (gx, gy):
                fill = theme.cell_selected_fill
                outline = theme.cell_selected_outline
                width = 2

            c.create_rectangle(sx_min, sy_min, sx_max, sy_max,
                               fill=fill, outline=outline, width=width)

            rw = abs(sx_max - sx_min)
            rh = abs(sy_max - sy_min)
            if rw > 30 and rh > 14:
                mb = mem / (1024 * 1024)
                c.create_text((sx_min + sx_max) / 2, (sy_min + sy_max) / 2,
                              text=f"{mb:.0f}", fill=theme.cell_text,
                              font=theme.font("xs", mono=True) if rw < 50 else theme.font("sm", mono=True))

    def _on_left_click(self, e):
        g = self._grid_at(e.x, e.y)
        if g and self.grid_memory.get(g, 0) > 0:
            self.selected = g
            self._redraw()
            self.on_click(g[0], g[1])

    def _on_double_click(self, e):
        g = self._grid_at(e.x, e.y)
        if g and self.grid_memory.get(g, 0) > 0:
            self.on_dblclick(g[0], g[1])

    def _on_right_down(self, e):
        self._panning = True
        self._pan_last = (e.x, e.y)

    def _on_right_drag(self, e):
        if self._panning:
            s = self._base_scale * self.scale
            if s > 1e-9:
                dx = (e.x - self._pan_last[0]) / s
                dy = -(e.y - self._pan_last[1]) / s
                self.tx += dx
                self.ty += dy
                self._pan_last = (e.x, e.y)
                self._redraw()

    def _on_scroll(self, e):
        factor = 1.15 if e.delta > 0 else 1 / 1.15
        old_s = self._base_scale * self.scale
        self.scale = max(0.01, min(500.0, self.scale * factor))
        new_s = self._base_scale * self.scale
        if old_s > 1e-9 and new_s > 1e-9:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            mx_rel = e.x - cw / 2
            my_rel = e.y - ch / 2
            self.tx += (mx_rel / new_s - mx_rel / old_s)
            self.ty += (-(my_rel / new_s) - (-(my_rel / old_s)))
        self._redraw()

    def _on_motion(self, e):
        g = self._grid_at(e.x, e.y)
        if g:
            mem = self.grid_memory.get(g, 0)
            mb = mem / (1024 * 1024) if mem > 0 else 0
            wx, wy = self.grid_center(g[0], g[1])
            self.coord_label.configure(
                text=f"({g[0]},{g[1]}) {mb:.1f} MB  [{wx:.0f}, {wy:.0f}]")
        else:
            wx, wy = self._s2w(e.x, e.y)
            self.coord_label.configure(text=f"({wx:.0f}, {wy:.0f})")


# ─── Memory Map Canvas ────────────────────────────────────────────────────────

class MemoryMapCanvas:
    """2D cell map showing only loaded cells, with camera arrow and capture marker."""

    def __init__(self, parent, all_cells: list[Cell], on_selection_changed):
        self.all_cells = all_cells
        self.loaded_cells: list[Cell] = []
        self.on_selection_changed = on_selection_changed
        self.selected_cells: list[Cell] = []
        self.cell_memory: dict[str, float] = {}
        self.cam_info: dict | None = None
        self.capture_pos: tuple[float, float] | None = None
        self.grid_params: dict = {}

        self.scale = 1.0
        self.tx = 0.0
        self.ty = 0.0
        self._base_scale = 1.0
        self._panning = False
        self._pan_last = (0, 0)
        self._dragging = False
        self._drag_start_w = (0.0, 0.0)
        self._mouse_x = 0
        self._mouse_y = 0
        self._redraw_lock = False

        self._world_bounds = self._compute_world_bounds(all_cells)

        frame = tk.Frame(parent, bg=theme.bg_primary)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.frame = frame

        top_bar = tk.Frame(frame, bg=theme.bg_primary)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        self.count_label = tk.Label(top_bar, text="Loaded: 0", bg=theme.bg_primary, fg=theme.fg_secondary,
                                    font=theme.font("sm"))
        self.count_label.pack(side=tk.LEFT, padx=4)
        fit_btn = tk.Button(top_bar, text="Fit", bg=theme.ctrl_bg, fg=theme.fg_primary,
                            font=theme.font("sm"), relief=tk.FLAT, padx=6, pady=1,
                            command=self.fit_view)
        fit_btn.pack(side=tk.RIGHT, padx=4)
        self.coord_label = tk.Label(top_bar, text="", bg=theme.bg_primary, fg=theme.fg_secondary,
                                    font=theme.font("sm"), anchor=tk.E)
        self.coord_label.pack(side=tk.RIGHT, padx=4)

        self.canvas = tk.Canvas(frame, bg=theme.bg_primary, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", lambda e: self.fit_view())
        self.canvas.bind("<ButtonPress-1>", self._on_left_down)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_up)
        self.canvas.bind("<ButtonPress-3>", self._on_right_down)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", lambda e: setattr(self, '_panning', False))
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.canvas.bind("<Motion>", self._on_motion)
        self._tooltip = None

    def _compute_world_bounds(self, cells):
        if not cells:
            return (-1, -1, 1, 1)
        min_x = min(c.cell_bounds_min[0] for c in cells)
        max_x = max(c.cell_bounds_max[0] for c in cells)
        min_y = min(c.cell_bounds_min[1] for c in cells)
        max_y = max(c.cell_bounds_max[1] for c in cells)
        return (min_x, min_y, max_x, max_y)

    def set_loaded_cells(self, loaded: list[Cell], cell_memory: dict[str, float]):
        self.loaded_cells = loaded
        self.cell_memory = cell_memory
        self.selected_cells = []
        self._redraw()

    def set_capture_pos(self, x: float, y: float):
        self.capture_pos = (x, y)

    def update_camera(self, cam_info: dict | None):
        self.cam_info = cam_info
        if not self._redraw_lock:
            self._draw_overlays()

    def fit_view(self):
        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        bx0, by0, bx1, by1 = self._world_bounds
        ww = max(bx1 - bx0, 1)
        wh = max(by1 - by0, 1)
        self._base_scale = min(cw / ww, ch / wh) * 0.85
        self.scale = 1.0
        cx = (bx0 + bx1) / 2
        cy = (by0 + by1) / 2
        self.tx = -cx
        self.ty = -cy
        self._redraw()

    def _w2s(self, wx, wy):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        s = self._base_scale * self.scale
        sx = (wx + self.tx) * s + cw / 2
        sy = ch / 2 - (wy + self.ty) * s
        return sx, sy

    def _s2w(self, sx, sy):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        s = self._base_scale * self.scale
        if s < 1e-9:
            return 0, 0
        wx = (sx - cw / 2) / s - self.tx
        wy = -(sy - ch / 2) / s - self.ty
        return wx, wy

    def _redraw(self):
        self._redraw_lock = True
        try:
            c = self.canvas
            c.delete("all")
            if not self.loaded_cells:
                self.count_label.configure(text="Loaded: 0")
                return

            max_mem = max((self.cell_memory.get(cl.short_id, 0)
                          for cl in self.loaded_cells), default=1) or 1
            sel_ids = {cl.short_id for cl in self.selected_cells}

            def _draw_order(cl):
                w = abs(cl.cell_bounds_max[0] - cl.cell_bounds_min[0])
                h = abs(cl.cell_bounds_max[1] - cl.cell_bounds_min[1])
                area = w * h
                mem = self.cell_memory.get(cl.short_id, 0)
                return (-area, mem)

            for cell in sorted(self.loaded_cells, key=_draw_order):
                x1, y1 = self._w2s(cell.cell_bounds_min[0], cell.cell_bounds_min[1])
                x2, y2 = self._w2s(cell.cell_bounds_max[0], cell.cell_bounds_max[1])
                sx1, sy1 = min(x1, x2), min(y1, y2)
                sx2, sy2 = max(x1, x2), max(y1, y2)

                mem = self.cell_memory.get(cell.short_id, 0)
                ratio = mem / max_mem if max_mem > 0 else 0
                fill = heatmap_color(ratio)
                outline = theme.grid_line
                width = 1

                if cell.short_id in sel_ids:
                    fill = theme.cell_selected_fill
                    outline = theme.cell_selected_outline
                    width = 2

                c.create_rectangle(sx1, sy1, sx2, sy2,
                                   fill=fill, outline=outline, width=width)

                rw = abs(sx2 - sx1)
                rh = abs(sy2 - sy1)
                if rw > 28 and rh > 14:
                    mb = mem / (1024 * 1024)
                    lbl = (f"{mb:.1f}MB" if mb >= 0.1
                           else f"X{cell.grid_x}Y{cell.grid_y}")
                    c.create_text((sx1 + sx2) / 2, (sy1 + sy2) / 2, text=lbl,
                                  fill=theme.cell_text,
                                  font=theme.font("xs", mono=True) if rw < 50 else theme.font("sm", mono=True))

            self._draw_overlays()
        finally:
            self._redraw_lock = False

        if self._dragging:
            dsx, dsy = self._w2s(*self._drag_start_w)
            self.canvas.create_rectangle(dsx, dsy, self._mouse_x, self._mouse_y,
                                         outline=theme.drag_rect, width=1, dash=(4, 2))

        self.count_label.configure(text=f"Loaded: {len(self.loaded_cells)}")

    def _draw_overlays(self):
        c = self.canvas
        c.delete("overlay")
        if self.capture_pos:
            cpx, cpy = self.capture_pos
            for gname, gp in self.grid_params.items():
                if not isinstance(gp, dict):
                    continue
                lr = gp.get("loading_range", 0)
                if lr > 0:
                    rx1, ry1 = self._w2s(cpx - lr, cpy + lr)
                    rx2, ry2 = self._w2s(cpx + lr, cpy - lr)
                    c.create_oval(rx1, ry1, rx2, ry2, outline=theme.overlay_capture, width=1,
                                  dash=(4, 4), tags=("overlay",))
        if self.capture_pos:
            sx, sy = self._w2s(*self.capture_pos)
            c.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill=theme.overlay_capture,
                          outline=theme.overlay_capture_outline, width=1, tags=("overlay",))
        if self.cam_info:
            cam_x = self.cam_info.get("x", 0)
            cam_y = self.cam_info.get("y", 0)
            yaw = self.cam_info.get("yaw", 0)
            sx, sy = self._w2s(cam_x, cam_y)
            rad = math.radians(-yaw)
            arrow_len = 14
            arrow_half = 6
            tip_x = sx + arrow_len * math.cos(rad)
            tip_y = sy + arrow_len * math.sin(rad)
            left_x = sx + arrow_half * math.cos(rad + 2.5)
            left_y = sy + arrow_half * math.sin(rad + 2.5)
            right_x = sx + arrow_half * math.cos(rad - 2.5)
            right_y = sy + arrow_half * math.sin(rad - 2.5)
            c.create_polygon(tip_x, tip_y, left_x, left_y, right_x, right_y,
                             fill=theme.overlay_camera_fill, outline=theme.overlay_camera_outline, width=1,
                             tags=("overlay",))

    def _cells_at(self, sx, sy) -> list[Cell]:
        wx, wy = self._s2w(sx, sy)
        hits: list[Cell] = []
        hit_area = float('inf')
        for cell in self.loaded_cells:
            if (cell.cell_bounds_min[0] <= wx <= cell.cell_bounds_max[0] and
                    cell.cell_bounds_min[1] <= wy <= cell.cell_bounds_max[1]):
                w = abs(cell.cell_bounds_max[0] - cell.cell_bounds_min[0])
                h = abs(cell.cell_bounds_max[1] - cell.cell_bounds_min[1])
                area = w * h
                if area < hit_area:
                    hit_area = area
        if hit_area < float('inf'):
            for cell in self.loaded_cells:
                if (cell.cell_bounds_min[0] <= wx <= cell.cell_bounds_max[0] and
                        cell.cell_bounds_min[1] <= wy <= cell.cell_bounds_max[1]):
                    w = abs(cell.cell_bounds_max[0] - cell.cell_bounds_min[0])
                    h = abs(cell.cell_bounds_max[1] - cell.cell_bounds_min[1])
                    if abs(w * h - hit_area) < 1.0:
                        hits.append(cell)
        return hits

    def _cells_in_rect(self, w0, w1):
        x0, x1 = min(w0[0], w1[0]), max(w0[0], w1[0])
        y0, y1 = min(w0[1], w1[1]), max(w0[1], w1[1])
        return [c for c in self.loaded_cells
                if c.cell_bounds_max[0] >= x0 and c.cell_bounds_min[0] <= x1
                and c.cell_bounds_max[1] >= y0 and c.cell_bounds_min[1] <= y1]

    def _on_left_down(self, e):
        self._dragging = True
        self._drag_start_w = self._s2w(e.x, e.y)
        self._mouse_x, self._mouse_y = e.x, e.y
        ctrl = e.state & 0x4
        if not ctrl:
            self.selected_cells = []
        for clicked in self._cells_at(e.x, e.y):
            if clicked not in self.selected_cells:
                self.selected_cells.append(clicked)
        self._redraw()

    def _on_left_drag(self, e):
        self._mouse_x, self._mouse_y = e.x, e.y
        self._redraw()

    def _on_left_up(self, e):
        if self._dragging:
            end_w = self._s2w(e.x, e.y)
            dx = abs(e.x - self._w2s(*self._drag_start_w)[0])
            dy = abs(e.y - self._w2s(*self._drag_start_w)[1])
            if dx > 5 or dy > 5:
                ctrl = e.state & 0x4
                new_sel = self._cells_in_rect(self._drag_start_w, end_w)
                if ctrl:
                    for cc in new_sel:
                        if cc not in self.selected_cells:
                            self.selected_cells.append(cc)
                else:
                    self.selected_cells = new_sel
            self._dragging = False
            self._redraw()
            self.on_selection_changed(self.selected_cells)

    def _on_right_down(self, e):
        self._panning = True
        self._pan_last = (e.x, e.y)

    def _on_right_drag(self, e):
        if self._panning:
            s = self._base_scale * self.scale
            if s > 1e-9:
                dx = (e.x - self._pan_last[0]) / s
                dy = -(e.y - self._pan_last[1]) / s
                self.tx += dx
                self.ty += dy
                self._pan_last = (e.x, e.y)
                self._redraw()

    def _on_scroll(self, e):
        factor = 1.15 if e.delta > 0 else 1 / 1.15
        old_s = self._base_scale * self.scale
        self.scale = max(0.01, min(500.0, self.scale * factor))
        new_s = self._base_scale * self.scale
        if old_s > 1e-9 and new_s > 1e-9:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            mx_rel = e.x - cw / 2
            my_rel = e.y - ch / 2
            self.tx += (mx_rel / new_s - mx_rel / old_s)
            self.ty += (-(my_rel / new_s) - (-(my_rel / old_s)))
        self._redraw()

    def _on_motion(self, e):
        self._mouse_x, self._mouse_y = e.x, e.y
        wx, wy = self._s2w(e.x, e.y)
        self.coord_label.configure(text=f"({wx:.0f}, {wy:.0f})")


# ─── Stats Bar Chart (Canvas) ────────────────────────────────────────────────

class StatsChart:
    """Canvas-drawn horizontal bar chart of resource type memory usage."""

    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=theme.bg_secondary)
        self.frame.pack(fill=tk.X, padx=4, pady=(0, 4))

        self.total_label = tk.Label(self.frame, text="", bg=theme.bg_secondary, fg=theme.fg_primary,
                                    font=theme.font("lg", bold=True), anchor=tk.W)
        self.total_label.pack(fill=tk.X, padx=4, pady=(2, 0))

        self.canvas = tk.Canvas(self.frame, bg=theme.bg_secondary, highlightthickness=0, height=180)
        self.canvas.pack(fill=tk.X, padx=4)

    def update(self, global_assets: set[str], asset_memory: dict, asset_class: dict):
        type_mem: dict[str, int] = {}
        type_count: dict[str, int] = {}
        for path in global_assets:
            mem = asset_memory.get(path, 0)
            rtype = asset_class.get(path, classify_resource(path))
            type_mem[rtype] = type_mem.get(rtype, 0) + mem
            type_count[rtype] = type_count.get(rtype, 0) + 1

        total = sum(type_mem.values())
        total_mb = total / (1024 * 1024)
        self.total_label.configure(
            text=f"Breakdown: {total_mb:.1f} MB  |  {len(global_assets)} assets")

        MAX_BARS = 10
        all_sorted = sorted(type_mem.items(), key=lambda x: x[1], reverse=True)
        if len(all_sorted) > MAX_BARS:
            top = all_sorted[:MAX_BARS]
            others_mem = sum(v for _, v in all_sorted[MAX_BARS:])
            others_count = sum(type_count.get(rt, 0) for rt, _ in all_sorted[MAX_BARS:])
            sorted_types = top + [("Others", others_mem)]
            type_count["Others"] = others_count
        else:
            sorted_types = all_sorted

        c = self.canvas
        c.delete("all")
        if not sorted_types:
            return

        bar_h = 16
        gap = 3
        font = theme.font("sm", mono=True)
        longest = max((len(rt) for rt, _ in sorted_types), default=5)
        label_w = max(longest * 7 + 10, 80)
        value_w = 180
        needed_h = len(sorted_types) * (bar_h + gap) + 4
        c.configure(height=max(needed_h, 30))

        max_mem = sorted_types[0][1] if sorted_types else 1
        canvas_w = max(c.winfo_width(), 300)
        bar_area_w = max(canvas_w - label_w - value_w, 40)

        y = 4
        for rtype, mem in sorted_types:
            mb = mem / (1024 * 1024)
            pct = (mem / total * 100) if total > 0 else 0
            cnt = type_count.get(rtype, 0)
            color = resource_type_color(rtype)

            c.create_text(label_w - 4, y + bar_h / 2, text=rtype, anchor=tk.E,
                          fill=theme.fg_primary, font=font)

            bar_w = (mem / max_mem) * bar_area_w if max_mem > 0 else 0
            c.create_rectangle(label_w, y, label_w + bar_w, y + bar_h,
                               fill=color, outline="")

            val_text = f"{mb:.1f} MB  #{cnt} ({pct:.0f}%)"
            c.create_text(label_w + bar_w + 6, y + bar_h / 2, text=val_text,
                          anchor=tk.W, fill=theme.fg_secondary, font=font)

            y += bar_h + gap


# ─── Memory Tab ───────────────────────────────────────────────────────────────

class MemoryTab(ttk.Frame):
    """Memory analysis tab with map, stats chart, cell/actor/resource lists."""

    def __init__(self, parent, actors_db: dict[str, ActorDesc],
                 all_cells: list[Cell], project_name: str = ""):
        super().__init__(parent)
        self.actors_db = actors_db
        self.all_cells = all_cells
        self._cell_map_dict = {c.short_id: c for c in all_cells}

        self.grid_params: dict = {}
        self.loaded_cells: list[Cell] = []

        self.cache = DepCache(project_name)
        self.actor_refs: dict[str, list[str]] = {}
        self._dep_graph: dict[str, list[str]] = {}
        self._asset_memory: dict[str, int] = {}
        self._asset_class: dict[str, str] = {}
        self._tex_info: dict[str, dict] = {}
        self._actor_bounds: dict[str, tuple] = {}
        self.actor_resolved: dict[str, set[str]] = {}
        self.actor_memory: dict[str, float] = {}
        self.cell_assets: dict[str, set[str]] = {}
        self.cell_memory: dict[str, float] = {}
        self.global_assets: set[str] = set()
        self._streaming_adjusted: dict[str, int] = {}

        self._actor_db_by_name: dict[str, ActorDesc] = {}
        for ad in actors_db.values():
            if ad.name:
                self._actor_db_by_name[ad.name] = ad
            if ad.label and ad.label != ad.name:
                self._actor_db_by_name[ad.label] = ad

        self._polling = False
        self._poll_in_flight = False
        self._capture_cam: tuple[float, float] | None = None
        self._busy = False

        self._scan_actor_refs: dict[str, list[str]] = {}
        self._scan_actor_resolved: dict[str, set[str]] = {}
        self._scan_cell_assets: dict[str, set[str]] = {}
        self._scan_asset_memory: dict[str, int] = {}
        self._scan_asset_class: dict[str, str] = {}
        self._scan_tex_info: dict[str, dict] = {}
        self._scan_actor_bounds: dict[str, tuple] = {}
        self._scan_asset_to_actors: dict[str, set[str]] = {}
        self._grid_memory: dict[tuple[int, int], float] = {}
        self._grid_cells: dict[tuple[int, int], list] = {}

        levels = sorted(set(c.level for c in all_cells))
        self._level_options = ["All"] + [str(l) for l in levels]

        self._build_ui()
        connection.subscribe(self._on_connection_changed)

    def _build_ui(self):
        top = tk.Frame(self, bg=theme.bg_secondary)
        top.pack(fill=tk.X, padx=8, pady=(8, 2))

        tk.Label(top, text="Level:", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 4))
        self.level_var = tk.StringVar(value="All")
        ttk.Combobox(top, textvariable=self.level_var, values=self._level_options,
                     state="readonly", width=6).pack(side=tk.LEFT, padx=(0, 12))
        self.level_var.trace_add("write", lambda *_: self._on_level_change())

        tk.Label(top, text="Grid:", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 2))
        self._grid_size_var = tk.StringVar(value="200")
        grid_entry = tk.Entry(top, textvariable=self._grid_size_var, bg=theme.bg_primary, fg=theme.fg_primary,
                              insertbackground=theme.fg_primary, font=theme.font("md"), width=4,
                              relief=tk.FLAT, bd=2)
        grid_entry.pack(side=tk.LEFT, padx=(0, 1))
        tk.Label(top, text="m", bg=theme.bg_secondary, fg=theme.fg_secondary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 8))

        self.scan_btn = tk.Button(top, text="  Scan All  ", bg=theme.action_blue_bg, fg=theme.action_blue_fg,
                                  font=theme.font("md", bold=True), relief=tk.FLAT,
                                  padx=10, pady=2, command=self._scan_all)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(top, text="Clear Cache", bg=theme.ctrl_bg, fg=theme.cell_text,
                  font=theme.font("sm"), relief=tk.FLAT,
                  padx=6, pady=2, command=self._clear_cache).pack(side=tk.LEFT, padx=(0, 8))
        self._streaming_var = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Tex Streaming", variable=self._streaming_var,
                       bg=theme.bg_secondary, fg=theme.status_streaming, selectcolor=theme.bg_primary, activebackground=theme.bg_secondary,
                       activeforeground=theme.status_streaming, font=theme.font("sm"),
                       command=self._on_streaming_toggle).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top, text="Load", bg=theme.ctrl_bg, fg=theme.cell_text,
                  font=theme.font("sm"), relief=tk.FLAT,
                  padx=6, pady=2, command=self._load_scan).pack(side=tk.RIGHT, padx=(2, 0))
        tk.Button(top, text="Save", bg=theme.ctrl_bg, fg=theme.cell_text,
                  font=theme.font("sm"), relief=tk.FLAT,
                  padx=6, pady=2, command=self._save_scan).pack(side=tk.RIGHT, padx=(2, 0))

        self.status_label = tk.Label(top, text="Click Capture to begin", bg=theme.bg_secondary,
                                     fg=theme.fg_secondary, font=theme.font("md"))
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._spinner_chars = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
        self._spinner_idx = 0
        self._spinner_after_id = None

        mid = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=theme.bg_secondary, sashwidth=4)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left_frame = tk.Frame(mid, bg=theme.bg_secondary)
        mid.add(left_frame, stretch="always")

        map_pane = tk.PanedWindow(left_frame, orient=tk.HORIZONTAL, bg=theme.bg_secondary, sashwidth=4)
        map_pane.pack(fill=tk.BOTH, expand=True)

        grid_frame = tk.Frame(map_pane, bg=theme.bg_secondary)
        map_pane.add(grid_frame, stretch="always")
        self.grid_scan = GridScanCanvas(grid_frame, self.all_cells,
                                        on_click=self._on_grid_select,
                                        on_dblclick=self._on_grid_dblclick)

        mem_frame = tk.Frame(map_pane, bg=theme.bg_secondary)
        map_pane.add(mem_frame, stretch="always")
        self.mem_map = MemoryMapCanvas(mem_frame, self.all_cells,
                                       self._on_map_selection)
        self.capture_btn = tk.Button(mem_frame, text="Capture", bg=theme.action_gold_bg,
                                     fg=theme.action_gold_fg, font=theme.font("sm", bold=True),
                                     relief=tk.FLAT, padx=8, pady=2,
                                     command=self._capture)
        self.capture_btn.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-8, y=-8)

        cell_section = tk.Frame(left_frame, bg=theme.bg_secondary)
        cell_section.pack(fill=tk.X, padx=0, pady=(2, 2))
        self.cell_list_label = tk.Label(cell_section, text="Loaded Cells", bg=theme.bg_secondary,
                                        fg=theme.fg_primary, font=theme.font("md"))
        self.cell_list_label.pack(fill=tk.X, padx=4)

        cell_tree_outer = tk.Frame(cell_section, bg=theme.bg_primary, height=120)
        cell_tree_outer.pack(fill=tk.X)
        cell_tree_outer.pack_propagate(False)
        self.cell_tree = ttk.Treeview(cell_tree_outer,
            columns=("grid", "cell", "level", "spatial", "always", "actors",
                     "memory_mb"),
            show="headings", selectmode="browse")
        for col, text, w, anc in [
            ("grid", "Grid", 100, tk.W), ("cell", "Cell", 110, tk.W),
            ("level", "Lvl", 35, tk.CENTER), ("spatial", "Spatial", 50, tk.CENTER),
            ("always", "Always", 50, tk.CENTER), ("actors", "Actors", 50, tk.CENTER),
            ("memory_mb", "MB", 60, tk.E),
        ]:
            self.cell_tree.heading(col, text=text)
            self.cell_tree.column(col, width=w, anchor=anc)
        cs = ttk.Scrollbar(cell_tree_outer, orient=tk.VERTICAL,
                           command=self.cell_tree.yview)
        self.cell_tree.configure(yscrollcommand=cs.set)
        self.cell_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cs.pack(side=tk.RIGHT, fill=tk.Y)
        self.cell_tree.bind("<<TreeviewSelect>>", self._on_cell_select)
        make_sortable(self.cell_tree)

        actor_section = tk.Frame(left_frame, bg=theme.bg_secondary)
        actor_section.pack(fill=tk.BOTH, expand=True, padx=0, pady=(2, 0))
        self.actor_label = tk.Label(actor_section, text="Actors", bg=theme.bg_secondary, fg=theme.fg_primary,
                                    font=theme.font("md"))
        self.actor_label.pack(fill=tk.X, padx=4)

        actor_tree_outer = tk.Frame(actor_section, bg=theme.bg_primary)
        actor_tree_outer.pack(fill=tk.BOTH, expand=True)
        self.actor_tree = ttk.Treeview(actor_tree_outer,
            columns=("name", "class", "package", "memory_mb"),
            show="headings", selectmode="browse")
        for col, text, w, anc in [
            ("name", "Name", 180, tk.W), ("class", "Class", 140, tk.W),
            ("package", "Package", 140, tk.W), ("memory_mb", "MB", 60, tk.E),
        ]:
            self.actor_tree.heading(col, text=text)
            self.actor_tree.column(col, width=w, anchor=anc)
        ats = ttk.Scrollbar(actor_tree_outer, orient=tk.VERTICAL,
                            command=self.actor_tree.yview)
        self.actor_tree.configure(yscrollcommand=ats.set)
        self.actor_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ats.pack(side=tk.RIGHT, fill=tk.Y)
        make_sortable(self.actor_tree)

        self._actor_tooltip = None
        self._actor_tooltip_data: dict[str, str] = {}
        self.actor_tree.bind("<Motion>", self._on_actor_motion)
        self.actor_tree.bind("<Leave>", self._on_actor_leave)
        self.actor_tree.bind("<Double-1>", self._on_actor_dblclick)

        right_frame = tk.Frame(mid, bg=theme.bg_secondary)
        mid.add(right_frame, stretch="always")
        self.stats_chart = StatsChart(right_frame)

        tk.Label(right_frame, text="Resources", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md")).pack(fill=tk.X, padx=4, pady=(0, 2))

        res_tree_outer = tk.Frame(right_frame, bg=theme.bg_primary)
        res_tree_outer.pack(fill=tk.BOTH, expand=True)
        self.res_tree = ttk.Treeview(res_tree_outer,
            columns=("path", "class", "src", "memory_mb", "ref_count"),
            show="headings", selectmode="browse")
        for col, text, w, anc in [
            ("path", "Resource", 250, tk.W), ("class", "Class", 100, tk.W),
            ("src", "Src", 35, tk.CENTER),
            ("memory_mb", "MB", 70, tk.E), ("ref_count", "Refs", 50, tk.CENTER),
        ]:
            self.res_tree.heading(col, text=text)
            self.res_tree.column(col, width=w, anchor=anc)
        rss = ttk.Scrollbar(res_tree_outer, orient=tk.VERTICAL,
                            command=self.res_tree.yview)
        self.res_tree.configure(yscrollcommand=rss.set)
        self.res_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rss.pack(side=tk.RIGHT, fill=tk.Y)
        make_sortable(self.res_tree)

        self._res_tooltip = None
        self._res_full_path: dict[str, str] = {}
        self._res_raw_mem: dict[str, int] = {}
        self.res_tree.bind("<Motion>", self._on_res_motion)
        self.res_tree.bind("<Leave>", self._on_res_leave)
        self.res_tree.bind("<Double-1>", self._on_res_dblclick)
        self.res_tree.bind("<Button-3>", self._on_res_rightclick)
        self._res_actor_map: dict[str, list[str]] = {}

        self.total_label = tk.Label(right_frame, text="", bg=theme.bg_secondary, fg=theme.fg_secondary,
                                    font=theme.font("md"), anchor=tk.E)
        self.total_label.pack(fill=tk.X, padx=4, pady=(2, 0))

    # ── Connection state ─────────────────────────────────────────────────────

    def _on_connection_changed(self, connected: bool):
        self.after(0, lambda: self._apply_connection_state(connected))

    def _apply_connection_state(self, connected: bool):
        if connected:
            self.capture_btn.configure(state=tk.NORMAL, bg=theme.action_gold_bg, fg=theme.action_gold_fg)
        else:
            self.capture_btn.configure(state=tk.DISABLED, bg=theme.bg_tertiary, fg=theme.fg_secondary)
            if self._polling:
                self.stop_polling()

    # ── Reload Data ──────────────────────────────────────────────────────────

    def reload(self, actors_db, cells, project_name):
        self.actors_db = actors_db
        self.all_cells = cells
        self._cell_map_dict = {c.short_id: c for c in cells}
        self.cache = DepCache(project_name)

        self._actor_db_by_name.clear()
        for ad in actors_db.values():
            if ad.name:
                self._actor_db_by_name[ad.name] = ad
            if ad.label and ad.label != ad.name:
                self._actor_db_by_name[ad.label] = ad

        self.actor_refs.clear()
        self._dep_graph.clear()
        self._asset_memory.clear()
        self._asset_class.clear()
        self._tex_info.clear()
        self._actor_bounds.clear()
        self.actor_resolved.clear()
        self.actor_memory.clear()
        self.cell_assets.clear()
        self.cell_memory.clear()
        self.global_assets.clear()
        self._streaming_adjusted.clear()
        self._scan_actor_refs.clear()
        self._scan_actor_resolved.clear()
        self._scan_cell_assets.clear()
        self._scan_asset_memory.clear()
        self._scan_asset_class.clear()
        self._scan_tex_info.clear()
        self._scan_actor_bounds.clear()
        self._scan_asset_to_actors.clear()
        self._grid_memory.clear()
        self._grid_cells.clear()

        self.grid_scan._world_bounds = GridScanCanvas._compute_world_bounds(cells)
        self.grid_scan._recompute_grid()
        self.grid_scan.grid_memory.clear()
        self.grid_scan.selected = None
        self.grid_scan._redraw()

        self.mem_map.all_cells = cells
        self.mem_map._world_bounds = self.mem_map._compute_world_bounds(cells)
        self.mem_map.loaded_cells = []
        self.mem_map.cell_memory.clear()
        self.mem_map.fit_view()

        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())
        self.res_tree.delete(*self.res_tree.get_children())

        self.status_label.configure(
            text="Data refreshed — click Scan All or Capture", fg=theme.status_ok)

    # ── Camera Polling ───────────────────────────────────────────────────────

    def start_polling(self):
        if self._polling or not connection.connected:
            return
        self._polling = True
        self._poll_in_flight = False
        self._poll_camera()

    def stop_polling(self):
        self._polling = False

    def _poll_camera(self):
        if not self._polling:
            return
        if not connection.connected:
            self._polling = False
            return
        if not self._poll_in_flight:
            self._poll_in_flight = True

            def _bg():
                cam = fetch_camera_info()
                try:
                    self.after(0, lambda: self._on_camera_poll(cam))
                except Exception:
                    self._poll_in_flight = False
            threading.Thread(target=_bg, daemon=True).start()
        self.after(500, self._poll_camera)

    def _on_camera_poll(self, cam: dict | None):
        self._poll_in_flight = False
        if cam:
            self.mem_map.update_camera(cam)

    # ── Capture ──────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, status_text: str = "", status_fg: str = theme.fg_secondary):
        self._busy = busy
        if busy:
            self.capture_btn.configure(state=tk.DISABLED, bg=theme.bg_tertiary, fg=theme.fg_secondary)
            self.scan_btn.configure(state=tk.DISABLED, bg=theme.bg_tertiary, fg=theme.fg_secondary)
            self._start_spinner()
        else:
            self._stop_spinner()
            self.capture_btn.configure(state=tk.NORMAL, bg=theme.action_gold_bg, fg=theme.action_gold_fg)
            self.scan_btn.configure(state=tk.NORMAL, bg=theme.action_blue_bg, fg=theme.action_blue_fg)
        if status_text:
            self.status_label.configure(text=status_text, fg=status_fg)
        self.update_idletasks()

    def _start_spinner(self):
        self._spinner_idx = 0
        self._tick_spinner()

    def _tick_spinner(self):
        ch = self._spinner_chars[self._spinner_idx % len(self._spinner_chars)]
        cur = self.status_label.cget("text")
        base = cur.rstrip(" " + self._spinner_chars)
        self.status_label.configure(text=f"{base} {ch}")
        self._spinner_idx += 1
        self._spinner_after_id = self.after(80, self._tick_spinner)

    def _stop_spinner(self):
        if self._spinner_after_id is not None:
            self.after_cancel(self._spinner_after_id)
            self._spinner_after_id = None

    def _clear_cache(self):
        self.cache.entries.clear()
        self.cache.save()
        self.status_label.configure(text="Cache cleared", fg=theme.action_gold_fg)

    # ── Save / Load Scan Data ────────────────────────────────────────────────

    def _save_scan(self):
        if not self._grid_memory:
            self.status_label.configure(
                text="Nothing to save — run Scan All first", fg=theme.status_error)
            return
        path = filedialog.asksaveasfilename(
            title="Save Scan Data",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return

        def _set_to_list(s):
            return sorted(s) if isinstance(s, set) else s

        data = {
            "version": 2,
            "grid_size": self.grid_scan.grid_size,
            "grid_params": self.grid_params,
            "grid_memory": {f"{k[0]},{k[1]}": v
                            for k, v in self._grid_memory.items()},
            "scan_actor_resolved": {k: _set_to_list(v)
                                    for k, v in self._scan_actor_resolved.items()},
            "scan_cell_assets": {k: _set_to_list(v)
                                 for k, v in self._scan_cell_assets.items()},
            "scan_asset_memory": self._scan_asset_memory,
            "scan_asset_class": self._scan_asset_class,
            "scan_tex_info": self._scan_tex_info,
            "dep_cache": self.cache.entries,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            size_mb = os.path.getsize(path) / (1024 * 1024)
            self.status_label.configure(
                text=f"Saved scan data ({size_mb:.1f} MB) → {os.path.basename(path)}",
                fg=theme.status_ok)
        except Exception as e:
            self.status_label.configure(text=f"Save failed: {e}", fg=theme.status_error)

    def _load_scan(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Load Scan Data",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return

        self.status_label.configure(text="Loading scan data...", fg=theme.action_blue_fg)
        self.update_idletasks()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.status_label.configure(text=f"Load failed: {e}", fg=theme.status_error)
            return

        version = data.get("version", 1)
        if version < 2:
            self.status_label.configure(
                text="Incompatible file format (version < 2)", fg=theme.status_error)
            return

        grid_size = data.get("grid_size", 20000)
        self.grid_params = data.get("grid_params", {})
        self.mem_map.grid_params = self.grid_params

        self._scan_actor_resolved = {
            k: set(v) for k, v in data.get("scan_actor_resolved", {}).items()}
        self._scan_cell_assets = {
            k: set(v) for k, v in data.get("scan_cell_assets", {}).items()}
        self._scan_asset_memory = data.get("scan_asset_memory", {})
        self._scan_asset_class = data.get("scan_asset_class", {})
        self._scan_tex_info = data.get("scan_tex_info", {})
        self._scan_actor_bounds = build_actor_bounds(self.actors_db, self.all_cells)
        self._scan_asset_to_actors = build_asset_to_actors(
            self._scan_actor_resolved)
        self._scan_actor_refs = {}

        dep_cache = data.get("dep_cache", {})
        if dep_cache:
            self.cache.entries.update(dep_cache)

        grid_memory_raw = data.get("grid_memory", {})
        grid_memory: dict[tuple[int, int], float] = {}
        for k, v in grid_memory_raw.items():
            parts = k.split(",")
            if len(parts) == 2:
                grid_memory[(int(parts[0]), int(parts[1]))] = v
        self._grid_memory = grid_memory

        self._grid_cells = {}
        gp = self.grid_params
        self.grid_scan.set_grid_size(grid_size)
        for (gx, gy) in grid_memory:
            cx, cy = self.grid_scan.grid_center(gx, gy)
            self._grid_cells[(gx, gy)] = [
                c for c in self.all_cells if is_cell_loaded(c, cx, cy, gp)]

        self.grid_scan.set_grid_data(grid_memory)

        vals = [v / (1024 * 1024) for v in grid_memory.values() if v > 0]
        max_mb = max(vals) if vals else 0
        avg_mb = (sum(vals) / len(vals)) if vals else 0
        self.status_label.configure(
            text=f"\u2714 Loaded: max {max_mb:.1f} MB, avg {avg_mb:.1f} MB, "
                 f"{len(grid_memory)} grids | {os.path.basename(path)}",
            fg=theme.status_ok)

    # ── Scan All ─────────────────────────────────────────────────────────────

    def _scan_all(self):
        if self._busy:
            return
        try:
            meters = int(self._grid_size_var.get())
        except ValueError:
            meters = 200
        self.grid_scan.set_grid_size(max(50, meters) * 100)

        if not connection.connected:
            self._scan_all_offline()
            return

        self._set_busy(True, "[Scan 1/4] Fetching grid params...", theme.action_blue_fg)

        def _bg_phase1():
            gp = fetch_grid_params_with_fallback(self.all_cells)
            self.after(0, lambda: self._scan_phase2(gp))
        threading.Thread(target=_bg_phase1, daemon=True).start()

    def _scan_all_offline(self):
        gp = infer_grid_params_from_cells(self.all_cells)
        self.grid_params = gp
        self.mem_map.grid_params = gp

        if not self.cache.entries:
            self._set_busy(False,
                "[Offline] No dep cache found — run online Scan All first to build cache",
                theme.status_error)
            return

        self._set_busy(True, "[Offline Scan 1/2] Resolving from cache...", theme.action_blue_fg)
        self.update_idletasks()

        t0 = time.perf_counter()

        dep_graph = self.cache.build_dep_graph()
        asset_memory = self.cache.build_asset_memory()
        asset_class = self.cache.build_asset_class()
        tex_info = self.cache.build_tex_info()
        self._scan_asset_memory = asset_memory
        self._scan_asset_class = asset_class
        self._scan_tex_info = tex_info
        self._scan_actor_bounds = build_actor_bounds(self.actors_db, self.all_cells)

        all_labels = set()
        for cell in self.all_cells:
            for ca in cell.actors:
                all_labels.add(ca.label)

        scan_actor_resolved: dict[str, set[str]] = {}
        for label in all_labels:
            scan_actor_resolved[label] = set()

        cell_assets_map: dict[str, set[str]] = {}
        for cell in self.all_cells:
            merged: set[str] = set()
            for ca in cell.actors:
                if ca.package and ca.package in dep_graph:
                    resolved = _resolve_all_deps(
                        dep_graph.get(ca.package, []) + [ca.package],
                        dep_graph, asset_class)
                    scan_actor_resolved[ca.label] = resolved
                    merged |= resolved
            cell_assets_map[cell.short_id] = merged

        self._scan_actor_resolved = scan_actor_resolved
        self._scan_cell_assets = cell_assets_map
        self._scan_actor_refs = {}
        self._scan_asset_to_actors = build_asset_to_actors(scan_actor_resolved)

        t1 = time.perf_counter()
        print(f"[offline scan] Resolve from cache: {(t1-t0)*1000:.0f}ms, "
              f"{len(scan_actor_resolved)} actors, {len(cell_assets_map)} cells")

        self._scan_phase4()

    def _scan_phase2(self, gp: dict):
        self.grid_params = gp
        self.mem_map.grid_params = gp

        all_labels = set()
        for cell in self.all_cells:
            for ca in cell.actors:
                all_labels.add(ca.label)

        cached_count = len(self.cache.entries)
        self._set_busy(True,
            f"[Scan 2/4] Collecting {len(all_labels)} actors "
            f"(cache: {cached_count})...",
            theme.action_blue_fg)

        def _bg():
            def progress_cb(stage, detail):
                self.after(0, lambda d=detail:
                    self.status_label.configure(text=f"[Scan 2/4] {d}"))
            refs = fetch_memory_data(list(all_labels), self.cache, progress_cb)
            self.after(0, lambda: self._scan_phase3(refs))
        threading.Thread(target=_bg, daemon=True).start()

    def _scan_phase3(self, scan_actor_refs: dict):
        self._scan_actor_refs = scan_actor_refs
        self._set_busy(True, "[Scan 3/4] Resolving dependencies...", theme.action_blue_fg)
        self.update_idletasks()

        t0 = time.perf_counter()

        dep_graph = self.cache.build_dep_graph()
        asset_memory = self.cache.build_asset_memory()
        asset_class = self.cache.build_asset_class()
        tex_info = self.cache.build_tex_info()
        self._scan_asset_memory = asset_memory
        self._scan_asset_class = asset_class
        self._scan_tex_info = tex_info
        self._scan_actor_bounds = build_actor_bounds(self.actors_db, self.all_cells)

        scan_actor_resolved: dict[str, set[str]] = {}
        for label, direct in scan_actor_refs.items():
            scan_actor_resolved[label] = _resolve_all_deps(
                direct, dep_graph, asset_class)
        self._scan_actor_resolved = scan_actor_resolved
        self._scan_asset_to_actors = build_asset_to_actors(scan_actor_resolved)

        cell_assets_map: dict[str, set[str]] = {}
        for cell in self.all_cells:
            merged: set[str] = set()
            for ca in cell.actors:
                merged |= scan_actor_resolved.get(ca.label, set())
            cell_assets_map[cell.short_id] = merged
        self._scan_cell_assets = cell_assets_map

        t1 = time.perf_counter()
        print(f"[scan] Phase 3 resolve: {(t1-t0)*1000:.0f}ms, "
              f"{len(scan_actor_resolved)} actors, {len(cell_assets_map)} cells, "
              f"{len(tex_info)} streamable textures")

        self._scan_phase4()

    def _scan_phase4(self):
        gs = self.grid_scan
        gp = self.grid_params
        all_cells = self.all_cells
        cell_assets_map = self._scan_cell_assets
        asset_memory = self._scan_asset_memory
        asset_class = self._scan_asset_class
        tex_info = self._scan_tex_info
        actor_bounds = self._scan_actor_bounds
        asset_to_actors = self._scan_asset_to_actors
        use_streaming = self._streaming_var.get()
        total = gs.grid_nx * gs.grid_ny

        self._set_busy(True, f"[Scan 4/4] Computing 0/{total} grids...", theme.action_blue_fg)
        self.update_idletasks()

        grid_memory: dict[tuple[int, int], float] = {}
        grid_cells: dict[tuple[int, int], list] = {}

        def _bg():
            t0 = time.perf_counter()
            done = 0
            for gy in range(gs.grid_ny):
                for gx in range(gs.grid_nx):
                    cx, cy = gs.grid_center(gx, gy)
                    loaded = [c for c in all_cells if is_cell_loaded(c, cx, cy, gp)]
                    spatial = [c for c in loaded if not c.always_loaded]
                    if not spatial:
                        done += 1
                        continue
                    merged: set[str] = set()
                    for cell in loaded:
                        merged |= cell_assets_map.get(cell.short_id, set())

                    if use_streaming and tex_info:
                        mem_total, _ = estimate_streaming_memory(
                            merged, asset_memory, asset_class, tex_info,
                            cx, cy, actor_bounds, asset_to_actors)
                    else:
                        mem_total = sum(asset_memory.get(p, 0) for p in merged)

                    grid_memory[(gx, gy)] = mem_total
                    grid_cells[(gx, gy)] = loaded
                    done += 1
                row_done = done
                self.after(0, lambda d=row_done: self.status_label.configure(
                    text=f"[Scan 4/4] Computing {d}/{total} grids..."))

            dt = time.perf_counter() - t0
            tag = " (streaming)" if use_streaming else ""
            print(f"[scan] Phase 4 grid compute{tag}: {dt*1000:.0f}ms, "
                  f"{len(grid_memory)} non-empty grids")
            self.after(0, lambda: self._scan_complete(grid_memory, grid_cells))

        threading.Thread(target=_bg, daemon=True).start()

    def _scan_complete(self, grid_memory, grid_cells):
        self._grid_memory = grid_memory
        self._grid_cells = grid_cells

        self.grid_scan.set_grid_data(grid_memory)

        vals = [v / (1024 * 1024) for v in grid_memory.values() if v > 0]
        max_mb = max(vals) if vals else 0
        avg_mb = (sum(vals) / len(vals)) if vals else 0
        self._set_busy(
            False,
            f"\u2714 Scan complete: max {max_mb:.1f} MB, avg {avg_mb:.1f} MB, "
            f"{len(grid_memory)} grids | cache: {len(self.cache.entries)}",
            theme.status_ok,
        )

    # ── Grid Interaction ─────────────────────────────────────────────────────

    def _on_grid_select(self, gx: int, gy: int):
        loaded = self._grid_cells.get((gx, gy))
        if not loaded:
            return

        cx, cy = self.grid_scan.grid_center(gx, gy)
        use_streaming = self._streaming_var.get() and self._scan_tex_info

        global_assets: set[str] = set()
        for cell in loaded:
            global_assets |= self._scan_cell_assets.get(cell.short_id, set())

        if use_streaming:
            _, streaming_mem = estimate_streaming_memory(
                global_assets, self._scan_asset_memory, self._scan_asset_class,
                self._scan_tex_info, cx, cy,
                self._scan_actor_bounds, self._scan_asset_to_actors)
            effective_mem = streaming_mem
        else:
            effective_mem = self._scan_asset_memory

        cell_memory: dict[str, float] = {}
        for cell in loaded:
            assets = self._scan_cell_assets.get(cell.short_id, set())
            cell_memory[cell.short_id] = sum(
                effective_mem.get(p, 0) for p in assets)

        actor_memory: dict[str, float] = {}
        for cell in loaded:
            for ca in cell.actors:
                if ca.label not in actor_memory:
                    resolved = self._scan_actor_resolved.get(ca.label, set())
                    actor_memory[ca.label] = sum(
                        effective_mem.get(p, 0) for p in resolved)

        self.mem_map.set_capture_pos(cx, cy)
        self.mem_map.set_loaded_cells(loaded, cell_memory)

        self.cell_memory = cell_memory
        self.loaded_cells = loaded
        self.actor_memory = actor_memory
        self.actor_resolved = self._scan_actor_resolved
        self.actor_refs = self._scan_actor_refs
        self.cell_assets = self._scan_cell_assets
        self._asset_memory = self._scan_asset_memory
        self._asset_class = self._scan_asset_class
        self._tex_info = self._scan_tex_info
        self._streaming_adjusted = effective_mem
        self._populate_cell_tree()

        self.stats_chart.update(global_assets, effective_mem,
                                self._scan_asset_class)

        self._update_resource_table(loaded,
            actor_resolved=self._scan_actor_resolved,
            asset_memory=effective_mem,
            asset_class=self._scan_asset_class,
            cell_assets=self._scan_cell_assets,
            raw_memory=self._scan_asset_memory if use_streaming else None)

        total_mb = sum(effective_mem.get(p, 0) for p in global_assets) / (1024 * 1024)
        raw_mb = sum(self._scan_asset_memory.get(p, 0)
                     for p in global_assets) / (1024 * 1024)
        streaming_tag = (f" (raw {raw_mb:.1f} MB)"
                         if use_streaming and abs(raw_mb - total_mb) > 0.1 else "")
        self.status_label.configure(
            text=f"Grid ({gx},{gy}) | {len(loaded)} cells | "
                 f"{len(global_assets)} assets | {total_mb:.1f} MB{streaming_tag}",
            fg=theme.action_blue_fg)

    def _on_grid_dblclick(self, gx: int, gy: int):
        if not connection.connected:
            return
        cx, cy = self.grid_scan.grid_center(gx, gy)
        threading.Thread(target=lambda: move_camera_to(cx, cy, 5000),
                         daemon=True).start()

    # ── Capture ──────────────────────────────────────────────────────────────

    def _capture(self):
        if self._busy:
            return
        if not connection.connected:
            self.status_label.configure(
                text="[Offline] Capture unavailable — use Scan All with cached data",
                fg=theme.status_error)
            return
        self._set_busy(True, "[1/3] Fetching camera & grid params...", theme.action_gold_fg)

        def _bg():
            cam = fetch_camera_info()
            gp = fetch_grid_params_with_fallback(self.all_cells)
            self.after(0, lambda: self._on_capture_params(cam, gp))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_capture_params(self, cam: dict | None, gp: dict):
        self.grid_params = gp
        self.mem_map.grid_params = gp

        if cam:
            cam_x, cam_y = cam["x"], cam["y"]
        else:
            cam_x, cam_y = 0.0, 0.0

        self._capture_cam = (cam_x, cam_y)
        self.mem_map.set_capture_pos(cam_x, cam_y)

        level_filter = self.level_var.get()
        self.loaded_cells = [
            c for c in self.all_cells
            if is_cell_loaded(c, cam_x, cam_y, gp) and
               (level_filter == "All" or c.level == int(level_filter))
        ]

        all_labels = set()
        for cell in self.loaded_cells:
            for ca in cell.actors:
                all_labels.add(ca.label)

        cached_count = len(self.cache.entries)
        self._set_busy(True,
            f"[2/3] Collecting {len(all_labels)} actors "
            f"(cache: {cached_count})...",
            theme.action_gold_fg)

        def _bg2():
            def progress_cb(stage, detail):
                self.after(0, lambda d=detail:
                    self.status_label.configure(text=f"[2/3] {d}"))
            actor_refs = fetch_memory_data(list(all_labels), self.cache, progress_cb)
            self.after(0, lambda: self._on_memory_loaded(actor_refs))

        threading.Thread(target=_bg2, daemon=True).start()

    def _on_memory_loaded(self, actor_refs: dict[str, list[str]]):
        self.actor_refs = actor_refs

        self._set_busy(True, "[3/3] Building cache views...", theme.action_gold_fg)
        self.update_idletasks()
        self._rebuild_cache_views()

        self.status_label.configure(text="[3/3] Resolving dependencies...")
        self.update_idletasks()
        self._compute_all()

        self.status_label.configure(text="[3/3] Updating UI...")
        self.update_idletasks()
        self.mem_map.set_loaded_cells(self.loaded_cells, self.cell_memory)
        self.update_idletasks()

        self._populate_cell_tree()
        self.update_idletasks()

        effective_mem = self._streaming_adjusted
        use_streaming = self._streaming_var.get() and self._tex_info
        raw_memory = self._asset_memory if use_streaming else None
        self.stats_chart.update(self.global_assets, effective_mem, self._asset_class)
        self.update_idletasks()
        self._update_resource_table(self.loaded_cells, raw_memory=raw_memory)

        total_mb = sum(effective_mem.get(p, 0)
                       for p in self.global_assets) / (1024 * 1024)
        raw_mb = sum(self._asset_memory.get(p, 0)
                     for p in self.global_assets) / (1024 * 1024)
        cx, cy = self._capture_cam or (0, 0)
        streaming_tag = (f" | raw {raw_mb:.1f} MB"
                         if use_streaming and abs(raw_mb - total_mb) > 0.1 else "")
        self._set_busy(
            False,
            f"\u2714 ({cx:.0f}, {cy:.0f}) | "
            f"{len(self.loaded_cells)} cells | "
            f"{len(self.global_assets)} assets | "
            f"{total_mb:.1f} MB (deduplicated){streaming_tag} | "
            f"cache: {len(self.cache.entries)}",
            theme.status_ok,
        )

        if not self._polling:
            self.start_polling()

    def _rebuild_cache_views(self):
        t0 = time.perf_counter()
        self._dep_graph = self.cache.build_dep_graph()
        self._asset_memory = self.cache.build_asset_memory()
        self._asset_class = self.cache.build_asset_class()
        self._tex_info = self.cache.build_tex_info()
        self._actor_bounds = build_actor_bounds(self.actors_db, self.all_cells)
        print(f"[perf] _rebuild_cache_views: {len(self.cache.entries)} entries, "
              f"{len(self._tex_info)} textures in "
              f"{(time.perf_counter()-t0)*1000:.0f}ms")

    def _compute_all(self):
        t0 = time.perf_counter()

        self.actor_resolved = {}
        for label, direct in self.actor_refs.items():
            self.actor_resolved[label] = _resolve_all_deps(
                direct, self._dep_graph, self._asset_class)
        t1 = time.perf_counter()

        self.cell_assets = {}
        for cell in self.loaded_cells:
            merged = set()
            for ca in cell.actors:
                merged |= self.actor_resolved.get(ca.label, set())
            self.cell_assets[cell.short_id] = merged

        self.global_assets = set()
        for assets in self.cell_assets.values():
            self.global_assets |= assets
        t2 = time.perf_counter()

        use_streaming = self._streaming_var.get() and self._tex_info
        cam_x, cam_y = self._capture_cam or (0.0, 0.0)

        if use_streaming:
            asset_to_actors = build_asset_to_actors(self.actor_resolved)
            _, self._streaming_adjusted = estimate_streaming_memory(
                self.global_assets, self._asset_memory, self._asset_class,
                self._tex_info, cam_x, cam_y,
                self._actor_bounds, asset_to_actors)
            effective_mem = self._streaming_adjusted
        else:
            self._streaming_adjusted = self._asset_memory
            effective_mem = self._asset_memory

        self.actor_memory = {}
        for label, assets in self.actor_resolved.items():
            self.actor_memory[label] = sum(
                effective_mem.get(p, 0) for p in assets)

        self.cell_memory = {}
        for cid, assets in self.cell_assets.items():
            self.cell_memory[cid] = sum(effective_mem.get(p, 0) for p in assets)

        t3 = time.perf_counter()
        tag = " (streaming)" if use_streaming else ""
        print(f"[perf] _compute_all{tag}: resolve={int((t1-t0)*1000)}ms "
              f"cells={int((t2-t1)*1000)}ms mem={int((t3-t2)*1000)}ms "
              f"actors={len(self.actor_resolved)} cells={len(self.cell_assets)} "
              f"global={len(self.global_assets)}")

    # ── Level Filter ─────────────────────────────────────────────────────────

    def _on_level_change(self):
        if not self._capture_cam:
            return
        cam_x, cam_y = self._capture_cam
        level_filter = self.level_var.get()
        self.loaded_cells = [
            c for c in self.all_cells
            if is_cell_loaded(c, cam_x, cam_y, self.grid_params) and
               (level_filter == "All" or c.level == int(level_filter))
        ]
        self._compute_all()
        effective_mem = self._streaming_adjusted
        use_streaming = self._streaming_var.get() and self._tex_info
        raw_memory = self._asset_memory if use_streaming else None
        self.mem_map.set_loaded_cells(self.loaded_cells, self.cell_memory)
        self._populate_cell_tree()
        self.stats_chart.update(self.global_assets, effective_mem, self._asset_class)
        self._update_resource_table(self.loaded_cells, raw_memory=raw_memory)

    # ── Streaming Toggle ─────────────────────────────────────────────────────

    def _on_streaming_toggle(self):
        if self._busy:
            return

        has_scan = bool(self._grid_memory)
        has_capture = self._capture_cam is not None

        if not has_scan and not has_capture:
            return

        if has_scan and self._scan_actor_resolved:
            self._scan_phase4_recompute()
            return

        if has_capture:
            self._compute_all()
            effective_mem = self._streaming_adjusted
            use_streaming = self._streaming_var.get() and self._tex_info
            raw_memory = self._asset_memory if use_streaming else None

            self.mem_map.set_loaded_cells(self.loaded_cells, self.cell_memory)
            self._populate_cell_tree()
            self.stats_chart.update(self.global_assets, effective_mem,
                                    self._asset_class)
            self._update_resource_table(self.loaded_cells, raw_memory=raw_memory)

            total_mb = sum(effective_mem.get(p, 0)
                           for p in self.global_assets) / (1024 * 1024)
            tag = " (streaming)" if use_streaming else " (raw)"
            self.status_label.configure(
                text=f"Recalculated{tag}: {total_mb:.1f} MB | "
                     f"{len(self.global_assets)} assets",
                fg=theme.status_streaming)

    def _scan_phase4_recompute(self):
        gs = self.grid_scan
        gp = self.grid_params
        all_cells = self.all_cells
        cell_assets_map = self._scan_cell_assets
        asset_memory = self._scan_asset_memory
        asset_class = self._scan_asset_class
        tex_info = self._scan_tex_info
        actor_bounds = self._scan_actor_bounds
        asset_to_actors = self._scan_asset_to_actors
        use_streaming = self._streaming_var.get() and tex_info
        total = gs.grid_nx * gs.grid_ny

        tag = " (streaming)" if use_streaming else " (raw)"
        self._set_busy(True, f"Recomputing{tag} 0/{total} grids...", theme.status_streaming)

        def _bg():
            t0 = time.perf_counter()
            grid_memory: dict[tuple[int, int], float] = {}
            grid_cells: dict[tuple[int, int], list] = {}
            done = 0

            for gy in range(gs.grid_ny):
                for gx in range(gs.grid_nx):
                    cx, cy = gs.grid_center(gx, gy)
                    loaded = [c for c in all_cells
                              if is_cell_loaded(c, cx, cy, gp)]
                    spatial = [c for c in loaded if not c.always_loaded]
                    if not spatial:
                        done += 1
                        continue
                    merged: set[str] = set()
                    for cell in loaded:
                        merged |= cell_assets_map.get(cell.short_id, set())

                    if use_streaming and tex_info:
                        mem_total, _ = estimate_streaming_memory(
                            merged, asset_memory, asset_class, tex_info,
                            cx, cy, actor_bounds, asset_to_actors)
                    else:
                        mem_total = sum(asset_memory.get(p, 0) for p in merged)

                    grid_memory[(gx, gy)] = mem_total
                    grid_cells[(gx, gy)] = loaded
                    done += 1
                row_done = done
                self.after(0, lambda d=row_done:
                    self.status_label.configure(
                        text=f"Recomputing{tag} {d}/{total} grids..."))

            dt = time.perf_counter() - t0
            print(f"[toggle] Recompute{tag}: {dt*1000:.0f}ms, "
                  f"{len(grid_memory)} grids")
            self.after(0, lambda: self._scan_recompute_done(
                grid_memory, grid_cells, use_streaming))

        threading.Thread(target=_bg, daemon=True).start()

    def _scan_recompute_done(self, grid_memory, grid_cells, use_streaming):
        self._grid_memory = grid_memory
        self._grid_cells = grid_cells
        self.grid_scan.set_grid_data(grid_memory)

        vals = [v / (1024 * 1024) for v in grid_memory.values() if v > 0]
        max_mb = max(vals) if vals else 0
        avg_mb = (sum(vals) / len(vals)) if vals else 0
        tag = " (streaming)" if use_streaming else " (raw)"
        self._set_busy(
            False,
            f"Recalculated{tag}: max {max_mb:.1f} MB, avg {avg_mb:.1f} MB, "
            f"{len(grid_memory)} grids",
            theme.status_streaming)

        sel = self.grid_scan.selected
        if sel and sel in self._grid_cells:
            self._on_grid_select(sel[0], sel[1])

    # ── Cell / Actor / Resource Lists ────────────────────────────────────────

    def _update_stats_for_cells(self, cells: list[Cell]):
        merged = set()
        for cell in cells:
            merged |= self.cell_assets.get(cell.short_id, set())
        effective_mem = self._streaming_adjusted or self._asset_memory
        self.stats_chart.update(merged, effective_mem, self._asset_class)

    def _insert_cell_row(self, cell: Cell):
        mem_mb = self.cell_memory.get(cell.short_id, 0) / (1024 * 1024)
        short = cell_short_label(cell)
        grid_short = (cell.grid_name.split("_")[-1]
                      if "_" in cell.grid_name else cell.grid_name)
        self.cell_tree.insert("", tk.END, iid=cell.short_id, values=(
            grid_short, short, cell.level,
            "Y" if cell.spatially_loaded else "",
            "Y" if cell.always_loaded else "",
            cell.actor_count, f"{mem_mb:.3f}",
        ))

    def _populate_cell_tree(self):
        self.cell_tree.delete(*self.cell_tree.get_children())
        for cell in sorted(self.loaded_cells,
                           key=lambda c: self.cell_memory.get(c.short_id, 0),
                           reverse=True):
            self._insert_cell_row(cell)
        children = self.cell_tree.get_children()
        if children:
            self.cell_tree.selection_set(children[0])
            self._on_cell_select(None)

    def _on_map_selection(self, selected: list[Cell]):
        self.cell_tree.delete(*self.cell_tree.get_children())
        for cell in sorted(selected,
                           key=lambda c: self.cell_memory.get(c.short_id, 0),
                           reverse=True):
            self._insert_cell_row(cell)
        self.cell_list_label.configure(text=f"Selected Cells: {len(selected)}")
        self._update_resource_table(selected)
        self._update_stats_for_cells(selected)
        children = self.cell_tree.get_children()
        if children:
            self.cell_tree.selection_set(children[0])
            self._on_cell_select(None)

    def _on_cell_select(self, e):
        sel = self.cell_tree.selection()
        if not sel:
            return
        cell = self._cell_map_dict.get(sel[0])
        if not cell:
            return

        self.actor_tree.delete(*self.actor_tree.get_children())
        self._actor_tooltip_data.clear()
        for idx, ca in enumerate(cell.actors):
            ad = self._actor_db_by_name.get(ca.label)
            cls = ""
            if ad:
                cls = ad.native_class.split(".")[-1] if ad.native_class else ""
                if ad.base_class:
                    cls = ad.base_class.split(".")[-1]
            pkg = ca.package.rsplit("/", 1)[-1] if ca.package else ""
            mem_mb = self.actor_memory.get(ca.label, 0) / (1024 * 1024)
            iid = f"a_{cell.short_id}_{idx}"
            self.actor_tree.insert("", tk.END, iid=iid,
                values=(ca.label, cls, pkg, f"{mem_mb:.3f}"))
            direct = self.actor_refs.get(ca.label, [])
            resolved = self.actor_resolved.get(ca.label, set())
            tip = f"{ca.label}: {ca.path}" if ca.path else ca.label
            tip += f"\nRefs: {len(direct)} direct, {len(resolved)} total"
            self._actor_tooltip_data[iid] = tip
        self.actor_label.configure(
            text=f"Actors in {cell_short_label(cell)}: {len(cell.actors)}")

    def _on_actor_motion(self, e):
        row = self.actor_tree.identify_row(e.y)
        if row and row in self._actor_tooltip_data:
            txt = self._actor_tooltip_data[row]
            if self._actor_tooltip:
                self._actor_tooltip.destroy()
            self._actor_tooltip = tk.Toplevel(self.actor_tree)
            self._actor_tooltip.wm_overrideredirect(True)
            self._actor_tooltip.attributes("-topmost", True)
            cx = self.actor_tree.winfo_rootx() + e.x + 14
            cy = self.actor_tree.winfo_rooty() + e.y + 14
            self._actor_tooltip.geometry(f"+{cx}+{cy}")
            tk.Label(self._actor_tooltip, text=txt, bg=theme.bg_tooltip, fg=theme.fg_bright,
                     font=theme.font("sm"), justify=tk.LEFT, padx=6, pady=3,
                     relief=tk.SOLID, bd=1).pack()
        else:
            self._on_actor_leave(e)

    def _on_actor_leave(self, e):
        if self._actor_tooltip:
            self._actor_tooltip.destroy()
            self._actor_tooltip = None

    def _on_actor_dblclick(self, e):
        sel = self.actor_tree.selection()
        if not sel:
            return
        values = self.actor_tree.item(sel[0], "values")
        name = values[0] if values else ""
        if not name or not connection.connected:
            return
        threading.Thread(target=lambda: select_and_focus(name),
                         daemon=True).start()

    _RES_TABLE_MAX = 500

    def _update_resource_table(self, cells: list[Cell], *,
                               actor_resolved=None, asset_memory=None,
                               asset_class=None, cell_assets=None,
                               raw_memory=None):
        _actor_resolved = actor_resolved or self.actor_resolved
        _asset_memory = (asset_memory or self._streaming_adjusted
                         or self._asset_memory)
        _asset_class = asset_class or self._asset_class
        _cell_assets = cell_assets or self.cell_assets
        _raw_memory = raw_memory

        self.res_tree.delete(*self.res_tree.get_children())
        self._res_actor_map.clear()
        self._res_full_path.clear()
        self._res_raw_mem: dict[str, int] = {}

        merged_assets: set[str] = set()
        actor_of_asset: dict[str, dict[str, str]] = {}
        for cell in cells:
            merged_assets |= _cell_assets.get(cell.short_id, set())
            for ca in cell.actors:
                for path in _actor_resolved.get(ca.label, set()):
                    if path not in actor_of_asset:
                        actor_of_asset[path] = {}
                    actor_of_asset[path][ca.label] = ca.path

        total = 0
        raw_total = 0
        items = []
        for path in merged_assets:
            mem = _asset_memory.get(path, 0)
            total += mem
            raw = _raw_memory.get(path, 0) if _raw_memory else mem
            raw_total += raw
            items.append((mem, raw, path, actor_of_asset.get(path, set())))

        items.sort(key=lambda x: x[0], reverse=True)
        shown = min(len(items), self._RES_TABLE_MAX)
        for mem, raw, path, actor_dict in items[:shown]:
            short_path = path.rsplit("/", 1)[-1]
            cls = _asset_class.get(path, "")
            src = "FN" if not path.startswith("/RPG2") else ""
            mem_mb = mem / (1024 * 1024)
            iid = f"res_{hash(path) & 0xFFFFFFFF}"
            self.res_tree.insert("", tk.END, iid=iid,
                values=(short_path, cls, src, f"{mem_mb:.3f}", len(actor_dict)))
            self._res_actor_map[iid] = actor_dict
            self._res_full_path[iid] = path
            if _raw_memory and raw != mem:
                self._res_raw_mem[iid] = raw

        total_mb = total / (1024 * 1024)
        suffix = f" (top {shown})" if shown < len(items) else ""
        raw_tag = ""
        if _raw_memory and abs(raw_total - total) > 1024:
            raw_tag = f" | raw {raw_total / (1024*1024):.3f} MB"
        self.total_label.configure(
            text=f"Total (deduplicated): {total_mb:.3f} MB{raw_tag}  |  "
                 f"{len(items)} resources{suffix}")

    # ── Resource Tooltip + DblClick ──────────────────────────────────────────

    def _on_res_motion(self, e):
        row = self.res_tree.identify_row(e.y)
        col = self.res_tree.identify_column(e.x)
        txt = None
        if row and col == "#1" and row in self._res_full_path:
            txt = self._res_full_path[row]
            raw = self._res_raw_mem.get(row)
            if raw:
                txt += f"\nRaw: {raw/(1024*1024):.3f} MB"
                path = self._res_full_path[row]
                ti = self._tex_info.get(path) or self._scan_tex_info.get(path)
                if ti:
                    txt += (f"\nTexture: {ti.get('sx',0)}x{ti.get('sy',0)}, "
                            f"{ti.get('mips',0)} mips")
                    if ti.get('never_stream'):
                        txt += " (NeverStream)"
        elif row and col == "#5" and row in self._res_actor_map:
            actor_dict = self._res_actor_map[row]
            lines = [f"{label}: {path}"
                     for label, path in sorted(actor_dict.items())[:30]]
            txt = "\n".join(lines)
            if len(actor_dict) > 30:
                txt += f"\n... +{len(actor_dict) - 30} more"
        if txt:
            if self._res_tooltip:
                self._res_tooltip.destroy()
            self._res_tooltip = tk.Toplevel(self.res_tree)
            self._res_tooltip.wm_overrideredirect(True)
            self._res_tooltip.attributes("-topmost", True)
            cx = self.res_tree.winfo_rootx() + e.x + 14
            cy = self.res_tree.winfo_rooty() + e.y + 14
            self._res_tooltip.geometry(f"+{cx}+{cy}")
            tk.Label(self._res_tooltip, text=txt, bg=theme.bg_tooltip, fg=theme.fg_bright,
                     font=theme.font("sm"), justify=tk.LEFT, padx=6, pady=3,
                     relief=tk.SOLID, bd=1).pack()
        else:
            self._on_res_leave(e)

    def _on_res_leave(self, e):
        if self._res_tooltip:
            self._res_tooltip.destroy()
            self._res_tooltip = None

    def _on_res_dblclick(self, e):
        sel = self.res_tree.selection()
        if not sel:
            return
        path = self._res_full_path.get(sel[0])
        if not path or not connection.connected:
            return
        threading.Thread(target=lambda: browse_to_asset(path),
                         daemon=True).start()

    def _on_res_rightclick(self, e):
        row = self.res_tree.identify_row(e.y)
        if not row:
            return
        self.res_tree.selection_set(row)
        path = self._res_full_path.get(row)
        actor_dict = self._res_actor_map.get(row, {})
        if not path:
            return

        menu = tk.Menu(self, tearoff=0, bg=theme.ctrl_bg, fg=theme.fg_primary,
                       activebackground=theme.ctrl_hover, activeforeground=theme.fg_bright,
                       font=theme.font("md"))

        offline = not connection.connected
        menu.add_command(label="Browse to Asset",
                         state=tk.DISABLED if offline else tk.NORMAL,
                         command=lambda: threading.Thread(
                             target=lambda: browse_to_asset(path),
                             daemon=True).start())
        menu.add_command(label="Open in Editor",
                         state=tk.DISABLED if offline else tk.NORMAL,
                         command=lambda: threading.Thread(
                             target=lambda: open_asset_editor(path),
                             daemon=True).start())

        if actor_dict:
            actor_menu = tk.Menu(menu, tearoff=0, bg=theme.ctrl_bg, fg=theme.fg_primary,
                                 activebackground=theme.ctrl_hover,
                                 activeforeground=theme.fg_bright,
                                 font=theme.font("md"))
            for label in sorted(actor_dict.keys())[:50]:
                actor_menu.add_command(
                    label=label,
                    state=tk.DISABLED if offline else tk.NORMAL,
                    command=lambda l=label: threading.Thread(
                        target=lambda: select_and_focus(l),
                        daemon=True).start())
            if len(actor_dict) > 50:
                actor_menu.add_command(
                    label=f"... +{len(actor_dict) - 50} more",
                    state=tk.DISABLED)
            menu.add_cascade(label=f"Select Actor ({len(actor_dict)})",
                             menu=actor_menu)

        menu.tk_popup(e.x_root, e.y_root)
        menu.grab_release()
