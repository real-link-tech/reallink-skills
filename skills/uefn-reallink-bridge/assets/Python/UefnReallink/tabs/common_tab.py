"""tabs/common_tab.py — Common Tab: 控制台指令输入 + 历史记录"""

import threading
import tkinter as tk
from tkinter import ttk

from ..core.theme import theme
from ..core.bridge import connection, uefn_cmd


class CommonTab(ttk.Frame):
    """控制台指令面板：输入框 + Send 按钮 + 历史记录。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.configure(style="Dark.TFrame")
        self._build_ui()
        connection.subscribe(self._on_connection_changed)
        self._apply_connection(connection.connected)

    def _build_ui(self):
        self.configure(style="Dark.TFrame")

        # ── Input row ────────────────────────────────────────────────────────
        input_row = tk.Frame(self, bg=theme.bg_secondary)
        input_row.pack(fill=tk.X, padx=10, pady=(12, 4))

        tk.Label(input_row, text="Console:", bg=theme.bg_secondary, fg=theme.fg_secondary,
                 font=theme.font("md")).pack(side=tk.LEFT, padx=(0, 6))

        self._cmd_var = tk.StringVar()
        self._entry = tk.Entry(input_row, textvariable=self._cmd_var,
                               bg=theme.bg_input, fg=theme.fg_primary, insertbackground=theme.fg_primary,
                               font=theme.font("xl"), relief=tk.FLAT,
                               highlightthickness=1, highlightbackground=theme.ctrl_border,
                               highlightcolor=theme.accent)
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self._entry.bind("<Return>", lambda _: self._send())

        self._send_btn = tk.Button(input_row, text="Send", bg=theme.accent, fg=theme.fg_primary,
                                   font=theme.font("md", bold=True), relief=tk.FLAT,
                                   padx=12, pady=4, cursor="hand2",
                                   command=self._send)
        self._send_btn.pack(side=tk.LEFT, padx=(6, 0))

        # ── Status line ───────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self._status_var, bg=theme.bg_secondary, fg=theme.fg_secondary,
                 font=theme.font("sm"), anchor=tk.W).pack(fill=tk.X, padx=10)

        # ── History ───────────────────────────────────────────────────────────
        hist_frame = tk.Frame(self, bg=theme.bg_primary)
        hist_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))

        tk.Label(hist_frame, text="History", bg=theme.bg_primary, fg=theme.fg_muted,
                 font=theme.font("sm")).pack(anchor=tk.W)

        scroll = tk.Scrollbar(hist_frame, orient=tk.VERTICAL)
        self._history = tk.Text(hist_frame, bg=theme.bg_input, fg=theme.fg_primary,
                                font=theme.font("md"), relief=tk.FLAT,
                                state=tk.DISABLED, wrap=tk.WORD,
                                yscrollcommand=scroll.set,
                                highlightthickness=0)
        scroll.configure(command=self._history.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._history.pack(fill=tk.BOTH, expand=True)

        # Tag styles
        self._history.tag_configure("cmd",    foreground=theme.action_blue_fg, font=theme.font("md", bold=True))
        self._history.tag_configure("ok",     foreground=theme.status_ok)
        self._history.tag_configure("err",    foreground=theme.status_error)
        self._history.tag_configure("ts",     foreground=theme.fg_muted, font=theme.font("sm"))

    # ── Send ──────────────────────────────────────────────────────────────────

    def _send(self):
        cmd = self._cmd_var.get().strip()
        if not cmd:
            return
        if not connection.connected:
            self._status_var.set("Editor not connected")
            return

        self._cmd_var.set("")
        self._status_var.set("Sending...")
        self._send_btn.configure(state=tk.DISABLED)

        def _bg():
            code = (
                "world = unreal.EditorLevelLibrary.get_editor_world()\n"
                f"unreal.SystemLibrary.execute_console_command(world, {cmd!r})\n"
                "result = 'ok'\n"
            )
            resp = uefn_cmd(code, activate=True)
            self.after(0, lambda: self._on_result(cmd, resp))

        threading.Thread(target=_bg, daemon=True).start()

    def _on_result(self, cmd: str, resp: dict):
        self._send_btn.configure(state=tk.NORMAL)
        success = resp.get("success", False)
        result = resp.get("result", "") or resp.get("error", "")
        self._status_var.set("OK" if success else f"Error: {result}")
        self._append_history(cmd, result, success)

    def _append_history(self, cmd: str, result: str, success: bool):
        import time
        ts = time.strftime("%H:%M:%S")
        self._history.configure(state=tk.NORMAL)
        self._history.insert(tk.END, f"[{ts}] ", "ts")
        self._history.insert(tk.END, f"> {cmd}\n", "cmd")
        if result:
            tag = "ok" if success else "err"
            self._history.insert(tk.END, f"  {result}\n", tag)
        self._history.insert(tk.END, "\n")
        self._history.configure(state=tk.DISABLED)
        self._history.see(tk.END)

    # ── Connection state ──────────────────────────────────────────────────────

    def _on_connection_changed(self, connected: bool):
        self.after(0, lambda: self._apply_connection(connected))

    def _apply_connection(self, connected: bool):
        state = tk.NORMAL if connected else tk.DISABLED
        self._entry.configure(state=state)
        self._send_btn.configure(state=state)
        if not connected:
            self._status_var.set("Editor disconnected — commands unavailable")
        else:
            self._status_var.set("")
