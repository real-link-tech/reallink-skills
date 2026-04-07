"""
reallink_uefn_editor.py — Reallink UEFN Editor (入口)
=====================================================
Usage:
  python reallink_uefn_editor.py
  python -m UefnReallink.reallink_uefn_editor
"""

from __future__ import annotations

import os
import sys
import time
import glob
import threading
import tkinter as tk
from tkinter import ttk

# 支持直接运行：将包的父目录加入 sys.path
if __name__ == "__main__" and __package__ is None:
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_this_dir)
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    __package__ = "UefnReallink"

from .core.theme import theme
from .core.bridge import connection, trigger_dump, find_latest_log
from .core.parser import parse_log
from .tabs.common_tab import CommonTab
from .tabs.streaming_layout_tab import StreamingLayoutTab
from .tabs.memory_test_tab import MemoryTab
from .widgets.connection_status import ConnectionStatusBar


def _find_existing_log() -> str | None:
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                           "UnrealEditorFortnite", "Saved", "Logs",
                           "WorldPartition")
    if not os.path.isdir(log_dir):
        return None
    files = sorted(glob.glob(os.path.join(log_dir, "StreamingGeneration-*.log")),
                   key=os.path.getmtime, reverse=True)
    return files[0] if files else None


class ReallinkUefnEditor(tk.Tk):

    def __init__(self, actors, cells, log_path):
        super().__init__()
        self.title("Reallink UEFN Editor")
        self.geometry("1400x900")
        self.minsize(900, 600)
        self.attributes("-topmost", True)
        self.configure(bg=theme.bg_secondary)

        self._setup_styles()

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.common_tab = CommonTab(notebook)
        notebook.add(self.common_tab, text="Common")

        self.layout_tab = StreamingLayoutTab(
            notebook, actors, cells, log_path,
            on_refresh=self._on_refresh)
        notebook.add(self.layout_tab, text="StreamingLayout")

        project_name = (os.path.basename(os.path.dirname(log_path))
                        if log_path else "")
        self.memory_tab = MemoryTab(notebook, actors, cells,
                                    project_name=project_name)
        notebook.add(self.memory_tab, text="MemoryTest")

        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        bottom = tk.Frame(self, bg=theme.bg_tertiary)
        bottom.pack(fill=tk.X)

        total = sum(c.actor_count for c in cells)
        log_name = os.path.basename(log_path) if log_path else "no log"
        status = f"Cells: {len(cells)} | Actors: {total} | {log_name}"
        tk.Label(bottom, text=status, bg=theme.bg_tertiary, fg=theme.fg_secondary,
                 font=theme.font("md"), anchor=tk.W).pack(side=tk.LEFT, fill=tk.X,
                                                           expand=True)

        self._conn_bar = ConnectionStatusBar(bottom)
        self._conn_bar.pack(side=tk.RIGHT)

        connection.start()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=theme.bg_secondary, foreground=theme.fg_primary,
                         borderwidth=0, focuscolor=theme.bg_secondary, relief=tk.FLAT)
        style.configure("TFrame", background=theme.bg_secondary, borderwidth=0)
        style.configure("Dark.TFrame", background=theme.bg_secondary, borderwidth=0)
        style.configure("TLabelframe", background=theme.bg_secondary,
                         foreground=theme.fg_primary, borderwidth=0)
        style.configure("TLabelframe.Label", background=theme.bg_secondary,
                         foreground=theme.fg_primary)
        style.configure("TPanedwindow", background=theme.bg_secondary)

        style.configure("TNotebook", background=theme.bg_secondary, borderwidth=0,
                         tabmargins=[0, 0, 0, 0])
        style.configure("TNotebook.Tab", background=theme.ctrl_bg,
                         foreground=theme.fg_secondary, padding=[12, 4],
                         font=theme.font("md"), borderwidth=0)
        style.map("TNotebook.Tab",
                   background=[("selected", theme.bg_secondary),
                               ("active", theme.ctrl_hover)],
                   foreground=[("selected", theme.fg_bright),
                               ("active", theme.fg_bright)])
        style.layout("TNotebook", [("TNotebook.client", {"sticky": "nswe"})])

        style.configure("TCombobox", fieldbackground=theme.bg_primary,
                         background=theme.ctrl_bg, foreground=theme.fg_primary,
                         arrowcolor=theme.fg_primary, borderwidth=0,
                         lightcolor=theme.bg_primary, darkcolor=theme.bg_primary)
        style.map("TCombobox",
                   fieldbackground=[("readonly", theme.bg_primary)],
                   selectbackground=[("readonly", theme.bg_primary)],
                   selectforeground=[("readonly", theme.fg_primary)],
                   lightcolor=[("readonly", theme.bg_primary)],
                   darkcolor=[("readonly", theme.bg_primary)])

        style.configure("Treeview", background=theme.bg_primary,
                         foreground=theme.fg_primary, fieldbackground=theme.bg_primary,
                         font=theme.font("md", mono=True), borderwidth=0, relief=tk.FLAT)
        style.configure("Treeview.Heading", background=theme.ctrl_bg,
                         foreground=theme.fg_primary, font=theme.font("md", bold=True, mono=True),
                         borderwidth=0, relief=tk.FLAT)
        style.map("Treeview", background=[("selected", theme.accent)])
        style.map("Treeview.Heading",
                   background=[("active", theme.ctrl_hover),
                               ("!active", theme.ctrl_bg)],
                   foreground=[("active", theme.fg_bright),
                               ("!active", theme.fg_primary)])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        style.element_create("dark.thumb", "from", "clam")
        style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": True, "sticky": "nswe"})
            ]})
        ])
        style.configure("Vertical.TScrollbar",
                         background=theme.ctrl_scrollbar,
                         troughcolor=theme.bg_primary,
                         borderwidth=0, relief=tk.FLAT, width=10)
        style.map("Vertical.TScrollbar",
                   background=[("active", theme.ctrl_scrollbar_active),
                               ("!active", theme.ctrl_scrollbar)])

    def _on_tab_changed(self, e):
        nb = e.widget
        tab_text = nb.tab(nb.select(), "text")
        if tab_text == "MemoryTest":
            self.memory_tab.start_polling()
        else:
            self.memory_tab.stop_polling()

    def _on_refresh(self):
        self.layout_tab.status_var.set("Triggering DumpStreamingGenerationLog ...")
        self.update_idletasks()

        def _bg():
            resp = trigger_dump()
            if not resp.get("success"):
                self.after(0, lambda: self.layout_tab.status_var.set(
                    f"Trigger failed: {resp.get('error', '?')}"))
                return

            self.after(0, lambda: self.layout_tab.status_var.set(
                "Waiting for log generation ..."))
            time.sleep(2)

            log_path = None
            for _ in range(10):
                log_path = find_latest_log()
                if log_path and os.path.exists(log_path):
                    if time.time() - os.path.getmtime(log_path) < 30:
                        break
                time.sleep(1)

            if not log_path or not os.path.exists(log_path):
                self.after(0, lambda: self.layout_tab.status_var.set(
                    "Error: Could not find StreamingGeneration log"))
                return

            actors, cells = parse_log(log_path)
            self.after(0, lambda: self._reload_data(actors, cells, log_path))

        threading.Thread(target=_bg, daemon=True).start()

    def _reload_data(self, actors, cells, log_path):
        self.layout_tab.reload(actors, cells, log_path)
        project_name = (os.path.basename(os.path.dirname(log_path))
                        if log_path else "")
        self.memory_tab.reload(actors, cells, project_name)


def main():
    log_path = _find_existing_log()
    if not log_path:
        print("[reallink] No existing StreamingGeneration log found.")
        print("[reallink] Click 'Refresh' in the StreamingLayout tab to trigger.")
        actors, cells = {}, []
        log_path = ""
    else:
        print(f"[reallink] Using existing log: {log_path}")
        actors, cells = parse_log(log_path)
        print(f"[reallink] {len(actors)} actors, {len(cells)} cells")

    ReallinkUefnEditor(actors, cells, log_path).mainloop()


if __name__ == "__main__":
    main()
