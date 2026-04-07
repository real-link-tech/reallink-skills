"""widgets/connection_status.py — 右下角编辑器连接状态指示器"""

import tkinter as tk
from ..core.bridge import connection
from ..core.theme import theme


class ConnectionStatusBar(tk.Frame):
    """右下角状态栏：绿/红圆点 + 文字，订阅 ConnectionManager 状态变化。"""

    _DOT_CONNECTED = "●"
    _DOT_DISCONNECTED = "●"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=theme.bg_tertiary, **kwargs)

        self._dot = tk.Label(self, text=self._DOT_DISCONNECTED,
                             fg=theme.status_disconnected, bg=theme.bg_tertiary,
                             font=theme.font("lg"))
        self._dot.pack(side=tk.LEFT, padx=(6, 2))

        self._label = tk.Label(self, text="Disconnected",
                               fg=theme.fg_secondary, bg=theme.bg_tertiary,
                               font=theme.font("md"))
        self._label.pack(side=tk.LEFT, padx=(0, 8))

        # Subscribe to connection changes (called from background thread)
        connection.subscribe(self._on_status_changed)

        # Reflect initial state
        self._apply(connection.connected)

    def _on_status_changed(self, connected: bool):
        # Schedule UI update on main thread
        self.after(0, lambda: self._apply(connected))

    def _apply(self, connected: bool):
        if connected:
            self._dot.configure(fg=theme.status_connected)
            self._label.configure(text="Connected", fg=theme.fg_secondary)
        else:
            self._dot.configure(fg=theme.status_disconnected)
            self._label.configure(text="Disconnected", fg=theme.fg_muted)
