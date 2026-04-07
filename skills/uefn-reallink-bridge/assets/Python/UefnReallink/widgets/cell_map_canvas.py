"""widgets/cell_map_canvas.py — Canvas-based 2D cell map with pan, zoom, drag-select."""

from __future__ import annotations

import tkinter as tk
from ..core.common import Cell, heatmap_color
from ..core.theme import theme


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

        frame = tk.Frame(parent, bg=theme.bg_primary)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        top_bar = tk.Frame(frame, bg=theme.bg_primary)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        self.count_label = tk.Label(top_bar, text=f"Count: {len(cells)}", bg=theme.bg_primary, fg=theme.fg_secondary,
                                    font=theme.font("sm"), anchor=tk.W)
        self.count_label.pack(side=tk.LEFT, padx=4)
        fit_btn = tk.Button(top_bar, text="Fit", bg=theme.ctrl_bg, fg=theme.fg_primary, font=theme.font("sm"),
                            relief=tk.FLAT, padx=6, pady=1, command=self.fit_view)
        fit_btn.pack(side=tk.RIGHT, padx=4)
        self.coord_label = tk.Label(top_bar, text="", bg=theme.bg_primary, fg=theme.fg_secondary,
                                    font=theme.font("sm"), anchor=tk.E)
        self.coord_label.pack(side=tk.RIGHT, padx=4)
        self.zoom_label = tk.Label(top_bar, text="100%", bg=theme.bg_primary, fg=theme.fg_secondary, font=theme.font("sm"))
        self.zoom_label.pack(side=tk.RIGHT, padx=4)

        self.canvas = tk.Canvas(frame, bg=theme.bg_primary, highlightthickness=0, cursor="cross")
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

    # ── World / Screen transforms ─────────────────────────────────────────────

    def _compute_world_bounds(self):
        if not self.cells:
            return (-1, -1, 1, 1)
        min_x = min(c.cell_bounds_min[0] for c in self.cells)
        max_x = max(c.cell_bounds_max[0] for c in self.cells)
        min_y = min(c.cell_bounds_min[1] for c in self.cells)
        max_y = max(c.cell_bounds_max[1] for c in self.cells)
        return (min_x, min_y, max_x, max_y)

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

    def reload_cells(self, cells: list[Cell]):
        self.cells = cells
        self.selected_cells = []
        self.hovered_cell = None
        self._world_bounds = self._compute_world_bounds()
        self.count_label.configure(text=f"Count: {len(cells)}")
        self.fit_view()

    # ── Drawing ───────────────────────────────────────────────────────────────

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
            outline = theme.grid_line
            width = 1

            if cell.short_id in sel_ids:
                fill = theme.cell_selected_fill
                outline = theme.cell_selected_outline
                width = 2

            tag = f"c_{cell.short_id}"
            c.create_rectangle(sx1, sy1, sx2, sy2,
                               fill=fill, outline=outline, width=width, tags=(tag,))

            rw = abs(sx2 - sx1)
            rh = abs(sy2 - sy1)
            if rw > 28 and rh > 14:
                idx = f"X{cell.grid_x} Y{cell.grid_y}"
                c.create_text((sx1 + sx2) / 2, (sy1 + sy2) / 2, text=idx, fill=theme.cell_text,
                              font=theme.font("xs") if rw < 50 else theme.font("sm"), tags=(tag,))

        if self._dragging:
            dsx, dsy = self._w2s(*self._drag_start_w)
            c.create_rectangle(dsx, dsy, self._mouse_x, self._mouse_y,
                               outline=theme.drag_rect, width=1, dash=(4, 2), tags=("sel_rect",))

        self.count_label.configure(text=f"Count: {len(self.cells)}")
        self.zoom_label.configure(text=f"{self.scale * 100:.0f}%")

    # ── Hit testing ───────────────────────────────────────────────────────────

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
        for c_ in self.cells:
            cx0, cy0 = c_.cell_bounds_min[0], c_.cell_bounds_min[1]
            cx1, cy1 = c_.cell_bounds_max[0], c_.cell_bounds_max[1]
            if cx1 >= x0 and cx0 <= x1 and cy1 >= y0 and cy0 <= y1:
                result.append(c_)
        return result

    # ── Mouse events ──────────────────────────────────────────────────────────

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
                    for c_ in new_sel:
                        if c_ not in self.selected_cells:
                            self.selected_cells.append(c_)
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
        c_ = self.hovered_cell
        self._tooltip = tk.Toplevel(self.canvas)
        self._tooltip.wm_overrideredirect(True)
        self._tooltip.attributes("-topmost", True)
        cx = self.canvas.winfo_rootx() + e.x + 14
        cy = self.canvas.winfo_rooty() + e.y + 14
        self._tooltip.geometry(f"+{cx}+{cy}")
        txt = f"{c_.name}\nActors: {c_.actor_count}\nL{c_.level} X{c_.grid_x} Y{c_.grid_y}"
        if c_.always_loaded:
            txt += "\n[Always Loaded]"
        tk.Label(self._tooltip, text=txt, bg=theme.bg_tooltip, fg=theme.fg_bright, font=theme.font("md"),
                 justify=tk.LEFT, padx=6, pady=3, relief=tk.SOLID, bd=1).pack()
