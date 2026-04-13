"""tabs/material_optimizer_tab.py — Material instance optimization helper."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from ..core.bridge import (
    connection,
    browse_to_asset,
    open_asset_editor,
    fetch_material_instance_sizes,
    fix_material_instance_asset,
    optimize_material_instance_group,
)
from ..core.common import make_sortable
from ..core.theme import theme


class MaterialOptimizerTab(ttk.Frame):
    ISSUE_MIN_BYTES = 10 * 1024
    GROUP_MIN_TOTAL_BYTES = 100 * 1024

    def __init__(self, parent):
        super().__init__(parent)
        self.configure(style="Dark.TFrame")
        self._rows: list[dict] = []
        self._filtered_rows: list[dict] = []
        self._issue_rows: list[dict] = []
        self._filtered_issue_rows: list[dict] = []
        self._group_rows: list[dict] = []
        self._build_ui()
        connection.subscribe(self._on_connection_changed)
        self._apply_connection(connection.connected)

    def _build_ui(self):
        top = tk.Frame(self, bg=theme.bg_secondary)
        top.pack(fill=tk.X, padx=10, pady=(10, 6))

        left = tk.Frame(top, bg=theme.bg_secondary)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(left, text="Search:", bg=theme.bg_secondary, fg=theme.fg_secondary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        self.search_entry = tk.Entry(
            left,
            textvariable=self.search_var,
            bg=theme.bg_input,
            fg=theme.fg_primary,
            insertbackground=theme.fg_primary,
            font=theme.font("md"),
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=theme.ctrl_border,
            highlightcolor=theme.accent,
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        right = tk.Frame(top, bg=theme.bg_secondary)
        right.pack(side=tk.RIGHT)

        self.scan_btn = tk.Button(
            right,
            text="  Scan  ",
            bg=theme.action_blue_bg,
            fg=theme.action_blue_fg,
            font=theme.font("md", bold=True),
            relief=tk.FLAT,
            padx=10,
            pady=2,
            cursor="hand2",
            command=self._scan,
        )
        self.scan_btn.pack(side=tk.RIGHT)

        self.summary_var = tk.StringVar(value="No scan yet")
        tk.Label(self, textvariable=self.summary_var, bg=theme.bg_secondary, fg=theme.fg_secondary,
                 font=theme.font("sm"), anchor=tk.W).pack(fill=tk.X, padx=10)

        outer = tk.Frame(self, bg=theme.bg_primary)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))

        panes = ttk.Panedwindow(outer, orient=tk.HORIZONTAL, style="TPanedwindow")
        panes.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(panes, bg=theme.bg_primary)
        right = tk.Frame(panes, bg=theme.bg_primary)
        panes.add(left, weight=5)
        panes.add(right, weight=7)

        right_panes = ttk.Panedwindow(right, orient=tk.VERTICAL, style="TPanedwindow")
        right_panes.pack(fill=tk.BOTH, expand=True)

        mid = tk.Frame(right_panes, bg=theme.bg_primary)
        group = tk.Frame(right_panes, bg=theme.bg_primary)
        right_panes.add(mid, weight=3)
        right_panes.add(group, weight=4)

        tk.Label(left, text="Material Instances", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md", bold=True), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))

        cols = ("name", "parent_name", "size_bytes")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Material Instance")
        self.tree.heading("parent_name", text="Parent Material")
        self.tree.heading("size_bytes", text="Size (KB)")
        self.tree.column("name", width=320, anchor=tk.W)
        self.tree.column("parent_name", width=300, anchor=tk.W)
        self.tree.column("size_bytes", width=100, anchor=tk.E)
        make_sortable(self.tree)

        left_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        left_xscroll = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=left_scroll.set)
        self.tree.configure(xscrollcommand=left_xscroll.set)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        left_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._open_selected)
        self.tree.bind("<Return>", self._open_selected)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())

        mid_header = tk.Frame(mid, bg=theme.bg_secondary)
        mid_header.pack(fill=tk.X, pady=(0, 4))

        tk.Label(mid_header, text="Invalid Override Review", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md", bold=True), anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.fix_btn = tk.Button(
            mid_header,
            text="  Auto Fix All  ",
            bg=theme.ctrl_bg,
            fg=theme.fg_primary,
            font=theme.font("md", bold=True),
            relief=tk.FLAT,
            padx=10,
            pady=2,
            cursor="hand2",
            command=self._fix_selected_issue,
        )
        self.fix_btn.pack(side=tk.RIGHT)

        issue_cols = ("issue_name", "issue_type", "entry_name")
        self.issue_tree = ttk.Treeview(mid, columns=issue_cols, show="headings", selectmode="extended")
        self.issue_tree.heading("issue_name", text="Material Instance")
        self.issue_tree.heading("issue_type", text="Type")
        self.issue_tree.heading("entry_name", text="Entry")
        self.issue_tree.column("issue_name", width=260, anchor=tk.W)
        self.issue_tree.column("issue_type", width=160, anchor=tk.W)
        self.issue_tree.column("entry_name", width=260, anchor=tk.W)
        make_sortable(self.issue_tree)

        right_scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.issue_tree.yview)
        right_xscroll = ttk.Scrollbar(mid, orient=tk.HORIZONTAL, command=self.issue_tree.xview)
        self.issue_tree.configure(yscrollcommand=right_scroll.set)
        self.issue_tree.configure(xscrollcommand=right_xscroll.set)
        self.issue_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        right_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        right_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.issue_tree.bind("<Double-1>", self._open_issue_selected)
        self.issue_tree.bind("<Return>", self._open_issue_selected)
        self.issue_tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())

        group_header = tk.Frame(group, bg=theme.bg_secondary)
        group_header.pack(fill=tk.X, pady=(0, 4))

        tk.Label(group_header, text="BasePropertyOverrides Groups", bg=theme.bg_secondary, fg=theme.fg_primary,
                 font=theme.font("md", bold=True), anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.group_opt_btn = tk.Button(
            group_header,
            text="  Auto Optimize Selected  ",
            bg=theme.ctrl_bg,
            fg=theme.fg_primary,
            font=theme.font("md", bold=True),
            relief=tk.FLAT,
            padx=10,
            pady=2,
            cursor="hand2",
            command=self._optimize_selected_group,
        )
        self.group_opt_btn.pack(side=tk.RIGHT)

        group_cols = ("count", "total_kb", "avg_kb")
        self.group_tree = ttk.Treeview(group, columns=group_cols, show="tree headings", selectmode="browse")
        self.group_tree.heading("#0", text="Parent / Override Signature")
        self.group_tree.heading("count", text="Instances")
        self.group_tree.heading("total_kb", text="Total KB")
        self.group_tree.heading("avg_kb", text="Avg KB")
        self.group_tree.column("#0", width=360, stretch=True, anchor=tk.W)
        self.group_tree.column("count", width=80, anchor=tk.E)
        self.group_tree.column("total_kb", width=90, anchor=tk.E)
        self.group_tree.column("avg_kb", width=90, anchor=tk.E)
        make_sortable(self.group_tree)

        group_scroll = ttk.Scrollbar(group, orient=tk.VERTICAL, command=self.group_tree.yview)
        group_xscroll = ttk.Scrollbar(group, orient=tk.HORIZONTAL, command=self.group_tree.xview)
        self.group_tree.configure(yscrollcommand=group_scroll.set)
        self.group_tree.configure(xscrollcommand=group_xscroll.set)
        self.group_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        group_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        group_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.group_tree.bind("<Double-1>", self._open_group_selected)
        self.group_tree.bind("<Return>", self._open_group_selected)
        self.group_tree.bind("<<TreeviewSelect>>", lambda e: self._update_detail())

        self.detail_var = tk.StringVar(value="Double-click a row to open the asset editor.")
        tk.Label(self, textvariable=self.detail_var, bg=theme.bg_secondary, fg=theme.fg_secondary,
                 font=theme.font("sm"), anchor=tk.W).pack(fill=tk.X, padx=10, pady=(0, 8))

    def _set_busy(self, busy: bool):
        if busy:
            self.scan_btn.configure(state=tk.DISABLED, bg=theme.bg_tertiary, fg=theme.fg_secondary)
            self.fix_btn.configure(state=tk.DISABLED, bg=theme.bg_tertiary, fg=theme.fg_secondary)
            self.group_opt_btn.configure(state=tk.DISABLED, bg=theme.bg_tertiary, fg=theme.fg_secondary)
        else:
            self.scan_btn.configure(state=tk.NORMAL, bg=theme.action_blue_bg, fg=theme.action_blue_fg)
            self.fix_btn.configure(state=tk.NORMAL, bg=theme.ctrl_bg, fg=theme.fg_primary)
            self.group_opt_btn.configure(state=tk.NORMAL, bg=theme.ctrl_bg, fg=theme.fg_primary)

    def _scan(self):
        if not connection.connected:
            self.summary_var.set("Editor disconnected — scan unavailable")
            return
        self.summary_var.set("Scanning material instances...")
        self._set_busy(True)

        def _bg():
            payload = fetch_material_instance_sizes()
            self.after(0, lambda: self._scan_done(payload))

        threading.Thread(target=_bg, daemon=True).start()

    def _scan_done(self, payload: dict):
        self._set_busy(False)
        error = payload.get("error")
        if error:
            self.summary_var.set(f"Scan failed: {error}")
            return

        self._rows = list(payload.get("rows") or [])
        self._issue_rows = [
            row for row in (payload.get("issue_rows") or [])
            if int(row.get("size_bytes", 0) or 0) > self.ISSUE_MIN_BYTES
        ]
        self._apply_filter()
        self._project_mount = payload.get("project_mount") or "(unknown mount)"
        self._update_summary()

    def _apply_filter(self):
        needle = self.search_var.get().strip().lower()
        if not needle:
            self._filtered_rows = list(self._rows)
            self._filtered_issue_rows = list(self._issue_rows)
        else:
            self._filtered_rows = [
                row for row in self._rows
                if needle in row.get("name", "").lower()
                or needle in row.get("parent_name", "").lower()
                or needle in row.get("path", "").lower()
                or needle in row.get("parent_path", "").lower()
            ]
            self._filtered_issue_rows = [
                row for row in self._issue_rows
                if needle in row.get("name", "").lower()
                or needle in row.get("parent_name", "").lower()
                or needle in row.get("path", "").lower()
                or needle in row.get("parent_path", "").lower()
                or needle in row.get("issue_type", "").lower()
                or needle in row.get("entry_name", "").lower()
                or needle in row.get("note", "").lower()
            ]
        self._rebuild_tree()
        self._update_summary()

    def _build_group_rows(self):
        groups: dict[str, dict[str, list[dict]]] = {}
        for row in self._filtered_rows:
            signature = row.get("base_override_signature", "")
            if not signature:
                continue
            parent_name = row.get("parent_name", "") or "(No Parent)"
            groups.setdefault(parent_name, {}).setdefault(signature, []).append(row)
        result = []
        for parent_name, sig_map in groups.items():
            sig_rows = []
            for signature, rows in sorted(sig_map.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())):
                total = sum(int(r.get("size_bytes", 0) or 0) for r in rows)
                if total < self.GROUP_MIN_TOTAL_BYTES:
                    continue
                count = len(rows)
                avg = total / count if count else 0
                sig_rows.append({
                    "signature": signature,
                    "count": count,
                    "total": total,
                    "avg": avg,
                    "rows": rows,
                })
            parent_total = sum(int(sig["total"]) for sig in sig_rows)
            parent_count = sum(int(sig["count"]) for sig in sig_rows)
            result.append({
                "parent_name": parent_name,
                "count": parent_count,
                "total": parent_total,
                "avg": parent_total / parent_count if parent_count else 0,
                "signatures": sig_rows,
            })
        result = [item for item in result if item["signatures"]]
        result.sort(key=lambda item: (-item["count"], -item["total"], item["parent_name"].lower()))
        self._group_rows = result

    def _update_summary(self):
        total_all = sum(int(row.get("size_bytes", 0) or 0) for row in self._rows)
        total_filtered = sum(int(row.get("size_bytes", 0) or 0) for row in self._filtered_rows)
        mount = getattr(self, "_project_mount", "(unknown mount)")
        if self._rows:
            self.summary_var.set(
                f"{len(self._filtered_rows)}/{len(self._rows)} material instances | "
                f"Issues: {len(self._filtered_issue_rows)}/{len(self._issue_rows)} | "
                f"Filtered total: {self._format_size(total_filtered)} | "
                f"All total: {self._format_size(total_all)} | {mount}"
            )
        else:
            self.summary_var.set("No scan yet")

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        units = ("bytes", "KB", "MB", "GB", "TB")
        value = float(max(0, int(num_bytes)))
        unit = units[0]
        for next_unit in units[1:]:
            if value < 1024.0:
                break
            value /= 1024.0
            unit = next_unit
        if unit == "bytes":
            return f"{int(value):,} bytes"
        if value >= 100:
            return f"{value:,.0f} {unit}"
        if value >= 10:
            return f"{value:,.1f} {unit}"
        return f"{value:,.2f} {unit}"

    @staticmethod
    def _format_kb(num_bytes: int) -> str:
        value = max(0, int(num_bytes)) / 1024.0
        if value >= 100:
            return f"{value:,.0f}"
        if value >= 10:
            return f"{value:,.1f}"
        return f"{value:,.2f}"

    def _rebuild_tree(self):
        self._build_group_rows()
        self.tree.delete(*self.tree.get_children(""))
        for idx, row in enumerate(self._filtered_rows):
            size_bytes = int(row.get("size_bytes", 0) or 0)
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    row.get("name", ""),
                    row.get("parent_name", ""),
                    self._format_kb(size_bytes),
                ),
            )
        self.issue_tree.delete(*self.issue_tree.get_children(""))
        for idx, row in enumerate(self._filtered_issue_rows):
            self.issue_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    row.get("name", ""),
                    row.get("issue_type", ""),
                    row.get("entry_name", ""),
                ),
            )
        self.group_tree.delete(*self.group_tree.get_children(""))
        for pidx, parent in enumerate(self._group_rows):
            pid = f"p:{pidx}"
            self.group_tree.insert(
                "",
                tk.END,
                iid=pid,
                text=parent.get("parent_name", ""),
                values=(
                    parent.get("count", 0),
                    self._format_kb(int(parent.get("total", 0))),
                    self._format_kb(int(parent.get("avg", 0))),
                ),
                open=False,
            )
            for sidx, sig in enumerate(parent.get("signatures", [])):
                sid = f"{pid}:s:{sidx}"
                self.group_tree.insert(
                    pid,
                    tk.END,
                    iid=sid,
                    text=sig.get("signature", ""),
                    values=(
                        sig.get("count", 0),
                        self._format_kb(int(sig.get("total", 0))),
                        self._format_kb(int(sig.get("avg", 0))),
                    ),
                    open=False,
                )
                for ridx, row in enumerate(sig.get("rows", [])):
                    self.group_tree.insert(
                        sid,
                        tk.END,
                        iid=f"{sid}:r:{ridx}",
                        text=row.get("name", ""),
                        values=(
                            1,
                            self._format_kb(int(row.get("size_bytes", 0) or 0)),
                            self._format_kb(int(row.get("size_bytes", 0) or 0)),
                        ),
                    )
        self.detail_var.set(
            f"{len(self._filtered_rows)} materials shown | {len(self._filtered_issue_rows)} review issues shown | {len(self._group_rows)} parent groups"
        )

    def _selected_row(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self._filtered_rows[int(sel[0])]
        except Exception:
            return None

    def _update_detail(self):
        issue_row = self._selected_issue_row()
        if issue_row:
            size_bytes = int(issue_row.get("size_bytes", 0) or 0)
            note = issue_row.get("note", "")
            self.detail_var.set(
                f"{issue_row.get('path', '')} | {issue_row.get('issue_type', '')} / {issue_row.get('entry_name', '')} | "
                f"{self._format_kb(size_bytes)} KB"
                + (f" | {note}" if note else "")
            )
            return
        row = self._selected_row()
        if row:
            size_bytes = int(row.get("size_bytes", 0) or 0)
            self.detail_var.set(
                f"{row.get('path', '')} | parent: {row.get('parent_path', '')} | {self._format_kb(size_bytes)} KB"
            )
            return
        group_row = self._selected_group_asset_row()
        if group_row:
            size_bytes = int(group_row.get("size_bytes", 0) or 0)
            self.detail_var.set(
                f"{group_row.get('path', '')} | parent: {group_row.get('parent_path', '')} | overrides: {group_row.get('base_override_signature', '')} | {self._format_kb(size_bytes)} KB"
            )

    def _open_selected(self, _event=None):
        row = self._selected_row()
        if not row:
            return
        browse_to_asset(row.get("path", ""))
        open_asset_editor(row.get("path", ""))
        self._update_detail()

    def _selected_issue_row(self) -> dict | None:
        sel = self.issue_tree.selection()
        if not sel:
            return None
        try:
            return self._filtered_issue_rows[int(sel[0])]
        except Exception:
            return None

    def _open_issue_selected(self, _event=None):
        row = self._selected_issue_row()
        if not row:
            return
        browse_to_asset(row.get("path", ""))
        open_asset_editor(row.get("path", ""))
        self._update_detail()

    def _selected_group_asset_row(self) -> dict | None:
        sel = self.group_tree.selection()
        if not sel:
            return None
        iid = sel[0]
        parts = iid.split(":")
        if len(parts) != 6 or parts[0] != "p" or parts[2] != "s" or parts[4] != "r":
            return None
        try:
            parent = self._group_rows[int(parts[1])]
            sig = parent["signatures"][int(parts[3])]
            return sig["rows"][int(parts[5])]
        except Exception:
            return None

    def _open_group_selected(self, _event=None):
        row = self._selected_group_asset_row()
        if not row:
            return
        browse_to_asset(row.get("path", ""))
        open_asset_editor(row.get("path", ""))
        self._update_detail()

    def _selected_group_signature_rows(self) -> list[dict]:
        sel = self.group_tree.selection()
        if not sel:
            return []
        iid = sel[0]
        parts = iid.split(":")
        try:
            if len(parts) == 4 and parts[0] == "p" and parts[2] == "s":
                parent = self._group_rows[int(parts[1])]
                sig = parent["signatures"][int(parts[3])]
                return list(sig["rows"])
            if len(parts) == 2 and parts[0] == "p":
                parent = self._group_rows[int(parts[1])]
                rows: list[dict] = []
                for sig in parent["signatures"]:
                    rows.extend(sig["rows"])
                return rows
            if len(parts) == 6 and parts[0] == "p" and parts[2] == "s" and parts[4] == "r":
                parent = self._group_rows[int(parts[1])]
                sig = parent["signatures"][int(parts[3])]
                return list(sig["rows"])
        except Exception:
            return []
        return []

    def _optimize_selected_group(self):
        rows = self._selected_group_signature_rows()
        if not rows:
            self.detail_var.set("Select a group row on the bottom-right tree before optimizing.")
            return
        if not connection.connected:
            self.detail_var.set("Editor disconnected - optimize unavailable")
            return
        self._set_busy(True)
        signature = rows[0].get("base_override_signature", "")
        self.detail_var.set(
            f"Optimizing {len(rows)} material instances for signature: {signature}"
        )

        def _bg():
            self.after(
                0,
                lambda: self.detail_var.set(
                    f"Optimizing 1/1 group | {len(rows)} instances | {signature}"
                ),
            )
            result = optimize_material_instance_group(rows)
            self.after(0, lambda: self._optimize_done(result))

        threading.Thread(target=_bg, daemon=True).start()

    def _optimize_done(self, payload: dict):
        self._set_busy(False)
        if not payload.get("optimized"):
            self.detail_var.set(f"Optimize failed: {payload.get('error', 'unknown error')}")
            return
        self.detail_var.set(
            f"Created shared parent {payload.get('shared_parent_path', '')} and reparented {payload.get('child_count', 0)} children"
        )
        self._scan()

    def _fix_selected_issue(self):
        rows = list(self._filtered_issue_rows)
        if not rows:
            self.detail_var.set("No invalid override rows to fix.")
            return
        if not connection.connected:
            self.detail_var.set("Editor disconnected - fix unavailable")
            return
        self._set_busy(True)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row.get("path", ""), []).append(row)
        self.detail_var.set(
            f"Auto-fixing {len(rows)} issues across {len(grouped)} assets ..."
        )

        def _bg():
            results = []
            total = len(grouped)
            for idx, (path, asset_issues) in enumerate(grouped.items(), start=1):
                self.after(
                    0,
                    lambda i=idx, t=total, p=path, c=len(asset_issues): self.detail_var.set(
                        f"Auto-fixing {i}/{t} assets | {c} issues | {p}"
                    ),
                )
                result = fix_material_instance_asset(
                    path,
                    asset_issues,
                )
                if not result.get("fixed"):
                    result["_path"] = path
                results.append(result)
            self.after(0, lambda: self._fix_done(results))

        threading.Thread(target=_bg, daemon=True).start()

    def _fix_done(self, payloads: list[dict]):
        self._set_busy(False)
        failures = [p for p in payloads if not p.get("fixed")]
        if failures:
            first = failures[0]
            suffix = f" ({len(failures)} failed)" if len(failures) > 1 else ""
            self.detail_var.set(
                f"Fix failed on {first.get('_path', first.get('path', 'unknown asset'))}: "
                f"{first.get('error', 'unknown error')}{suffix}"
            )
            return
        if len(payloads) == 1:
            payload = payloads[0]
            self.detail_var.set(
                f"Auto-fixed 1 asset: {payload.get('path', '')}"
            )
        else:
            self.detail_var.set(f"Auto-fixed {len(payloads)} assets")
        self._scan()

    def _on_connection_changed(self, connected: bool):
        self.after(0, lambda: self._apply_connection(connected))

    def _apply_connection(self, connected: bool):
        state = tk.NORMAL if connected else tk.DISABLED
        self.search_entry.configure(state=state)
        if not connected:
            self._set_busy(True)
            self.summary_var.set("Editor disconnected — scan unavailable")
        else:
            self._set_busy(False)
