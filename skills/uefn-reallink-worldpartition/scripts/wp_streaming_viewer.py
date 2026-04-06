"""
wp_streaming_viewer.py — World Partition Streaming Viewer (入口)
================================================================
Usage: python wp_streaming_viewer.py
"""

import os
import time
import tkinter as tk
from tkinter import ttk, messagebox

from wp_common import BG, BG2, FG, ACCENT
from wp_bridge import trigger_dump, find_latest_log
from wp_parser import parse_log
from wp_layout_tab import LayoutTab
from wp_memory_tab import MemoryTab


class StreamingViewer(tk.Tk):
    def __init__(self, actors, cells, log_path):
        super().__init__()
        self.title("World Partition Streaming Viewer")
        self.geometry("1400x900")
        self.minsize(900, 600)
        self.attributes("-topmost", True)
        self.configure(bg=BG2)

        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=BG2, foreground=FG, borderwidth=0,
                         focuscolor=BG2, relief=tk.FLAT)
        style.configure("TFrame", background=BG2, borderwidth=0)
        style.configure("TLabelframe", background=BG2, foreground=FG, borderwidth=0)
        style.configure("TLabelframe.Label", background=BG2, foreground=FG)
        style.configure("TPanedwindow", background=BG2)

        # Notebook
        style.configure("TNotebook", background=BG2, borderwidth=0,
                         tabmargins=[0, 0, 0, 0])
        style.configure("TNotebook.Tab", background="#3c3c3c", foreground="#ccc",
                         padding=[12, 4], font=("Consolas", 9), borderwidth=0)
        style.map("TNotebook.Tab",
                   background=[("selected", BG2), ("active", "#505050")],
                   foreground=[("selected", "#fff"), ("active", "#eee")])
        style.layout("TNotebook", [("TNotebook.client", {"sticky": "nswe"})])

        # Combobox
        style.configure("TCombobox", fieldbackground=BG, background="#3c3c3c",
                         foreground=FG, arrowcolor=FG, borderwidth=0,
                         lightcolor=BG, darkcolor=BG)
        style.map("TCombobox",
                   fieldbackground=[("readonly", BG)],
                   selectbackground=[("readonly", BG)],
                   selectforeground=[("readonly", FG)],
                   lightcolor=[("readonly", BG)],
                   darkcolor=[("readonly", BG)])

        # Treeview
        style.configure("Treeview", background=BG, foreground=FG,
                         fieldbackground=BG, font=("Consolas", 9),
                         borderwidth=0, relief=tk.FLAT)
        style.configure("Treeview.Heading", background="#3c3c3c",
                         foreground="#ddd", font=("Consolas", 9, "bold"),
                         borderwidth=0, relief=tk.FLAT)
        style.map("Treeview", background=[("selected", ACCENT)])
        style.map("Treeview.Heading",
                   background=[("active", "#505050"), ("!active", "#3c3c3c")],
                   foreground=[("active", "#fff"), ("!active", "#ddd")])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        # Scrollbar — minimal dark style
        style.element_create("dark.thumb", "from", "clam")
        style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": True, "sticky": "nswe"})
            ]})
        ])
        style.configure("Vertical.TScrollbar",
                         background="#444", troughcolor=BG,
                         borderwidth=0, relief=tk.FLAT, width=10)
        style.map("Vertical.TScrollbar",
                   background=[("active", "#555"), ("!active", "#444")])

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.layout_tab = LayoutTab(notebook, actors, cells, log_path)
        notebook.add(self.layout_tab, text="Layout")

        project_name = os.path.basename(os.path.dirname(log_path)) if log_path else ""
        self.memory_tab = MemoryTab(notebook, actors, cells, project_name=project_name)
        notebook.add(self.memory_tab, text="Memory")

        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        total = sum(c.actor_count for c in cells)
        status = f"Cells: {len(cells)} | Actors: {total} | {os.path.basename(log_path)}"
        tk.Label(self, text=status, bg="#333", fg="#aaa",
                 font=("Consolas", 9), anchor=tk.W).pack(fill=tk.X)

    def _on_tab_changed(self, e):
        nb = e.widget
        tab_text = nb.tab(nb.select(), "text")
        if tab_text == "Memory":
            self.memory_tab.start_polling()
        else:
            self.memory_tab.stop_polling()


def main():
    print("[wp] Triggering wp.Editor.DumpStreamingGenerationLog ...")
    resp = trigger_dump()
    if not resp.get("success"):
        print(f"[wp] Warning: {resp}")

    print("[wp] Waiting for log generation ...")
    time.sleep(2)

    log_path = None
    for _ in range(10):
        log_path = find_latest_log()
        if log_path and os.path.exists(log_path):
            if time.time() - os.path.getmtime(log_path) < 30:
                break
        time.sleep(1)

    if not log_path or not os.path.exists(log_path):
        messagebox.showerror("Error",
            "Could not find StreamingGeneration log.\nIs UEFN running with UefnReallink?")
        return

    print(f"[wp] Parsing: {log_path}")
    actors, cells = parse_log(log_path)
    print(f"[wp] {len(actors)} actors, {len(cells)} cells")

    if not cells:
        messagebox.showwarning("Warning", f"No cells found.\n{log_path}")
        return

    StreamingViewer(actors, cells, log_path).mainloop()


if __name__ == "__main__":
    main()
