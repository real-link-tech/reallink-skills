"""wp_layout_tab.py — Layout Tab: CellMapCanvas + LayoutTab(ttk.Frame)"""

import threading
import tkinter as tk
from tkinter import ttk

from wp_common import (
    BG, BG2, FG, ACCENT, GRID_LINE,
    ActorDesc, CellActor, Cell,
    heatmap_color, make_sortable,
)
from wp_bridge import select_and_focus


# ─── 2D Map Widget ────────────────────────────────────────────────────────────

class CellMapCanvas:
    """Canvas-based 2D cell map with pan, zoom, drag-select."""

    def __init__(self, parent, cells: list[Cell], on_selection_changed):
        self.cells = cells
        self.on_selection_changed = on_selection_changed
        self.selected_cells: list[Cell] = []
        self.hovered_cell: Cell | None = None

        self.scale = 1.0
        self.tx = 0.0
        self.ty = 0.0
        self._base_scale = 1.0

        self._dragging = False
        self._drag_start_w = (0.0, 0.0)
        self._panning = False
        self._pan_last = (0, 0)
        self._mouse_x = 0
        self._mouse_y = 0

        self._world_bounds = self._compute_world_bounds()

        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        top_bar = tk.Frame(frame, bg=BG)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        self.count_label = tk.Label(top_bar, text=f"Count: {len(cells)}", bg=BG, fg="#888",
                                    font=("Consolas", 8), anchor=tk.W)
        self.count_label.pack(side=tk.LEFT, padx=4)
        fit_btn = tk.Button(top_bar, text="Fit", bg="#3c3c3c", fg="#ddd", font=("Consolas", 8),
                            relief=tk.FLAT, padx=6, pady=1, command=self.fit_view)
        fit_btn.pack(side=tk.RIGHT, padx=4)
        self.coord_label = tk.Label(top_bar, text="", bg=BG, fg="#888", font=("Consolas", 8), anchor=tk.E)
        self.coord_label.pack(side=tk.RIGHT, padx=4)
        self.zoom_label = tk.Label(top_bar, text="100%", bg=BG, fg="#888", font=("Consolas", 8))
        self.zoom_label.pack(side=tk.RIGHT, padx=4)

        self.canvas = tk.Canvas(frame, bg=BG, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_left_down)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_up)
        self.canvas.bind("<ButtonPress-3>", self._on_right_down)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_up)
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)

        self._tooltip = None

    def _compute_world_bounds(self):
        if not self.cells:
            return (-1, -1, 1, 1)
        min_x = min(c.cell_bounds_min[0] for c in self.cells)
        max_x = max(c.cell_bounds_max[0] for c in self.cells)
        min_y = min(c.cell_bounds_min[1] for c in self.cells)
        max_y = max(c.cell_bounds_max[1] for c in self.cells)
        return (min_x, min_y, max_x, max_y)

    def set_cells(self, cells: list[Cell]):
        self.cells = cells
        self.selected_cells = []
        self._world_bounds = self._compute_world_bounds()
        self.fit_view()

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
        c = self.canvas
        c.delete("all")
        if not self.cells:
            return

        max_count = max((cl.actor_count for cl in self.cells), default=1) or 1
        sel_ids = {cl.short_id for cl in self.selected_cells}

        def _cell_area(cl):
            w = abs(cl.cell_bounds_max[0] - cl.cell_bounds_min[0])
            h = abs(cl.cell_bounds_max[1] - cl.cell_bounds_min[1])
            return w * h
        draw_order = sorted(self.cells, key=_cell_area, reverse=True)
        for cell in draw_order:
            x1, y1 = self._w2s(cell.cell_bounds_min[0], cell.cell_bounds_min[1])
            x2, y2 = self._w2s(cell.cell_bounds_max[0], cell.cell_bounds_max[1])
            sx1, sy1 = min(x1, x2), min(y1, y2)
            sx2, sy2 = max(x1, x2), max(y1, y2)

            ratio = cell.actor_count / max_count
            fill = heatmap_color(ratio)
            outline = GRID_LINE
            width = 1

            if cell.short_id in sel_ids:
                fill = "#3a5f8a"
                outline = "#4fc3f7"
                width = 2

            tag = f"c_{cell.short_id}"
            c.create_rectangle(sx1, sy1, sx2, sy2, fill=fill, outline=outline, width=width, tags=(tag,))

            rw = abs(sx2 - sx1)
            rh = abs(sy2 - sy1)
            if rw > 28 and rh > 14:
                idx = f"X{cell.grid_x} Y{cell.grid_y}"
                c.create_text((sx1+sx2)/2, (sy1+sy2)/2, text=idx, fill="#aaa",
                              font=("Consolas", 7 if rw < 50 else 8), tags=(tag,))

        if self._dragging:
            dsx, dsy = self._w2s(*self._drag_start_w)
            c.create_rectangle(dsx, dsy, self._mouse_x, self._mouse_y,
                               outline="#fff", width=1, dash=(4, 2), tags=("sel_rect",))

        self.count_label.configure(text=f"Count: {len(self.cells)}")
        self.zoom_label.configure(text=f"{self.scale * 100:.0f}%")

    def _cell_at(self, sx, sy) -> Cell | None:
        wx, wy = self._s2w(sx, sy)
        hit: Cell | None = None
        hit_area = float('inf')
        for cell in self.cells:
            if (cell.cell_bounds_min[0] <= wx <= cell.cell_bounds_max[0] and
                cell.cell_bounds_min[1] <= wy <= cell.cell_bounds_max[1]):
                w = abs(cell.cell_bounds_max[0] - cell.cell_bounds_min[0])
                h = abs(cell.cell_bounds_max[1] - cell.cell_bounds_min[1])
                area = w * h
                if area < hit_area:
                    hit = cell
                    hit_area = area
        return hit

    def _cells_in_rect(self, w0, w1) -> list[Cell]:
        x0, x1 = min(w0[0], w1[0]), max(w0[0], w1[0])
        y0, y1 = min(w0[1], w1[1]), max(w0[1], w1[1])
        result = []
        for c in self.cells:
            cx0, cy0 = c.cell_bounds_min[0], c.cell_bounds_min[1]
            cx1, cy1 = c.cell_bounds_max[0], c.cell_bounds_max[1]
            if cx1 >= x0 and cx0 <= x1 and cy1 >= y0 and cy0 <= y1:
                result.append(c)
        return result

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_configure(self, e):
        self.fit_view()

    def _on_left_down(self, e):
        self._dragging = True
        self._drag_start_w = self._s2w(e.x, e.y)
        self._mouse_x, self._mouse_y = e.x, e.y
        ctrl = e.state & 0x4
        if not ctrl:
            self.selected_cells = []
        clicked = self._cell_at(e.x, e.y)
        if clicked and clicked not in self.selected_cells:
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
                    for c in new_sel:
                        if c not in self.selected_cells:
                            self.selected_cells.append(c)
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

    def _on_right_up(self, e):
        self._panning = False

    def _on_scroll(self, e):
        old_s = self._base_scale * self.scale
        factor = 1.15 if e.delta > 0 else 1 / 1.15
        new_scale = max(0.01, min(500.0, self.scale * factor))

        wx, wy = self._s2w(e.x, e.y)
        self.scale = new_scale
        new_s = self._base_scale * self.scale
        if old_s > 1e-9 and new_s > 1e-9:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            mx_rel = e.x - cw / 2
            my_rel = e.y - ch / 2
            p0x = mx_rel / old_s
            p0y = -my_rel / old_s
            p1x = mx_rel / new_s
            p1y = -my_rel / new_s
            self.tx += (p1x - p0x)
            self.ty += (p1y - p0y)
        self._redraw()

    def _on_motion(self, e):
        self._mouse_x, self._mouse_y = e.x, e.y
        wx, wy = self._s2w(e.x, e.y)
        self.coord_label.configure(text=f"({wx:.0f}, {wy:.0f})")

        cell = self._cell_at(e.x, e.y)
        if cell != self.hovered_cell:
            self.hovered_cell = cell
            self._update_tooltip(e)

    def _on_leave(self, e):
        self.hovered_cell = None
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None
        self.coord_label.configure(text="")

    def _update_tooltip(self, e):
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None
        if not self.hovered_cell:
            return
        c = self.hovered_cell
        self._tooltip = tk.Toplevel(self.canvas)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.attributes("-topmost", True)
        cx = self.canvas.winfo_rootx() + e.x + 14
        cy = self.canvas.winfo_rooty() + e.y + 14
        self._tooltip.geometry(f"+{cx}+{cy}")
        txt = f"{c.name}\nActors: {c.actor_count}\nL{c.level} X{c.grid_x} Y{c.grid_y}"
        if c.always_loaded:
            txt += "\n[Always Loaded]"
        tk.Label(self._tooltip, text=txt, bg="#444", fg="#eee", font=("Consolas", 9),
                 justify=tk.LEFT, padx=6, pady=3, relief=tk.SOLID, bd=1).pack()


# ─── Layout Tab ───────────────────────────────────────────────────────────────

class LayoutTab(ttk.Frame):
    """Original StreamingViewer UI content, now as a Tab."""

    def __init__(self, parent, actors_db: dict[str, ActorDesc], cells: list[Cell], log_path: str):
        super().__init__(parent)
        self.actors_db = actors_db
        self.all_cells = cells
        self.log_path = log_path
        self._cell_map = {c.short_id: c for c in cells}
        self._active_query = ""

        grids = sorted(set(c.grid_name for c in cells if c.grid_name))
        levels = sorted(set(c.level for c in cells))
        self._grid_options = ["All"] + grids
        self._level_options = ["All"] + [str(l) for l in levels]

        self._build_ui()
        self._apply_filter()

    def _build_ui(self):
        # Filter bar
        top = tk.Frame(self, bg=BG2)
        top.pack(fill=tk.X, padx=8, pady=(8, 2))

        tk.Label(top, text="Grid:", bg=BG2, fg=FG, font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.grid_var = tk.StringVar(value="All")
        ttk.Combobox(top, textvariable=self.grid_var, values=self._grid_options,
                     state="readonly", width=22).pack(side=tk.LEFT, padx=(0, 12))
        self.grid_var.trace_add("write", lambda *_: self._apply_filter())

        tk.Label(top, text="Level:", bg=BG2, fg=FG, font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.level_var = tk.StringVar(value="All")
        ttk.Combobox(top, textvariable=self.level_var, values=self._level_options,
                     state="readonly", width=6).pack(side=tk.LEFT, padx=(0, 12))
        self.level_var.trace_add("write", lambda *_: self._apply_filter())

        tk.Label(top, text="Search:", bg=BG2, fg=FG, font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(top, textvariable=self.search_var, bg=BG, fg=FG, insertbackground=FG,
                                font=("Consolas", 9), width=24, relief=tk.FLAT, bd=2)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        search_entry.bind("<Return>", lambda _: self._do_search())
        tk.Button(top, text="Search", bg="#3c3c3c", fg="#ddd", font=("Consolas", 8),
                  relief=tk.FLAT, padx=8, pady=1, command=self._do_search).pack(side=tk.LEFT)

        # Canvas map
        self.cell_map = CellMapCanvas(self, [], self._on_map_selection)

        # Cell list
        cell_section = tk.Frame(self, bg=BG2)
        cell_section.pack(fill=tk.X, padx=8, pady=(2, 2))

        cell_header = tk.Frame(cell_section, bg=BG2)
        cell_header.pack(fill=tk.X)
        self.cell_list_label = tk.Label(cell_header, text="Selected Cells", bg=BG2, fg=FG, font=("Consolas", 9))
        self.cell_list_label.pack(side=tk.LEFT, padx=4)

        cell_tree_outer = tk.Frame(cell_section, bg=BG, height=130)
        cell_tree_outer.pack(fill=tk.X)
        cell_tree_outer.pack_propagate(False)
        self.cell_tree = ttk.Treeview(cell_tree_outer,
            columns=("cell", "package", "level", "spatial", "always_loaded", "actors"),
            show="headings", selectmode="browse")
        self.cell_tree.heading("cell", text="Cell")
        self.cell_tree.heading("package", text="PackageShortName")
        self.cell_tree.heading("level", text="Level")
        self.cell_tree.heading("spatial", text="Spatial")
        self.cell_tree.heading("always_loaded", text="Always Loaded")
        self.cell_tree.heading("actors", text="Actors")
        self.cell_tree.column("cell", width=160)
        self.cell_tree.column("package", width=200)
        self.cell_tree.column("level", width=50, anchor=tk.CENTER)
        self.cell_tree.column("spatial", width=55, anchor=tk.CENTER)
        self.cell_tree.column("always_loaded", width=90, anchor=tk.CENTER)
        self.cell_tree.column("actors", width=60, anchor=tk.CENTER)
        cs = ttk.Scrollbar(cell_tree_outer, orient=tk.VERTICAL, command=self.cell_tree.yview)
        self.cell_tree.configure(yscrollcommand=cs.set)
        self.cell_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cs.pack(side=tk.RIGHT, fill=tk.Y)
        self.cell_tree.bind("<<TreeviewSelect>>", self._on_cell_tree_select)
        make_sortable(self.cell_tree)

        # Actor list
        actor_section = tk.Frame(self, bg=BG2)
        actor_section.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 4))

        actor_header = tk.Frame(actor_section, bg=BG2)
        actor_header.pack(fill=tk.X)
        self.actor_label = tk.Label(actor_header, text="Actors (double-click to focus)",
                                    bg=BG2, fg=FG, font=("Consolas", 9))
        self.actor_label.pack(side=tk.LEFT, padx=4)

        actor_tree_outer = tk.Frame(actor_section, bg=BG)
        actor_tree_outer.pack(fill=tk.BOTH, expand=True)
        self.actor_tree = ttk.Treeview(actor_tree_outer,
            columns=("name", "class", "package", "radius", "hlod"),
            show="headings", selectmode="browse")
        self.actor_tree.heading("name", text="Name")
        self.actor_tree.heading("class", text="Class")
        self.actor_tree.heading("package", text="Package")
        self.actor_tree.heading("radius", text="Radius")
        self.actor_tree.heading("hlod", text="HLOD")
        self.actor_tree.column("name", width=200)
        self.actor_tree.column("class", width=180)
        self.actor_tree.column("package", width=220)
        self.actor_tree.column("radius", width=65, anchor=tk.E)
        self.actor_tree.column("hlod", width=45, anchor=tk.CENTER)
        as_ = ttk.Scrollbar(actor_tree_outer, orient=tk.VERTICAL, command=self.actor_tree.yview)
        self.actor_tree.configure(yscrollcommand=as_.set)
        self.actor_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        as_.pack(side=tk.RIGHT, fill=tk.Y)
        self.actor_tree.bind("<Double-1>", self._on_actor_dblclick)
        make_sortable(self.actor_tree)

        # Status label (inside the tab)
        self.status_var = tk.StringVar(
            value=f"Cells: {len(self.all_cells)}  |  "
                  f"Actors: {sum(c.actor_count for c in self.all_cells)}")
        tk.Label(self, textvariable=self.status_var, bg="#333", fg="#aaa",
                 font=("Consolas", 9), anchor=tk.W).pack(fill=tk.X)

    def _apply_filter(self):
        grid = self.grid_var.get()
        level = self.level_var.get()
        filtered = []
        for c in self.all_cells:
            if grid != "All" and c.grid_name != grid:
                continue
            if level != "All" and c.level != int(level):
                continue
            filtered.append(c)
        self.cell_map.set_cells(filtered)
        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())

    def _on_map_selection(self, selected: list[Cell]):
        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())
        self.cell_list_label.configure(text=f"Selected Cells: {len(selected)}")
        for cell in sorted(selected, key=lambda c: c.actor_count, reverse=True):
            short = f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}"
            pkg = cell.short_id
            self.cell_tree.insert("", tk.END, iid=cell.short_id,
                values=(short, pkg, cell.level,
                        "Yes" if cell.spatially_loaded else "No",
                        "Yes" if cell.always_loaded else "No",
                        cell.actor_count))

    def _get_actor_info(self, ca: CellActor) -> tuple[str, str, str, str]:
        """Return (class_short, package_short, radius_str, hlod)."""
        cls, hlod, radius_str = "", "", ""
        for ad in self.actors_db.values():
            if ad.name == ca.label or ad.label == ca.label:
                cls = ad.native_class.split(".")[-1] if ad.native_class else ""
                if ad.base_class:
                    cls = ad.base_class.split(".")[-1]
                hlod = "Yes" if ad.hlod_relevant else ""
                bmin, bmax = ad.bounds_min, ad.bounds_max
                if bmin != (0, 0, 0) or bmax != (0, 0, 0):
                    dx = (bmax[0] - bmin[0]) / 2
                    dy = (bmax[1] - bmin[1]) / 2
                    dz = (bmax[2] - bmin[2]) / 2
                    r = (dx*dx + dy*dy + dz*dz) ** 0.5
                    radius_str = f"{r:.0f}" if r >= 1 else f"{r:.1f}"
                break
        pkg = ca.package.rsplit("/", 1)[-1] if ca.package else ""
        return cls, pkg, radius_str, hlod

    def _cell_matches_query(self, cell: Cell, query: str) -> bool:
        cell_str = f"{cell.name} {cell.short_id} L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}".lower()
        return query in cell_str

    def _actor_matches_query(self, ca: CellActor, query: str) -> bool:
        cls, pkg, _, _ = self._get_actor_info(ca)
        return query in f"{ca.label} {cls} {pkg}".lower()

    def _on_cell_tree_select(self, e):
        sel = self.cell_tree.selection()
        if not sel:
            return
        cell = self._cell_map.get(sel[0])
        if not cell:
            return
        self.actor_tree.delete(*self.actor_tree.get_children())
        query = self._active_query
        cell_itself_matched = self._cell_matches_query(cell, query) if query else False

        shown = 0
        for idx, ca in enumerate(cell.actors):
            cls, pkg, radius, hlod = self._get_actor_info(ca)
            if query and not cell_itself_matched:
                if not self._actor_matches_query(ca, query):
                    continue
            self.actor_tree.insert("", tk.END, iid=f"a_{cell.short_id}_{idx}",
                values=(ca.label, cls, pkg, radius, hlod), tags=(ca.label,))
            shown += 1

        label = f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}"
        suffix = " (filtered)" if query and not cell_itself_matched else ""
        self.actor_label.configure(text=f"Actors in {label}: {shown}{suffix}")

    def _do_search(self):
        query = self.search_var.get().strip().lower()
        self._active_query = query
        grid = self.grid_var.get()
        level = self.level_var.get()

        base_cells = []
        for c in self.all_cells:
            if grid != "All" and c.grid_name != grid:
                continue
            if level != "All" and c.level != int(level):
                continue
            base_cells.append(c)

        if not query:
            self.cell_map.set_cells(base_cells)
            self.cell_tree.delete(*self.cell_tree.get_children())
            self.actor_tree.delete(*self.actor_tree.get_children())
            self.cell_list_label.configure(text="Selected Cells")
            return

        matched_cells: list[Cell] = []
        for c in base_cells:
            if self._cell_matches_query(c, query):
                matched_cells.append(c)
                continue
            for a in c.actors:
                if self._actor_matches_query(a, query):
                    matched_cells.append(c)
                    break

        self.cell_map.set_cells(base_cells)
        self.cell_map.selected_cells = matched_cells
        self.cell_map._redraw()

        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())
        self.cell_list_label.configure(text=f"Search Results: {len(matched_cells)} cells")
        for cell in sorted(matched_cells, key=lambda c: c.actor_count, reverse=True):
            short = f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}"
            pkg = cell.short_id
            self.cell_tree.insert("", tk.END, iid=cell.short_id,
                values=(short, pkg, cell.level,
                        "Yes" if cell.spatially_loaded else "No",
                        "Yes" if cell.always_loaded else "No",
                        cell.actor_count))

        if len(matched_cells) == 1:
            only = matched_cells[0]
            self.cell_tree.selection_set(only.short_id)
            self._on_cell_tree_select(None)

    def _on_actor_dblclick(self, e):
        sel = self.actor_tree.selection()
        if not sel:
            return
        values = self.actor_tree.item(sel[0], "values")
        name = values[0] if values else ""
        if not name:
            return
        self.status_var.set(f"Selecting: {name} ...")
        self.update_idletasks()
        def _do():
            try:
                select_and_focus(name)
                self.after(0, lambda: self.status_var.set(f"Focused: {name}"))
            except Exception as ex:
                self.after(0, lambda: self.status_var.set(f"Error: {ex}"))
        threading.Thread(target=_do, daemon=True).start()
