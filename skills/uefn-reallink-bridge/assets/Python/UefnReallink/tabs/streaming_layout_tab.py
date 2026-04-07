"""tabs/streaming_layout_tab.py — Streaming Layout Tab（原 wp_layout_tab.py）"""

import os
import threading
import tkinter as tk
from tkinter import ttk

from ..core.common import ActorDesc, CellActor, Cell, make_sortable
from ..core.theme import theme
from ..core.bridge import connection, select_and_focus
from ..widgets.cell_map_canvas import CellMapCanvas


class StreamingLayoutTab(ttk.Frame):

    def __init__(self, parent, actors_db: dict[str, ActorDesc],
                 cells: list[Cell], log_path: str, on_refresh=None):
        super().__init__(parent)
        self.actors_db = actors_db
        self.all_cells = cells
        self.log_path = log_path
        self._cell_map = {c.short_id: c for c in cells}
        self._active_query = ""
        self._on_refresh = on_refresh

        grids = sorted(set(c.grid_name for c in cells if c.grid_name))
        levels = sorted(set(c.level for c in cells))
        self._grid_options = ["All"] + grids
        self._level_options = ["All"] + [str(l) for l in levels]

        self._build_ui()
        self._apply_filter()

        connection.subscribe(self._on_connection_changed)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        top = tk.Frame(self, bg=theme.bg_secondary)
        top.pack(fill=tk.X, padx=8, pady=(8, 2))

        tk.Label(top, text="Grid:", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 4))
        self.grid_var = tk.StringVar(value="All")
        self._grid_combo = ttk.Combobox(top, textvariable=self.grid_var,
                                        values=self._grid_options,
                                        state="readonly", width=22)
        self._grid_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.grid_var.trace_add("write", lambda *_: self._apply_filter())

        tk.Label(top, text="Level:", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 4))
        self.level_var = tk.StringVar(value="All")
        self._level_combo = ttk.Combobox(top, textvariable=self.level_var,
                                         values=self._level_options,
                                         state="readonly", width=6)
        self._level_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.level_var.trace_add("write", lambda *_: self._apply_filter())

        tk.Label(top, text="Search:", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 4))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(top, textvariable=self.search_var,
                                bg=theme.bg_primary, fg=theme.fg_primary,
                                insertbackground=theme.fg_primary,
                                font=theme.font("md"), width=24,
                                relief=tk.FLAT, bd=2)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        search_entry.bind("<Return>", lambda _: self._do_search())
        tk.Button(top, text="Search", bg=theme.ctrl_bg, fg=theme.fg_primary,
                  font=theme.font("sm"), relief=tk.FLAT, padx=8, pady=1,
                  command=self._do_search).pack(side=tk.LEFT)

        self._refresh_btn = tk.Button(top, text="⟳ Refresh",
                                      bg=theme.action_blue_bg,
                                      fg=theme.action_blue_fg,
                                      font=theme.font("md", bold=True),
                                      relief=tk.FLAT, padx=8, pady=1,
                                      command=self._on_refresh)
        if self._on_refresh:
            self._refresh_btn.pack(side=tk.RIGHT, padx=(4, 0))

        # Canvas map
        self.cell_map = CellMapCanvas(self, [], self._on_map_selection)

        # Cell list
        cell_section = tk.Frame(self, bg=theme.bg_secondary)
        cell_section.pack(fill=tk.X, padx=8, pady=(2, 2))

        cell_header = tk.Frame(cell_section, bg=theme.bg_secondary)
        cell_header.pack(fill=tk.X)
        self.cell_list_label = tk.Label(cell_header, text="Selected Cells",
                                        bg=theme.bg_secondary, fg=theme.fg_primary,
                                        font=theme.font("md"))
        self.cell_list_label.pack(side=tk.LEFT, padx=4)

        cell_tree_outer = tk.Frame(cell_section, bg=theme.bg_primary, height=130)
        cell_tree_outer.pack(fill=tk.X)
        cell_tree_outer.pack_propagate(False)
        self.cell_tree = ttk.Treeview(
            cell_tree_outer,
            columns=("cell", "package", "level", "spatial", "always_loaded", "actors"),
            show="headings", selectmode="browse")
        for col, text, w, anchor in [
            ("cell", "Cell", 160, tk.W),
            ("package", "PackageShortName", 200, tk.W),
            ("level", "Level", 50, tk.CENTER),
            ("spatial", "Spatial", 55, tk.CENTER),
            ("always_loaded", "Always Loaded", 90, tk.CENTER),
            ("actors", "Actors", 60, tk.CENTER),
        ]:
            self.cell_tree.heading(col, text=text)
            self.cell_tree.column(col, width=w, anchor=anchor)
        cs = ttk.Scrollbar(cell_tree_outer, orient=tk.VERTICAL,
                           command=self.cell_tree.yview)
        self.cell_tree.configure(yscrollcommand=cs.set)
        self.cell_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cs.pack(side=tk.RIGHT, fill=tk.Y)
        self.cell_tree.bind("<<TreeviewSelect>>", self._on_cell_tree_select)
        make_sortable(self.cell_tree)

        # Actor list
        actor_section = tk.Frame(self, bg=theme.bg_secondary)
        actor_section.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 4))

        actor_header = tk.Frame(actor_section, bg=theme.bg_secondary)
        actor_header.pack(fill=tk.X)
        self.actor_label = tk.Label(actor_header,
                                    text="Actors (double-click to focus in editor)",
                                    bg=theme.bg_secondary, fg=theme.fg_primary,
                                    font=theme.font("md"))
        self.actor_label.pack(side=tk.LEFT, padx=4)

        actor_tree_outer = tk.Frame(actor_section, bg=theme.bg_primary)
        actor_tree_outer.pack(fill=tk.BOTH, expand=True)
        self.actor_tree = ttk.Treeview(
            actor_tree_outer,
            columns=("name", "class", "package", "radius", "hlod"),
            show="headings", selectmode="browse")
        for col, text, w, anchor in [
            ("name", "Name", 200, tk.W),
            ("class", "Class", 180, tk.W),
            ("package", "Package", 220, tk.W),
            ("radius", "Radius", 65, tk.E),
            ("hlod", "HLOD", 45, tk.CENTER),
        ]:
            self.actor_tree.heading(col, text=text)
            self.actor_tree.column(col, width=w, anchor=anchor)
        as_ = ttk.Scrollbar(actor_tree_outer, orient=tk.VERTICAL,
                            command=self.actor_tree.yview)
        self.actor_tree.configure(yscrollcommand=as_.set)
        self.actor_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        as_.pack(side=tk.RIGHT, fill=tk.Y)
        self.actor_tree.bind("<Double-1>", self._on_actor_dblclick)
        make_sortable(self.actor_tree)

        self.status_var = tk.StringVar(
            value=f"Cells: {len(self.all_cells)}  |  "
                  f"Actors: {sum(c.actor_count for c in self.all_cells)}")
        tk.Label(self, textvariable=self.status_var, bg=theme.bg_tertiary,
                 fg=theme.fg_secondary, font=theme.font("md"),
                 anchor=tk.W).pack(fill=tk.X)

    # ── Filter / Search ───────────────────────────────────────────────────────

    def _apply_filter(self):
        grid = self.grid_var.get()
        level = self.level_var.get()
        filtered = [
            c for c in self.all_cells
            if (grid == "All" or c.grid_name == grid) and
               (level == "All" or c.level == int(level))
        ]
        self.cell_map.reload_cells(filtered)
        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())

    def _do_search(self):
        query = self.search_var.get().strip().lower()
        self._active_query = query
        grid = self.grid_var.get()
        level = self.level_var.get()

        base_cells = [
            c for c in self.all_cells
            if (grid == "All" or c.grid_name == grid) and
               (level == "All" or c.level == int(level))
        ]

        if not query:
            self.cell_map.reload_cells(base_cells)
            self.cell_tree.delete(*self.cell_tree.get_children())
            self.actor_tree.delete(*self.actor_tree.get_children())
            self.cell_list_label.configure(text="Selected Cells")
            return

        matched: list[Cell] = []
        for c in base_cells:
            if self._cell_matches_query(c, query):
                matched.append(c)
                continue
            if any(self._actor_matches_query(a, query) for a in c.actors):
                matched.append(c)

        self.cell_map.reload_cells(base_cells)
        self.cell_map.selected_cells = matched
        self.cell_map._redraw()

        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())
        self.cell_list_label.configure(
            text=f"Search Results: {len(matched)} cells")
        for cell in sorted(matched, key=lambda c: c.actor_count, reverse=True):
            self.cell_tree.insert("", tk.END, iid=cell.short_id,
                values=(f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}",
                        cell.short_id, cell.level,
                        "Yes" if cell.spatially_loaded else "No",
                        "Yes" if cell.always_loaded else "No",
                        cell.actor_count))
        if len(matched) == 1:
            self.cell_tree.selection_set(matched[0].short_id)
            self._on_cell_tree_select(None)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_map_selection(self, selected: list[Cell]):
        self.cell_tree.delete(*self.cell_tree.get_children())
        self.actor_tree.delete(*self.actor_tree.get_children())
        self.cell_list_label.configure(
            text=f"Selected Cells: {len(selected)}")
        for cell in sorted(selected, key=lambda c: c.actor_count, reverse=True):
            self.cell_tree.insert("", tk.END, iid=cell.short_id,
                values=(f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}",
                        cell.short_id, cell.level,
                        "Yes" if cell.spatially_loaded else "No",
                        "Yes" if cell.always_loaded else "No",
                        cell.actor_count))

    def _on_cell_tree_select(self, e):
        sel = self.cell_tree.selection()
        if not sel:
            return
        cell = self._cell_map.get(sel[0])
        if not cell:
            return
        self.actor_tree.delete(*self.actor_tree.get_children())
        query = self._active_query
        cell_matched = self._cell_matches_query(cell, query) if query else False
        shown = 0
        for idx, ca in enumerate(cell.actors):
            if query and not cell_matched:
                if not self._actor_matches_query(ca, query):
                    continue
            cls, pkg, radius, hlod = self._get_actor_info(ca)
            self.actor_tree.insert("", tk.END,
                iid=f"a_{cell.short_id}_{idx}",
                values=(ca.label, cls, pkg, radius, hlod),
                tags=(ca.label,))
            shown += 1
        label = f"L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}"
        suffix = " (filtered)" if query and not cell_matched else ""
        self.actor_label.configure(
            text=f"Actors in {label}: {shown}{suffix}")

    def _on_actor_dblclick(self, e):
        sel = self.actor_tree.selection()
        if not sel:
            return
        values = self.actor_tree.item(sel[0], "values")
        name = values[0] if values else ""
        if not name:
            return
        if not connection.connected:
            self.status_var.set(f"[Disconnected] Cannot focus: {name}")
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

    def _on_connection_changed(self, connected: bool):
        self.after(0, lambda: self._apply_connection_state(connected))

    def _apply_connection_state(self, connected: bool):
        if self._on_refresh:
            self._refresh_btn.configure(
                state=tk.NORMAL if connected else tk.DISABLED,
                fg=theme.action_blue_fg if connected else theme.fg_muted)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_actor_info(self, ca: CellActor) -> tuple[str, str, str, str]:
        cls, hlod, radius_str = "", "", ""
        for ad in self.actors_db.values():
            if ad.name == ca.label or ad.label == ca.label:
                cls = ad.base_class.split(".")[-1] if ad.base_class else \
                      ad.native_class.split(".")[-1] if ad.native_class else ""
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
        s = f"{cell.name} {cell.short_id} L{cell.level}_X{cell.grid_x}_Y{cell.grid_y}".lower()
        return query in s

    def _actor_matches_query(self, ca: CellActor, query: str) -> bool:
        cls, pkg, _, _ = self._get_actor_info(ca)
        return query in f"{ca.label} {cls} {pkg}".lower()

    # ── Reload ────────────────────────────────────────────────────────────────

    def reload(self, actors_db, cells, log_path):
        self.actors_db = actors_db
        self.all_cells = cells
        self.log_path = log_path
        self._cell_map = {c.short_id: c for c in cells}
        self._active_query = ""

        grids = sorted(set(c.grid_name for c in cells if c.grid_name))
        levels = sorted(set(c.level for c in cells))
        self._grid_options = ["All"] + grids
        self._level_options = ["All"] + [str(l) for l in levels]
        self._grid_combo.configure(values=self._grid_options)
        self._level_combo.configure(values=self._level_options)
        self.grid_var.set("All")
        self.level_var.set("All")
        self._apply_filter()

        total = sum(c.actor_count for c in cells)
        self.status_var.set(
            f"Cells: {len(cells)}  |  Actors: {total}  |  "
            f"{os.path.basename(log_path) if log_path else 'no log'}")
